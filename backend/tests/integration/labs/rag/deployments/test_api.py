import asyncio
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from fastapi import Depends
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.deployments import domain as deployment_domain
from ai_workshop.labs.rag.deployments.domain import ModelDeploymentVersion
from ai_workshop.labs.rag.deployments.repository import (
    DeploymentCatalogEntry,
    DeploymentRepositoryConflict,
    SqlAlchemyDeploymentRepository,
)
from ai_workshop.labs.rag.deployments.service import (
    DeploymentHealthService,
    DeploymentRegistryService,
    get_deployment_health_service,
    get_deployment_registry_service,
)
from ai_workshop.labs.rag.generation.execution import (
    ProviderExecutionMetadata,
    ProviderHealthResult,
    ResolvedGenerationRuntime,
)
from ai_workshop.labs.rag.models.domain import ModelDefinition, ModelKind, freeze_json
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.shared.db import create_engine, create_session_factory, get_session
from alembic import command

pytestmark = pytest.mark.integration
BACKEND_ROOT = Path(__file__).resolve().parents[5]


class MemoryDeploymentRepository:
    def __init__(self, model: ModelDefinition) -> None:
        self.model = model
        self.identities: dict[UUID, UUID] = {}
        self.versions: list[DeploymentCatalogEntry] = []
        self.registered_secret_references: set[str] = set()
        self.conflict_on_identity = False
        self.conflict_on_add = False

    async def get_model_definition(self, model_id: UUID) -> ModelDefinition | None:
        return self.model if model_id == self.model.id else None

    async def create_identity(
        self, deployment_id: UUID, *, created_by: UUID, created_at: datetime
    ) -> None:
        del created_at
        if self.conflict_on_identity or deployment_id in self.identities:
            raise DeploymentRepositoryConflict
        self.identities[deployment_id] = created_by

    async def identity_exists(self, deployment_id: UUID, *, for_update: bool) -> bool:
        del for_update
        return deployment_id in self.identities

    async def next_version(self, deployment_id: UUID) -> int:
        versions = [
            item.deployment.version
            for item in self.versions
            if item.deployment.deployment_id == deployment_id
        ]
        return max(versions, default=0) + 1

    async def ensure_secret_reference(
        self, reference_name: str, *, created_by: UUID, created_at: datetime
    ) -> None:
        del created_by, created_at
        self.registered_secret_references.add(reference_name)

    async def add_version(
        self, deployment: ModelDeploymentVersion
    ) -> ModelDeploymentVersion:
        if self.conflict_on_add or any(
            (item.deployment.deployment_id, item.deployment.version)
            == (deployment.deployment_id, deployment.version)
            for item in self.versions
        ):
            raise DeploymentRepositoryConflict
        self.versions.append(
            DeploymentCatalogEntry(
                deployment=deployment,
                model_name=self.model.name,
                model_version=self.model.version,
            )
        )
        return deployment

    async def list_versions(self) -> list[DeploymentCatalogEntry]:
        return list(self.versions)


def user(role: UserRole) -> User:
    return User(
        id=uuid4(),
        display_name=role.value,
        email=f"{role.value}@example.test",
        normalized_email=f"{role.value}@example.test",
        password_hash="synthetic-hash",
        role=role,
    )


def llm_model() -> ModelDefinition:
    return ModelDefinition(
        id=uuid4(),
        kind=ModelKind.LLM,
        name="Public model name",
        version=7,
        config=freeze_json({}),
    )


def payload(model_id: UUID) -> dict[str, object]:
    return {
        "display_name": "OpenAI finance answers",
        "description": "Synthetic external deployment",
        "model_definition_id": str(model_id),
        "provider": "openai_responses",
        "location": "external",
        "allowed_environments": ["production"],
        "provider_model_id": "approved-model-version",
        "endpoint_ref": "openai-responses",
        "secret_ref": "openai-primary",
        "capabilities": ["structured_output", "token_accounting"],
        "external_transfer": True,
        "transmitted_data_categories": ["question", "evidence"],
        "data_processing_notice_ref": "public-notice-v1",
        "timeout_seconds": 30,
        "max_retries": 1,
        "retry_backoff_seconds": 0.5,
        "healthcheck_enabled": True,
        "development_only": False,
    }


def local_payload(model_id: UUID) -> dict[str, object]:
    return {
        **payload(model_id),
        "display_name": "Local exact health",
        "description": "Synthetic local deployment",
        "provider": "local_openai_compatible",
        "location": "local",
        "allowed_environments": ["development"],
        "endpoint_ref": "local-runtime",
        "secret_ref": None,
        "external_transfer": False,
        "transmitted_data_categories": [],
        "data_processing_notice_ref": None,
        "max_retries": 0,
    }


