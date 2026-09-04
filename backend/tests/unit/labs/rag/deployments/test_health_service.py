from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
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
from ai_workshop.labs.rag.deployments.service import DeploymentHealthService
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    ProviderExecutionMetadata,
    ProviderHealthResult,
    ResolvedGenerationRuntime,
)
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.shared.errors import AppError

VERSION_ID = UUID("10000000-0000-0000-0000-000000000001")
ACTOR_ID = UUID("10000000-0000-0000-0000-000000000002")


def deployment(
    provider: ProviderKind = ProviderKind.LOCAL_OPENAI_COMPATIBLE,
) -> ModelDeploymentVersion:
    external = provider is ProviderKind.OPENAI_RESPONSES
    return ModelDeploymentVersion(
        id=VERSION_ID,
        deployment_id=UUID("10000000-0000-0000-0000-000000000003"),
        version=1,
        display_name="Synthetic deployment",
        description="Synthetic health fixture",
        model_definition_id=UUID("10000000-0000-0000-0000-000000000004"),
        provider=provider,
        location=(ExecutionLocation.EXTERNAL if external else ExecutionLocation.LOCAL),
        allowed_environments=(DeploymentEnvironment.DEVELOPMENT,),
        provider_model_id="runtime/exact-model",
        endpoint_ref="runtime-endpoint",
        secret_ref="runtime-secret" if external else None,
        capabilities=frozenset({DeploymentCapability.STRUCTURED_OUTPUT}),
        external_transfer=external,
        transmitted_data_categories=("question",) if external else (),
        data_processing_notice_ref="public-notice-v1" if external else None,
        timeout_seconds=5.0,
        max_retries=0,
        retry_backoff_seconds=0.0,
        healthcheck_enabled=True,
        development_only=False,
        created_by=ACTOR_ID,
        created_at=datetime.now(UTC),
    )


class MemoryRepository:
    def __init__(self, selected: ModelDeploymentVersion | None) -> None:
        self.selected = selected
        self.health_checks: list[DeploymentHealthCheck] = []

    async def get_version(self, version_id: UUID) -> ModelDeploymentVersion | None:
        if self.selected is None or self.selected.id != version_id:
            return None
        return self.selected

    async def add_health_check(
        self, health_check: DeploymentHealthCheck
    ) -> DeploymentHealthCheck:
        self.health_checks.append(health_check)
        return health_check


class PolicyResolver:
    def __init__(self) -> None:
        self.calls: list[ModelDeploymentVersion] = []

    async def resolve(
        self,
        *,
        deployment: ModelDeploymentVersion,
        workspace_ids: tuple[UUID, ...],
    ) -> PolicyDecision:
        assert workspace_ids == ()
        self.calls.append(deployment)
        return PolicyDecision(True, None, UUID(int=21), ())


class Runtime:
    def __init__(self, result: ProviderHealthResult | Exception) -> None:
        self.result = result
        self.calls = 0

    async def health(self) -> ProviderHealthResult:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class RuntimeResolver:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.calls: list[tuple[ModelDeploymentVersion, PolicyDecision]] = []

    def resolve(
        self,
        selected: ModelDeploymentVersion,
        policy: PolicyDecision,
    ) -> ResolvedGenerationRuntime:
        self.calls.append((selected, policy))
        return ResolvedGenerationRuntime(selected, self.runtime)  # type: ignore[arg-type]


def health_result(
    *,
    ready: bool = True,
    observed_provider_model_id: str | None = "runtime/exact-model",
    provider: ProviderKind = ProviderKind.LOCAL_OPENAI_COMPATIBLE,
) -> ProviderHealthResult:
    return ProviderHealthResult(
        ready=ready,
        observed_provider_model_id=observed_provider_model_id,
        execution=ProviderExecutionMetadata(
            provider=provider,
            provider_model_id="runtime/exact-model",
            deployment_version_id=VERSION_ID,
            input_tokens=None,
            output_tokens=None,
            latency_ms=9,
        ),
    )


