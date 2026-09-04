import asyncio
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import make_url

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.policies import domain as policy_domain
from ai_workshop.labs.rag.policies.repository import SqlAlchemyDataPolicyRepository
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.shared.db import create_engine, create_session_factory
from alembic import command

pytestmark = pytest.mark.integration
BACKEND_ROOT = Path(__file__).resolve().parents[5]
INSTALLATION_V1_ID = UUID("00000000-0000-0000-0000-00000000d002")


def user(role: UserRole) -> User:
    identifier = uuid4()
    return User(
        id=identifier,
        display_name=role.value,
        email=f"{identifier}@example.test",
        normalized_email=f"{identifier}@example.test",
        password_hash="synthetic-hash",
        role=role,
    )


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(
        hide_password=False
    )


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def isolated_policy_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    base_settings = get_settings()
    database = f"ai_workshop_t4_policy_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    administrative = _database_url(base_settings.database_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        monkeypatch.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
        get_settings.cache_clear()
        command.upgrade(
            Config(str(BACKEND_ROOT / "alembic.ini")),
            "0016_rag_llm_deployments",
        )
        yield isolated_url
    finally:
        get_settings.cache_clear()
        with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )


def seed_users_and_workspaces(
    isolated_url: str,
) -> tuple[User, User, tuple[UUID, UUID]]:
    owner = user(UserRole.OWNER)
    member = user(UserRole.MEMBER)
    workspace_ids = (uuid4(), uuid4())
    with psycopg.connect(_sync_url(isolated_url)) as connection:
        for actor in (owner, member):
            connection.execute(
                """
                INSERT INTO users (
                    id, display_name, email, normalized_email, password_hash,
                    role, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, true)
                """,
                (
                    actor.id,
                    actor.display_name,
                    actor.email,
                    actor.normalized_email,
                    actor.password_hash,
                    actor.role.value,
                ),
            )
        for workspace_id in workspace_ids:
            connection.execute(
                """
                INSERT INTO workspaces (id, name, kind, created_by, expires_at)
                VALUES (%s, %s, 'personal', %s, NULL)
                """,
                (workspace_id, f"Synthetic workspace {workspace_id}", owner.id),
            )
        connection.commit()
    return owner, member, workspace_ids


def installation_payload(
    mode: str = "deny", providers: list[str] | None = None
) -> dict[str, object]:
    return {
        "mode": mode,
        "approved_providers": providers or [],
    }


def workspace_payload(
    mode: str = "inherit", providers: list[str] | None = None
) -> dict[str, object]:
    return {
        "mode": mode,
        "approved_providers": providers or [],
    }