class AllowedHealthPolicyResolver:
    async def resolve(
        self,
        *,
        deployment: ModelDeploymentVersion,
        workspace_ids: tuple[UUID, ...],
    ) -> PolicyDecision:
        del deployment
        assert workspace_ids == ()
        return PolicyDecision(True, None, UUID(int=1), ())


class ExactHealthRuntimeResolver:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(
        self,
        deployment: ModelDeploymentVersion,
        policy: PolicyDecision,
    ) -> ResolvedGenerationRuntime:
        del policy
        return ResolvedGenerationRuntime(  # type: ignore[arg-type]
            deployment,
            ExactHealthRuntime(deployment, self),
        )


class ExactHealthRuntime:
    def __init__(
        self,
        deployment: ModelDeploymentVersion,
        resolver: ExactHealthRuntimeResolver,
    ) -> None:
        self.deployment = deployment
        self.resolver = resolver

    async def health(self) -> ProviderHealthResult:
        self.resolver.calls += 1
        return ProviderHealthResult(
            ready=True,
            observed_provider_model_id=self.deployment.provider_model_id,
            execution=ProviderExecutionMetadata(
                provider=self.deployment.provider,
                provider_model_id=self.deployment.provider_model_id,
                deployment_version_id=self.deployment.id,
                input_tokens=None,
                output_tokens=None,
                latency_ms=self.resolver.calls,
            ),
        )


def configured_service(repository: MemoryDeploymentRepository) -> DeploymentRegistryService:
    return DeploymentRegistryService(
        repository,
        endpoint_refs={
            "openai-responses": "https://endpoint-value.example.invalid"
        },
        secret_refs={
            "openai-primary": SecretStr("synthetic-configured-secret-value")
        },
    )


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def isolated_api_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    base_settings = get_settings()
    database = f"ai_workshop_t3_api_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    administrative = _database_url(base_settings.database_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        monkeypatch.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
        monkeypatch.setenv(
            "AI_WORKSHOP_PROVIDER_ENDPOINT_REFS",
            json.dumps(
                {
                    "openai-responses": "https://endpoint-value.example.invalid",
                    "local-runtime": "http://127.0.0.1:11434",
                }
            ),
        )
        monkeypatch.setenv(
            "AI_WORKSHOP_PROVIDER_SECRET_REFS",
            json.dumps(
                {
                    "openai-primary": "synthetic-primary-secret-value",
                    "openai-secondary": "synthetic-secondary-secret-value",
                }
            ),
        )
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