@pytest.mark.asyncio
async def test_health_success_appends_one_exact_version_result() -> None:
    repository = MemoryRepository(deployment())
    policy = PolicyResolver()
    runtime = Runtime(health_result())
    runtime_resolver = RuntimeResolver(runtime)
    service = DeploymentHealthService(repository, policy, runtime_resolver)

    result = await service.check(VERSION_ID, actor_id=ACTOR_ID)

    assert result.status == "ready"
    assert result.safe_error_code is None
    assert result.provider_model_id == "runtime/exact-model"
    assert result.observed_provider_model_id == "runtime/exact-model"
    assert len(repository.health_checks) == 1
    assert repository.health_checks[0].deployment_version_id == VERSION_ID
    assert repository.health_checks[0].status == "ready"
    assert len(policy.calls) == len(runtime_resolver.calls) == runtime.calls == 1


@pytest.mark.parametrize(
    "observed_provider_model_id",
    [None, "runtime/wrong-model"],
)
@pytest.mark.asyncio
async def test_health_ready_requires_exact_observed_provider_model(
    observed_provider_model_id: str | None,
) -> None:
    repository = MemoryRepository(deployment())
    runtime = Runtime(
        health_result(observed_provider_model_id=observed_provider_model_id)
    )
    service = DeploymentHealthService(
        repository,
        PolicyResolver(),
        RuntimeResolver(runtime),
    )

    result = await service.check(VERSION_ID, actor_id=ACTOR_ID)

    assert result.status == "failed"
    assert result.safe_error_code == "provider_invalid_response"
    assert result.observed_provider_model_id is None
    assert len(repository.health_checks) == 1
    assert repository.health_checks[0].status == "failed"
    assert repository.health_checks[0].safe_error_code == "provider_invalid_response"


@pytest.mark.asyncio
async def test_health_safe_failure_appends_one_failed_result() -> None:
    repository = MemoryRepository(deployment())
    runtime = Runtime(GenerationProviderError("provider_timeout", retryable=True))
    service = DeploymentHealthService(
        repository,
        PolicyResolver(),
        RuntimeResolver(runtime),
    )

    result = await service.check(VERSION_ID, actor_id=ACTOR_ID)

    assert result.status == "failed"
    assert result.safe_error_code == "provider_timeout"
    assert result.observed_provider_model_id is None
    assert len(repository.health_checks) == 1
    assert repository.health_checks[0].safe_error_code == "provider_timeout"


@pytest.mark.asyncio
async def test_openai_health_uses_registered_runtime_and_records_exact_model() -> None:
    repository = MemoryRepository(deployment(ProviderKind.OPENAI_RESPONSES))
    policy = PolicyResolver()
    runtime = Runtime(health_result(provider=ProviderKind.OPENAI_RESPONSES))
    runtime_resolver = RuntimeResolver(runtime)
    service = DeploymentHealthService(repository, policy, runtime_resolver)

    result = await service.check(VERSION_ID, actor_id=ACTOR_ID)

    assert result.status == "ready"
    assert result.safe_error_code is None
    assert result.observed_provider_model_id == "runtime/exact-model"
    assert len(policy.calls) == len(runtime_resolver.calls) == runtime.calls == 1
    assert len(repository.health_checks) == 1


@pytest.mark.asyncio
async def test_unknown_version_returns_404_without_health_row() -> None:
    repository = MemoryRepository(None)
    service = DeploymentHealthService(
        repository,
        PolicyResolver(),
        RuntimeResolver(Runtime(health_result())),
    )

    with pytest.raises(AppError) as caught:
        await service.check(VERSION_ID, actor_id=ACTOR_ID)

    assert (caught.value.code, caught.value.status_code) == ("not_found", 404)
    assert repository.health_checks == []


@pytest.mark.asyncio
async def test_disabled_health_check_is_append_only_not_ready() -> None:
    repository = MemoryRepository(replace(deployment(), healthcheck_enabled=False))
    runtime = Runtime(AssertionError("disabled health must not run"))
    service = DeploymentHealthService(
        repository,
        PolicyResolver(),
        RuntimeResolver(runtime),
    )

    result = await service.check(VERSION_ID, actor_id=ACTOR_ID)

    assert result.safe_error_code == "deployment_not_ready"
    assert runtime.calls == 0
    assert len(repository.health_checks) == 1
