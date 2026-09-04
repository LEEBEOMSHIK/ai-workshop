from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.deployments.repository import DeploymentHealthCheck
from ai_workshop.labs.rag.generation.readiness import SqlAlchemyGenerationReadiness

PROFILE_ID = UUID("10000000-0000-0000-0000-000000000001")
VERSION_ID = UUID("10000000-0000-0000-0000-000000000002")


def deployment() -> ModelDeploymentVersion:
    return ModelDeploymentVersion(
        id=VERSION_ID,
        deployment_id=UUID("10000000-0000-0000-0000-000000000003"),
        version=1,
        display_name="Synthetic local runtime",
        description="Synthetic readiness fixture",
        model_definition_id=UUID("10000000-0000-0000-0000-000000000004"),
        provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
        location=ExecutionLocation.LOCAL,
        allowed_environments=(DeploymentEnvironment.DEVELOPMENT,),
        provider_model_id="runtime/exact-model",
        endpoint_ref="local-runtime",
        secret_ref=None,
        capabilities=frozenset({DeploymentCapability.STRUCTURED_OUTPUT}),
        external_transfer=False,
        transmitted_data_categories=(),
        data_processing_notice_ref=None,
        timeout_seconds=5.0,
        max_retries=0,
        retry_backoff_seconds=0.0,
        healthcheck_enabled=True,
        development_only=False,
        created_by=UUID("10000000-0000-0000-0000-000000000005"),
        created_at=datetime.now(UTC),
    )


class Profiles:
    def __init__(self, value: object) -> None:
        self.value = value

    async def find_profile(self, profile_id: UUID) -> object:
        assert profile_id == PROFILE_ID
        return self.value


class Deployments:
    def __init__(self, health: DeploymentHealthCheck | None) -> None:
        self.health = health
        self.health_version_ids: list[UUID] = []

    async def get_version(self, version_id: UUID) -> ModelDeploymentVersion:
        assert version_id == VERSION_ID
        return deployment()

    async def latest_health_check(
        self, version_id: UUID
    ) -> DeploymentHealthCheck | None:
        self.health_version_ids.append(version_id)
        return self.health


def readiness(profile: object, health: DeploymentHealthCheck | None):
    value = object.__new__(SqlAlchemyGenerationReadiness)
    value.settings = SimpleNamespace(
        environment="local",
        generation_base_url="http://legacy-global-must-not-be-used.invalid",
    )
    value.profiles = Profiles(profile)
    value.deployments = Deployments(health)
    return value


@pytest.mark.asyncio
async def test_readiness_uses_latest_health_for_exact_deployment_version() -> None:
    health = DeploymentHealthCheck(
        id=UUID("20000000-0000-0000-0000-000000000001"),
        deployment_version_id=VERSION_ID,
        status="ready",
        safe_error_code=None,
        observed_provider_model_id="runtime/exact-model",
        latency_ms=4,
        checked_by=UUID("20000000-0000-0000-0000-000000000002"),
        created_at=datetime.now(UTC),
    )
    deployments = Deployments(health)
    service = readiness(
        SimpleNamespace(bindings=(), deployment_version_id=VERSION_ID),
        health,
    )
    service.deployments = deployments

    assert await service.is_ready(PROFILE_ID) is True
    assert deployments.health_version_ids == [VERSION_ID]


@pytest.mark.asyncio
async def test_legacy_profile_stays_not_ready_without_deployment_lookup() -> None:
    service = readiness(
        SimpleNamespace(bindings=(object(),), deployment_version_id=None),
        None,
    )

    assert await service.is_ready(PROFILE_ID) is False
    assert service.deployments.health_version_ids == []