def seed_owner_and_model(isolated_url: str) -> tuple[User, UUID]:
    owner = user(UserRole.OWNER)
    model_id = uuid4()
    with psycopg.connect(_sync_url(isolated_url)) as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, display_name, email, normalized_email, password_hash,
                role, is_active
            ) VALUES (%s, %s, %s, %s, %s, 'owner', true)
            """,
            (
                owner.id,
                owner.display_name,
                owner.email,
                owner.normalized_email,
                owner.password_hash,
            ),
        )
        connection.execute(
            """
            INSERT INTO rag_model_definitions (id, kind, name, version, config)
            VALUES (%s, 'llm', 'PostgreSQL public model', 11, '{}'::json)
            """,
            (model_id,),
        )
        connection.commit()
    return owner, model_id


def actual_api_app(owner: User):
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: owner
    return app


def test_owner_creates_lists_and_versions_a_deployment_without_exposing_refs() -> None:
    model = llm_model()
    repository = MemoryDeploymentRepository(model)
    owner = user(UserRole.OWNER)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_deployment_registry_service] = lambda: configured_service(
        repository
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/admin/rag/deployments", json=payload(model.id)
        )
        deployment_id = created.json()["deployment_id"]
        versioned = client.post(
            f"/api/v1/admin/rag/deployments/{deployment_id}/versions",
            json={**payload(model.id), "display_name": "OpenAI finance answers v2"},
        )
        listed = client.get("/api/v1/admin/rag/deployments")

    assert created.status_code == 201
    assert created.json()["version"] == 1
    assert created.json()["secret_configured"] is True
    assert versioned.status_code == 201
    assert versioned.json()["version"] == 2
    assert [item["version"] for item in listed.json()] == [1, 2]
    assert repository.registered_secret_references == {"openai-primary"}
    for response in (created, versioned, listed):
        text = response.text
        assert "secret_ref" not in text
        assert "endpoint_ref" not in text
        assert "openai-primary" not in text
        assert "openai-responses" not in text
        assert "synthetic-configured-secret-value" not in text
        assert "endpoint-value.example.invalid" not in text


def test_member_cannot_create_or_list_admin_deployments() -> None:
    model = llm_model()
    repository = MemoryDeploymentRepository(model)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(UserRole.MEMBER)
    app.dependency_overrides[get_deployment_registry_service] = lambda: configured_service(
        repository
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/admin/rag/deployments", json=payload(model.id)
        )
        listed = client.get("/api/v1/admin/rag/deployments")

    assert created.status_code == 403
    assert listed.status_code == 403
    assert repository.identities == {}


def test_unknown_references_are_rejected_before_persistence() -> None:
    model = llm_model()
    repository = MemoryDeploymentRepository(model)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(UserRole.OWNER)
    app.dependency_overrides[get_deployment_registry_service] = lambda: configured_service(
        repository
    )

    with TestClient(app) as client:
        unknown_endpoint = client.post(
            "/api/v1/admin/rag/deployments",
            json={**payload(model.id), "endpoint_ref": "request-controlled-endpoint"},
        )
        unknown_secret = client.post(
            "/api/v1/admin/rag/deployments",
            json={**payload(model.id), "secret_ref": "request-controlled-secret"},
        )

    assert unknown_endpoint.status_code == 422
    assert unknown_endpoint.json()["error"]["code"] == "unknown_endpoint_reference"
    assert unknown_secret.status_code == 422
    assert unknown_secret.json()["error"]["code"] == "unknown_secret_reference"
    assert repository.identities == {}
    assert repository.registered_secret_references == set()
    assert "request-controlled" not in unknown_endpoint.text
    assert "request-controlled" not in unknown_secret.text


def test_missing_identity_and_identity_or_version_conflicts_are_safely_mapped() -> None:
    model = llm_model()
    repository = MemoryDeploymentRepository(model)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(UserRole.OWNER)
    app.dependency_overrides[get_deployment_registry_service] = lambda: configured_service(
        repository
    )

    with TestClient(app) as client:
        missing = client.post(
            f"/api/v1/admin/rag/deployments/{uuid4()}/versions",
            json=payload(model.id),
        )
        repository.conflict_on_identity = True
        identity_raced = client.post(
            "/api/v1/admin/rag/deployments", json=payload(model.id)
        )
        repository.conflict_on_identity = False
        repository.conflict_on_add = True
        version_raced = client.post(
            "/api/v1/admin/rag/deployments", json=payload(model.id)
        )

    assert missing.status_code == 404
    assert identity_raced.status_code == 409
    assert version_raced.status_code == 409
    assert identity_raced.json()["error"]["code"] == "deployment_version_exists"
    assert version_raced.json()["error"]["code"] == "deployment_version_exists"


def test_authenticated_options_are_safe_and_not_ready_before_health_support() -> None:
    model = llm_model()
    repository = MemoryDeploymentRepository(model)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(UserRole.OWNER)
    app.dependency_overrides[get_deployment_registry_service] = lambda: configured_service(
        repository
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/admin/rag/deployments", json=payload(model.id)
        )
        options = client.get("/api/v1/rag/deployments/options")

    assert created.status_code == 201
    assert options.status_code == 200
    assert options.json() == [
        {
            "display_name": "OpenAI finance answers",
            "model_name": "Public model name",
            "model_version": 7,
            "provider": "openai_responses",
            "provider_model_id": "approved-model-version",
            "location": "external",
            "external_transfer": True,
            "allowed_environments": ["production"],
            "capabilities": ["structured_output", "token_accounting"],
            "readiness": {
                "ready": False,
                "reason_codes": ["deployment_not_ready"],
            },
        }
    ]
    option_text = options.text
    assert str(repository.versions[0].deployment.id) not in option_text
    assert str(repository.versions[0].deployment.deployment_id) not in option_text
    assert "openai-primary" not in option_text
    assert "openai-responses\"" not in option_text
    assert "endpoint-value.example.invalid" not in option_text
    assert "synthetic-configured-secret-value" not in option_text


def test_owner_list_marks_a_stored_reference_unconfigured_when_allowlist_removed() -> None:
    model = llm_model()
    repository = MemoryDeploymentRepository(model)
    owner = user(UserRole.OWNER)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_deployment_registry_service] = lambda: configured_service(
        repository
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/admin/rag/deployments", json=payload(model.id)
        )
        app.dependency_overrides[get_deployment_registry_service] = lambda: (
            DeploymentRegistryService(
                repository,
                endpoint_refs={
                    "openai-responses": "https://endpoint-value.example.invalid"
                },
                secret_refs={},
            )
        )
        listed = client.get("/api/v1/admin/rag/deployments")

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()[0]["secret_configured"] is False
    assert "openai-primary" not in listed.text


def test_options_require_authentication() -> None:
    model = llm_model()
    repository = MemoryDeploymentRepository(model)
    app = create_app()
    app.dependency_overrides[get_deployment_registry_service] = lambda: configured_service(
        repository
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/rag/deployments/options")

    assert response.status_code == 401


def test_postgresql_api_create_list_and_repository_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_api_database(monkeypatch) as isolated_url:
        owner, model_id = seed_owner_and_model(isolated_url)
        app = actual_api_app(owner)
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/admin/rag/deployments", json=payload(model_id)
            )
            listed = client.get("/api/v1/admin/rag/deployments")
            health = client.post(
                "/api/v1/admin/rag/deployment-versions/"
                f"{created.json()['version_id']}/health-check"
            )

        assert created.status_code == 201
        assert listed.status_code == 200
        assert listed.json() == [created.json()]
        assert health.status_code == 200
        assert health.json()["status"] == "failed"
        assert health.json()["safe_error_code"] == (
            "deployment_not_allowed_in_environment"
        )
        deployment_id = UUID(created.json()["deployment_id"])

        async def verify_repository_paths() -> None:
            engine = create_engine(get_settings())
            sessions = create_session_factory(engine)
            try:
                async with sessions.begin() as session:
                    repository = SqlAlchemyDeploymentRepository(session)
                    assert await repository.identity_exists(
                        deployment_id, for_update=True
                    )
                    assert await repository.next_version(deployment_id) == 2
                    model = await repository.get_model_definition(model_id)
                    assert model is not None
                    assert model.name == "PostgreSQL public model"
                    entries = await repository.list_versions()
                    assert len(entries) == 1
                    assert entries[0].deployment.id == UUID(
                        created.json()["version_id"]
                    )
                    await repository.ensure_secret_reference(
                        "openai-primary",
                        created_by=owner.id,
                        created_at=datetime.now(UTC),
                    )
            finally:
                await engine.dispose()

        asyncio.run(verify_repository_paths())

        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM rag_model_deployments"
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT count(*) FROM rag_model_deployment_versions"
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT status, safe_error_code "
                "FROM rag_model_deployment_health_checks"
            ).fetchall() == [
                ("failed", "deployment_not_allowed_in_environment")
            ]
            assert connection.execute(
                "SELECT namespace, reference_name FROM rag_secret_references"
            ).fetchall() == [("provider_secret", "openai-primary")]


def test_postgresql_local_health_appends_two_immutable_rows_and_reads_latest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_api_database(monkeypatch) as isolated_url:
        owner, model_id = seed_owner_and_model(isolated_url)
        runtime_resolver = ExactHealthRuntimeResolver()
        app = actual_api_app(owner)

        def health_service(
            session: Annotated[AsyncSession, Depends(get_session)],
        ) -> DeploymentHealthService:
            return DeploymentHealthService(
                SqlAlchemyDeploymentRepository(session),
                AllowedHealthPolicyResolver(),
                runtime_resolver,
            )

        app.dependency_overrides[get_deployment_health_service] = health_service
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/admin/rag/deployments",
                json=local_payload(model_id),
            )
            version_id = UUID(created.json()["version_id"])
            first = client.post(
                f"/api/v1/admin/rag/deployment-versions/{version_id}/health-check"
            )
            second = client.post(
                f"/api/v1/admin/rag/deployment-versions/{version_id}/health-check"
            )

        assert created.status_code == 201
        assert first.status_code == second.status_code == 200
        assert first.json()["status"] == second.json()["status"] == "ready"
        assert first.json()["observed_provider_model_id"] == "approved-model-version"
        assert second.json()["observed_provider_model_id"] == "approved-model-version"
        assert first.json()["latency_ms"] == 1
        assert second.json()["latency_ms"] == 2

        async def verify_latest() -> None:
            engine = create_engine(get_settings())
            sessions = create_session_factory(engine)
            try:
                async with sessions.begin() as session:
                    latest = await SqlAlchemyDeploymentRepository(
                        session
                    ).latest_health_check(version_id)
                    assert latest is not None
                    assert latest.status == "ready"
                    assert latest.observed_provider_model_id == "approved-model-version"
                    assert latest.latency_ms == 2
            finally:
                await engine.dispose()

        asyncio.run(verify_latest())

        with psycopg.connect(_sync_url(isolated_url), autocommit=True) as connection:
            rows = connection.execute(
                """
                SELECT id, status, safe_error_code, observed_provider_model_id,
                       latency_ms
                FROM rag_model_deployment_health_checks
                WHERE deployment_version_id = %s
                ORDER BY created_at, id
                """,
                (version_id,),
            ).fetchall()
            assert [row[1:] for row in rows] == [
                ("ready", None, "approved-model-version", 1),
                ("ready", None, "approved-model-version", 2),
            ]
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                connection.execute(
                    "UPDATE rag_model_deployment_health_checks "
                    "SET status = 'failed' WHERE id = %s",
                    (rows[0][0],),
                )
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                connection.execute(
                    "DELETE FROM rag_model_deployment_health_checks WHERE id = %s",
                    (rows[0][0],),
                )
            assert connection.execute(
                "SELECT count(*) FROM rag_model_deployment_health_checks "
                "WHERE deployment_version_id = %s",
                (version_id,),
            ).fetchone() == (2,)


def test_postgresql_api_rolls_back_identity_and_registry_on_unique_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_api_database(monkeypatch) as isolated_url:
        owner, model_id = seed_owner_and_model(isolated_url)
        app = actual_api_app(owner)
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/admin/rag/deployments", json=payload(model_id)
            )
            existing_version_id = UUID(created.json()["version_id"])
            monkeypatch.setattr(
                deployment_domain,
                "uuid4",
                lambda: existing_version_id,
            )
            conflicted = client.post(
                "/api/v1/admin/rag/deployments",
                json={
                    **payload(model_id),
                    "display_name": "Rolled back deployment",
                    "secret_ref": "openai-secondary",
                },
            )

        assert created.status_code == 201
        assert conflicted.status_code == 409
        assert conflicted.json()["error"]["code"] == "deployment_version_exists"
        assert "synthetic-secondary-secret-value" not in conflicted.text
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM rag_model_deployments"
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT count(*) FROM rag_model_deployment_versions"
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT reference_name FROM rag_secret_references ORDER BY reference_name"
            ).fetchall() == [("openai-primary",)]


def test_postgresql_concurrent_versions_are_serialized_without_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_api_database(monkeypatch) as isolated_url:
        owner, model_id = seed_owner_and_model(isolated_url)
        app = actual_api_app(owner)
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/admin/rag/deployments", json=payload(model_id)
            )
        deployment_id = created.json()["deployment_id"]

        def create_version(display_name: str):
            with TestClient(app) as concurrent_client:
                return concurrent_client.post(
                    f"/api/v1/admin/rag/deployments/{deployment_id}/versions",
                    json={**payload(model_id), "display_name": display_name},
                )

        executor = ThreadPoolExecutor(max_workers=2)
        futures = [
            executor.submit(create_version, "Concurrent A"),
            executor.submit(create_version, "Concurrent B"),
        ]
        try:
            completed, pending = wait(futures, timeout=10)
            assert not pending, "Concurrent Deployment requests exceeded 10 seconds."
            responses = [future.result() for future in completed]
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        assert created.status_code == 201
        assert [response.status_code for response in responses] == [201, 201]
        assert {response.json()["version"] for response in responses} == {2, 3}
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            versions = connection.execute(
                """
                SELECT version FROM rag_model_deployment_versions
                WHERE deployment_id = %s ORDER BY version
                """,
                (UUID(deployment_id),),
            ).fetchall()
        assert versions == [(1,), (2,), (3,)]


def test_postgresql_identity_lock_blocks_second_session_until_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_api_database(monkeypatch) as isolated_url:
        owner, model_id = seed_owner_and_model(isolated_url)
        app = actual_api_app(owner)
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/admin/rag/deployments", json=payload(model_id)
            )
        deployment_id = UUID(created.json()["deployment_id"])

        async def verify_locking() -> None:
            engine = create_engine(get_settings())
            sessions = create_session_factory(engine)
            try:
                async with sessions() as first, sessions() as second:
                    first_transaction = await first.begin()
                    second_transaction = await second.begin()
                    first_repository = SqlAlchemyDeploymentRepository(first)
                    second_repository = SqlAlchemyDeploymentRepository(second)
                    assert await first_repository.identity_exists(
                        deployment_id, for_update=True
                    )
                    blocked = asyncio.create_task(
                        second_repository.identity_exists(
                            deployment_id, for_update=True
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

        asyncio.run(verify_locking())
