from uuid import UUID

from fastapi.testclient import TestClient

from ai_workshop.labs.rag.deployments.domain import ProviderKind
from ai_workshop.labs.rag.deployments.service import (
    DeploymentHealthResult,
    get_deployment_health_service,
)
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole

VERSION_ID = UUID("10000000-0000-0000-0000-000000000001")


def user(role: UserRole) -> User:
    return User(
        id=UUID("20000000-0000-0000-0000-000000000001"),
        display_name="Synthetic user",
        email="synthetic.user@example.test",
        normalized_email="synthetic.user@example.test",
        password_hash="fixture-hash",
        role=role,
        is_active=True,
    )


class HealthService:
    def __init__(self, result: DeploymentHealthResult | None = None) -> None:
        self.calls: list[tuple[UUID, UUID]] = []
        self.result = result or DeploymentHealthResult(
            status="ready",
            safe_error_code=None,
            provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
            provider_model_id="runtime/exact-model",
            observed_provider_model_id="runtime/exact-model",
            latency_ms=6,
        )

    async def check(self, version_id: UUID, *, actor_id: UUID) -> DeploymentHealthResult:
        self.calls.append((version_id, actor_id))
        return self.result


def test_owner_health_check_returns_only_safe_fields() -> None:
    owner = user(UserRole.OWNER)
    service = HealthService()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_deployment_health_service] = lambda: service

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/admin/rag/deployment-versions/{VERSION_ID}/health-check"
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "safe_error_code": None,
        "provider": "local_openai_compatible",
        "provider_model_id": "runtime/exact-model",
        "observed_provider_model_id": "runtime/exact-model",
        "latency_ms": 6,
    }
    assert service.calls == [(VERSION_ID, owner.id)]
    assert "endpoint" not in response.text
    assert "reference" not in response.text
    assert "secret" not in response.text


def test_owner_health_check_returns_safe_failed_model_mismatch() -> None:
    owner = user(UserRole.OWNER)
    service = HealthService(
        DeploymentHealthResult(
            status="failed",
            safe_error_code="provider_invalid_response",
            provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
            provider_model_id="runtime/exact-model",
            observed_provider_model_id=None,
            latency_ms=4,
        )
    )
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: owner
    app.dependency_overrides[get_deployment_health_service] = lambda: service

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/admin/rag/deployment-versions/{VERSION_ID}/health-check"
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "failed",
        "safe_error_code": "provider_invalid_response",
        "provider": "local_openai_compatible",
        "provider_model_id": "runtime/exact-model",
        "observed_provider_model_id": None,
        "latency_ms": 4,
    }


def test_member_cannot_run_deployment_health_check() -> None:
    service = HealthService()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user(UserRole.MEMBER)
    app.dependency_overrides[get_deployment_health_service] = lambda: service

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/admin/rag/deployment-versions/{VERSION_ID}/health-check"
        )

    assert response.status_code == 403
    assert service.calls == []