def test_owner_only_policy_api_appends_versions_and_rejects_widening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_policy_database(monkeypatch) as isolated_url:
        owner, member, (workspace_id, _) = seed_users_and_workspaces(isolated_url)
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: owner

        with TestClient(app) as client:
            seeded = client.get("/api/v1/admin/rag/data-policies/installation")
            approved = client.post(
                "/api/v1/admin/rag/data-policies/installation/versions",
                json=installation_payload(
                    "approved_providers", ["openai_responses"]
                ),
            )
            current = client.get("/api/v1/admin/rag/data-policies/installation")
            missing_get = client.get(
                f"/api/v1/admin/rag/data-policies/workspaces/{uuid4()}"
            )
            missing_post = client.post(
                f"/api/v1/admin/rag/data-policies/workspaces/{uuid4()}/versions",
                json=workspace_payload(),
            )
            first_workspace = client.post(
                f"/api/v1/admin/rag/data-policies/workspaces/{workspace_id}/versions",
                json=workspace_payload(
                    "approved_providers", ["openai_responses"]
                ),
            )
            second_workspace = client.post(
                f"/api/v1/admin/rag/data-policies/workspaces/{workspace_id}/versions",
                json=workspace_payload("deny"),
            )
            current_workspace = client.get(
                f"/api/v1/admin/rag/data-policies/workspaces/{workspace_id}"
            )
            tightened = client.post(
                "/api/v1/admin/rag/data-policies/installation/versions",
                json=installation_payload("deny"),
            )
            widening = client.post(
                f"/api/v1/admin/rag/data-policies/workspaces/{workspace_id}/versions",
                json=workspace_payload(
                    "approved_providers", ["openai_responses"]
                ),
            )

            app.dependency_overrides[get_current_user] = lambda: member
            member_read = client.get(
                "/api/v1/admin/rag/data-policies/installation"
            )
            member_write = client.post(
                "/api/v1/admin/rag/data-policies/installation/versions",
                json=installation_payload("deny"),
            )
            app.dependency_overrides.pop(get_current_user)
            anonymous = client.get(
                "/api/v1/admin/rag/data-policies/installation"
            )

        assert seeded.status_code == 200
        assert seeded.json()["version"] == 1
        assert seeded.json()["mode"] == "deny"
        assert approved.status_code == 201
        assert approved.json()["version"] == 2
        assert current.json() == approved.json()
        assert missing_get.status_code == 404
        assert missing_post.status_code == 404
        assert missing_get.json()["error"]["code"] == "not_found"
        assert first_workspace.status_code == 201
        assert first_workspace.json()["version"] == 1
        assert second_workspace.status_code == 201
        assert second_workspace.json()["version"] == 2
        assert current_workspace.json() == second_workspace.json()
        assert tightened.status_code == 201
        assert tightened.json()["version"] == 3
        assert widening.status_code == 422
        assert widening.json()["error"]["code"] == "invalid_data_policy"
        assert "cannot widen" not in widening.text.casefold()
        assert member_read.status_code == 403
        assert member_write.status_code == 403
        assert member_read.json()["error"]["code"] == "owner_required"
        assert anonymous.status_code == 401

        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                "SELECT version FROM rag_installation_data_policy_versions "
                "ORDER BY version"
            ).fetchall() == [(1,), (2,), (3,)]
            assert connection.execute(
                "SELECT version FROM rag_workspace_data_policy_versions "
                "WHERE workspace_id = %s ORDER BY version",
                (workspace_id,),
            ).fetchall() == [(1,), (2,)]


def test_postgresql_concurrent_policy_versions_are_serialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_policy_database(monkeypatch) as isolated_url:
        owner, _, (workspace_id, _) = seed_users_and_workspaces(isolated_url)
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: owner
        with TestClient(app) as client:
            first_workspace = client.post(
                f"/api/v1/admin/rag/data-policies/workspaces/{workspace_id}/versions",
                json=workspace_payload(),
            )
        assert first_workspace.status_code == 201

        def append_installation() -> object:
            with TestClient(app) as concurrent_client:
                return concurrent_client.post(
                    "/api/v1/admin/rag/data-policies/installation/versions",
                    json=installation_payload("deny"),
                )

        def append_workspace(mode: str) -> object:
            with TestClient(app) as concurrent_client:
                return concurrent_client.post(
                    f"/api/v1/admin/rag/data-policies/workspaces/{workspace_id}/versions",
                    json=workspace_payload(mode),
                )

        executor = ThreadPoolExecutor(max_workers=4)
        futures = [
            executor.submit(append_installation),
            executor.submit(append_installation),
            executor.submit(append_workspace, "inherit"),
            executor.submit(append_workspace, "deny"),
        ]
        try:
            completed, pending = wait(futures, timeout=10)
            assert not pending, "Concurrent policy requests exceeded 10 seconds."
            responses = [future.result() for future in completed]
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        assert [response.status_code for response in responses] == [201] * 4
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                "SELECT version FROM rag_installation_data_policy_versions "
                "ORDER BY version"
            ).fetchall() == [(1,), (2,), (3,)]
            assert connection.execute(
                "SELECT version FROM rag_workspace_data_policy_versions "
                "WHERE workspace_id = %s ORDER BY version",
                (workspace_id,),
            ).fetchall() == [(1,), (2,), (3,)]


