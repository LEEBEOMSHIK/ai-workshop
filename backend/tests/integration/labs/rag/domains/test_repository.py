from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.domains.repository import SqlAlchemyDomainRepository
from alembic import command

pytestmark = pytest.mark.integration
BACKEND_ROOT = Path(__file__).resolve().parents[5]
BASELINE_CONFIGURATION_VERSION_ID = UUID("00000000-0000-0000-0000-000000000503")


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def _isolated_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    settings = get_settings()
    database = f"ai_workshop_domain_repo_{uuid4().hex}"
    isolated_url = _database_url(settings.database_url, database)
    administrative = _database_url(settings.database_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        monkeypatch.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
        get_settings.cache_clear()
        command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "0023_rag_domains")
        yield isolated_url
    finally:
        get_settings.cache_clear()
        with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )


def _seed(isolated_url: str) -> dict[str, UUID]:
    ids = {
        name: uuid4()
        for name in (
            "owner",
            "member",
            "outsider",
            "allowed_workspace",
            "private_workspace",
            "domain",
            "connection",
        )
    }
    with psycopg.connect(_sync_url(isolated_url)) as connection:
        for role_name in ("owner", "member", "outsider"):
            user_id = ids[role_name]
            email = f"{user_id}@example.test"
            role = "owner" if role_name == "owner" else "member"
            connection.execute(
                """
                INSERT INTO users (
                    id, display_name, email, normalized_email, password_hash,
                    role, is_active
                ) VALUES (%s, %s, %s, %s, 'hash', %s, true)
                """,
                (user_id, role_name, email, email, role),
            )
        for workspace_name, title in (
            ("allowed_workspace", "허용 공간"),
            ("private_workspace", "비공개 공간"),
        ):
            workspace_id = ids[workspace_name]
            connection.execute(
                "INSERT INTO workspaces (id, name, kind, created_by) "
                "VALUES (%s, %s, 'team', %s)",
                (workspace_id, title, ids["owner"]),
            )
            connection.execute(
                """
                INSERT INTO rag_configuration_workspace_subscriptions (
                    id, configuration_version_id, workspace_id
                ) VALUES (%s, %s, %s)
                """,
                (uuid4(), BASELINE_CONFIGURATION_VERSION_ID, workspace_id),
            )
        connection.execute(
            """
            INSERT INTO workspace_memberships (id, workspace_id, user_id, role)
            VALUES (%s, %s, %s, 'member')
            """,
            (uuid4(), ids["allowed_workspace"], ids["member"]),
        )
        connection.execute(
            """
            INSERT INTO rag_domains (id, slug, display_name, description, created_by)
            VALUES (%s, 'fund-management', '자산운용', '', %s)
            """,
            (ids["domain"], ids["owner"]),
        )
        connection.execute(
            """
            INSERT INTO rag_domain_connection_versions (
                id, domain_id, version, configuration_version_id, created_by
            ) VALUES (%s, %s, 1, %s, %s)
            """,
            (
                ids["connection"],
                ids["domain"],
                BASELINE_CONFIGURATION_VERSION_ID,
                ids["owner"],
            ),
        )
        for workspace_id in (ids["allowed_workspace"], ids["private_workspace"]):
            connection.execute(
                """
                INSERT INTO rag_domain_connection_workspaces (
                    connection_version_id, configuration_version_id, workspace_id
                ) VALUES (%s, %s, %s)
                """,
                (ids["connection"], BASELINE_CONFIGURATION_VERSION_ID, workspace_id),
            )
        connection.execute(
            "UPDATE rag_domains SET active_connection_version_id = %s WHERE id = %s",
            (ids["connection"], ids["domain"]),
        )
        connection.commit()
    return ids


def test_repository_returns_only_actor_authorized_workspace_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_database(monkeypatch) as isolated_url:
        ids = _seed(isolated_url)

        async def verify() -> None:
            engine = create_async_engine(isolated_url)
            try:
                async with AsyncSession(engine) as session:
                    repository = SqlAlchemyDomainRepository(session)
                    domain = await repository.find_by_slug("fund-management")
                    assert domain is not None
                    assert domain.active_connection_version_id == ids["connection"]
                    connection = await repository.find_connection(ids["connection"])
                    assert connection is not None
                    assert set(connection.workspace_ids) == {
                        ids["allowed_workspace"],
                        ids["private_workspace"],
                    }
                    options = await repository.workspace_options_for_actor(
                        ids["member"], connection.workspace_ids
                    )
                    assert [(item.id, item.name) for item in options] == [
                        (ids["allowed_workspace"], "허용 공간")
                    ]
                    assert (
                        await repository.workspace_options_for_actor(
                            ids["outsider"], connection.workspace_ids
                        )
                        == ()
                    )
                    assert len(await repository.list_connections(ids["domain"])) == 1
            finally:
                await engine.dispose()

        asyncio.run(verify())
