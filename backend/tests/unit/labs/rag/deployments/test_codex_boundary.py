from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.deployments.repository import (
    DeploymentCatalogEntry,
    _version_domain,
    _version_record,
)
from ai_workshop.labs.rag.deployments.schemas import (
    DeploymentAdminResponse,
    DeploymentVersionCreate,
)
from ai_workshop.labs.rag.deployments.service import DeploymentRegistryService, DeploymentRepository
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.runtime_resolver import GenerationRuntimeResolver
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.deployments.test_domain import codex_deployment
from tests.unit.labs.rag.deployments.test_public_metadata import health
from tests.unit.labs.rag.generation.test_readiness import PROFILE_ID, VERSION_ID, readiness
from tests.unit.labs.rag.generation.test_runtime_resolver import allowed_policy


def test_codex_runtime_is_blocked_before_reference_resolution_even_with_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deployment = codex_deployment()

    def forbidden(*args: object) -> None:
        pytest.fail("Codex must be blocked before factory or endpoint resolution")

    resolver = GenerationRuntimeResolver(
        environment="test",
        endpoint_refs={},
        secret_refs={},
        factories={deployment.provider: forbidden},  # type: ignore[dict-item]
    )
    monkeypatch.setattr(resolver._endpoint_resolver, "resolve", forbidden)
    with pytest.raises(GenerationProviderError) as caught:
        resolver.resolve(deployment, allowed_policy())
    assert (caught.value.code, caught.value.retryable) == ("deployment_not_ready", False)


def test_codex_historical_ready_health_never_marks_metadata_ready() -> None:
    deployment = codex_deployment()
    entry = DeploymentCatalogEntry(
        deployment,
        "Synthetic model",
        1,
        replace(
            health(),
            deployment_version_id=deployment.id,
            observed_provider_model_id=deployment.provider_model_id,
        ),
    )
    response = DeploymentAdminResponse.from_entry(entry, secret_configured=False)
    assert response.readiness.model_dump() == {
        "ready": False,
        "reason_codes": ["deployment_not_ready"],
    }
    assert response.runner_ref == "personal-codex-v1"
    assert "endpoint_ref" not in response.model_dump()
    assert "secret_ref" not in response.model_dump()


@pytest.mark.parametrize("new_version", [False, True])
async def test_codex_registration_fails_before_repository_access(new_version: bool) -> None:
    deployment = codex_deployment()
    values = {name: getattr(deployment, name) for name in DeploymentVersionCreate.model_fields}
    request = DeploymentVersionCreate.model_validate(values)
    assert request.model_dump()["runner_ref"] == "personal-codex-v1"
    service = DeploymentRegistryService(
        cast(DeploymentRepository, object()),
        endpoint_refs={},
        secret_refs={},
    )
    with pytest.raises(AppError) as caught:
        if new_version:
            await service.create_version(uuid4(), request, actor_id=uuid4())
        else:
            await service.create_identity(request, actor_id=uuid4())
    assert caught.value.code == "deployment_not_ready"


async def test_codex_generation_readiness_rejects_historical_ready_health(monkeypatch):
    deployment = codex_deployment()
    service = readiness(
        SimpleNamespace(bindings=(), deployment_version_id=VERSION_ID),
        replace(health(), observed_provider_model_id=deployment.provider_model_id),
    )

    async def get_version(version_id):
        return deployment

    monkeypatch.setattr(service.deployments, "get_version", get_version)
    assert await service.is_ready(PROFILE_ID) is False


def test_codex_repository_roundtrip_preserves_runner_and_null_endpoint() -> None:
    deployment = codex_deployment()
    record = _version_record(deployment)
    assert record.runner_ref == "personal-codex-v1"
    assert record.endpoint_ref is None
    assert _version_domain(record) == deployment