def test_postgresql_policy_identity_locks_block_other_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_policy_database(monkeypatch) as isolated_url:
        _, _, (workspace_id, _) = seed_users_and_workspaces(isolated_url)

        async def verify_locks() -> None:
            engine = create_engine(get_settings())
            sessions = create_session_factory(engine)
            try:
                async with sessions() as first, sessions() as second:
                    first_transaction = await first.begin()
                    second_transaction = await second.begin()
                    first_repository = SqlAlchemyDataPolicyRepository(first)
                    second_repository = SqlAlchemyDataPolicyRepository(second)
                    await first_repository.installation_policy_id(for_update=True)
                    blocked = asyncio.create_task(
                        second_repository.installation_policy_id(for_update=True)
                    )
                    completed, pending = await asyncio.wait({blocked}, timeout=0.2)
                    assert completed == set()
                    assert pending == {blocked}
                    await first_transaction.commit()
                    assert await asyncio.wait_for(blocked, timeout=5)
                    await second_transaction.rollback()

                async with sessions() as first, sessions() as second:
                    first_transaction = await first.begin()
                    second_transaction = await second.begin()
                    first_repository = SqlAlchemyDataPolicyRepository(first)
                    second_repository = SqlAlchemyDataPolicyRepository(second)
                    assert await first_repository.workspace_exists(
                        workspace_id, for_update=True
                    )
                    blocked = asyncio.create_task(
                        second_repository.workspace_exists(
                            workspace_id, for_update=True
                        )
                    )
                    completed, pending = await asyncio.wait({blocked}, timeout=0.2)
                    assert completed == set()
                    assert pending == {blocked}
                    await first_transaction.commit()
                    assert await asyncio.wait_for(blocked, timeout=5)
                    await second_transaction.rollback()
            finally:
                await engine.dispose()

        asyncio.run(verify_locks())


def test_postgresql_policy_rollback_immutability_and_anti_widening_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_policy_database(monkeypatch) as isolated_url:
        owner, _, (workspace_id, other_workspace_id) = seed_users_and_workspaces(
            isolated_url
        )
        app = create_app()
        app.dependency_overrides[get_current_user] = lambda: owner
        with TestClient(app) as client:
            existing_workspace = client.post(
                f"/api/v1/admin/rag/data-policies/workspaces/"
                f"{other_workspace_id}/versions",
                json=workspace_payload(),
            )
            assert existing_workspace.status_code == 201
            monkeypatch.setattr(policy_domain, "uuid4", lambda: INSTALLATION_V1_ID)
            installation_conflict = client.post(
                "/api/v1/admin/rag/data-policies/installation/versions",
                json=installation_payload("deny"),
            )
            existing_workspace_version_id = UUID(
                existing_workspace.json()["version_id"]
            )
            monkeypatch.setattr(
                policy_domain,
                "uuid4",
                lambda: existing_workspace_version_id,
            )
            workspace_conflict = client.post(
                f"/api/v1/admin/rag/data-policies/workspaces/{workspace_id}/versions",
                json=workspace_payload(),
            )

        assert installation_conflict.status_code == 409
        assert workspace_conflict.status_code == 409
        assert installation_conflict.json()["error"]["code"] == (
            "data_policy_version_exists"
        )
        assert workspace_conflict.json()["error"]["code"] == (
            "data_policy_version_exists"
        )
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM rag_installation_data_policy_versions"
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT count(*) FROM rag_workspace_data_policies "
                "WHERE workspace_id = %s",
                (workspace_id,),
            ).fetchone() == (0,)

        with (
            pytest.raises(psycopg.errors.RaiseException),
            psycopg.connect(_sync_url(isolated_url)) as connection,
        ):
            connection.execute(
                "UPDATE rag_installation_data_policy_versions "
                "SET outbound_mode = 'approved_providers' WHERE version = 1"
            )

        policy_id = uuid4()
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            connection.execute(
                """
                INSERT INTO rag_workspace_data_policies (id, workspace_id)
                VALUES (%s, %s)
                """,
                (policy_id, workspace_id),
            )
            connection.commit()
        with (
            pytest.raises(psycopg.errors.RaiseException),
            psycopg.connect(_sync_url(isolated_url)) as connection,
        ):
            connection.execute(
                """
                INSERT INTO rag_workspace_data_policy_versions (
                    id, policy_id, workspace_id, version, outbound_mode,
                    approved_providers, changed_by
                ) VALUES (%s, %s, %s, 1, 'approved_providers', %s::jsonb, %s)
                """,
                (
                    uuid4(),
                    policy_id,
                    workspace_id,
                    json.dumps(["openai_responses"]),
                    owner.id,
                ),
            )

        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM rag_workspace_data_policy_versions "
                "WHERE workspace_id = %s",
                (workspace_id,),
            ).fetchone() == (0,)
