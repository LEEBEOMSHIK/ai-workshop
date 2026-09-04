from __future__ import annotations

import traceback
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import SecretStr

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.generation.contracts import GenerationRuntimePort
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.runtime_resolver import GenerationRuntimeResolver
from ai_workshop.labs.rag.policies.domain import (
    PolicyDecision,
    PolicyReasonCode,
)

DEPLOYMENT_VERSION_ID = UUID("10000000-0000-0000-0000-000000000001")


class Runtime:
    pass


class RecordingFactory:
    def __init__(self, runtime: GenerationRuntimePort) -> None:
        self.runtime = runtime
        self.calls: list[tuple[ModelDeploymentVersion, str, str | None]] = []

    def __call__(
        self,
        deployment: ModelDeploymentVersion,
        endpoint: str,
        secret: str | None,
    ) -> GenerationRuntimePort:
        self.calls.append((deployment, endpoint, secret))
        return self.runtime


def deployment(**overrides: object) -> ModelDeploymentVersion:
    values: dict[str, object] = {
        "id": DEPLOYMENT_VERSION_ID,
        "deployment_id": UUID("10000000-0000-0000-0000-000000000002"),
        "version": 1,
        "display_name": "Local exact runtime",
        "description": "Synthetic runtime fixture",
        "model_definition_id": UUID("10000000-0000-0000-0000-000000000003"),
        "provider": ProviderKind.LOCAL_OPENAI_COMPATIBLE,
        "location": ExecutionLocation.LOCAL,
        "allowed_environments": (DeploymentEnvironment.DEVELOPMENT,),
        "provider_model_id": "runtime/exact-model",
        "endpoint_ref": "local-runtime",
        "secret_ref": "local-auth",
        "capabilities": frozenset({DeploymentCapability.STRUCTURED_OUTPUT}),
        "external_transfer": False,
        "transmitted_data_categories": (),
        "data_processing_notice_ref": None,
        "timeout_seconds": 7.0,
        "max_retries": 2,
        "retry_backoff_seconds": 0.0,
        "healthcheck_enabled": True,
        "development_only": True,
        "created_by": UUID("10000000-0000-0000-0000-000000000004"),
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return ModelDeploymentVersion(**values)  # type: ignore[arg-type]


def allowed_policy() -> PolicyDecision:
    return PolicyDecision(
        True,
        None,
        UUID("20000000-0000-0000-0000-000000000001"),
        (),
    )


def resolver(factory: RecordingFactory, *, environment: str = "local") -> GenerationRuntimeResolver:
    return GenerationRuntimeResolver(
        environment=environment,
        endpoint_refs={"local-runtime": "http://127.42.0.1:11434"},
        secret_refs={"local-auth": SecretStr("synthetic-secret")},
        factories={ProviderKind.LOCAL_OPENAI_COMPATIBLE: factory},
    )


@pytest.mark.parametrize("environment", ["local", "test"])
def test_local_and_test_settings_environments_normalize_to_development(
    environment: str,
) -> None:
    runtime = Runtime()
    factory = RecordingFactory(runtime)  # type: ignore[arg-type]
    selected = deployment()

    resolved = resolver(factory, environment=environment).resolve(
        selected, allowed_policy()
    )

    assert resolved.adapter is runtime
    assert factory.calls == [
        (selected, "http://127.42.0.1:11434", "synthetic-secret")
    ]


def test_environment_and_development_only_gate_runs_before_factory() -> None:
    factory = RecordingFactory(Runtime())  # type: ignore[arg-type]

    with pytest.raises(GenerationProviderError) as caught:
        resolver(factory, environment="production").resolve(
            deployment(),
            allowed_policy(),
        )

    assert (caught.value.code, caught.value.retryable) == (
        "deployment_not_allowed_in_environment",
        False,
    )
    assert factory.calls == []


def test_policy_denial_runs_before_factory_or_reference_resolution() -> None:
    factory = RecordingFactory(Runtime())  # type: ignore[arg-type]
    denied = PolicyDecision(
        False,
        PolicyReasonCode.WORKSPACE_EXTERNAL_TRANSFER_DENIED,
        UUID("20000000-0000-0000-0000-000000000001"),
        (),
    )
    selected = replace(deployment(), endpoint_ref="missing-reference")

    with pytest.raises(GenerationProviderError) as caught:
        resolver(factory).resolve(selected, denied)

    assert caught.value.code == "workspace_external_transfer_denied"
    assert factory.calls == []


def test_exact_provider_factory_is_selected_once_without_fallback() -> None:
    selected = RecordingFactory(Runtime())  # type: ignore[arg-type]
    fallback = RecordingFactory(Runtime())  # type: ignore[arg-type]
    runtime_resolver = GenerationRuntimeResolver(
        environment="local",
        endpoint_refs={"local-runtime": "http://127.0.0.1:11434"},
        secret_refs={"local-auth": SecretStr("synthetic-secret")},
        factories={
            ProviderKind.LOCAL_OPENAI_COMPATIBLE: selected,
            ProviderKind.OPENAI_RESPONSES: fallback,
        },
    )

    result = runtime_resolver.resolve(deployment(), allowed_policy())

    assert result.adapter is selected.runtime
    assert len(selected.calls) == 1
    assert fallback.calls == []


@pytest.mark.parametrize(
    "selected",
    [
        deployment(
            provider=ProviderKind.OPENAI_RESPONSES,
            location=ExecutionLocation.EXTERNAL,
            external_transfer=True,
            transmitted_data_categories=("question",),
            data_processing_notice_ref="public-notice-v1",
            development_only=False,
        ),
        replace(deployment(), endpoint_ref="missing-reference"),
        replace(deployment(), secret_ref="missing-secret"),
    ],
)
def test_missing_factory_or_reference_fails_closed(
    selected: ModelDeploymentVersion,
) -> None:
    with pytest.raises(GenerationProviderError) as caught:
        resolver(RecordingFactory(Runtime())).resolve(  # type: ignore[arg-type]
            selected, allowed_policy()
        )

    assert (caught.value.code, caught.value.retryable) == (
        "deployment_not_ready",
        False,
    )


def test_missing_reference_discards_private_resolution_exception() -> None:
    private_reference = "CANARY-PRIVATE-REFERENCE"
    selected = replace(deployment(), endpoint_ref=private_reference)

    with pytest.raises(GenerationProviderError) as caught:
        resolver(RecordingFactory(Runtime())).resolve(  # type: ignore[arg-type]
            selected, allowed_policy()
        )

    assert caught.value.code == "deployment_not_ready"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert private_reference not in "".join(traceback.format_exception(caught.value))


def test_provider_error_contains_only_safe_code_and_retryability() -> None:
    error = GenerationProviderError("provider_timeout", retryable=True)

    assert str(error) == "provider_timeout"
    assert error.code == "provider_timeout"
    assert error.retryable is True
    assert error.__dict__ == {"code": "provider_timeout", "retryable": True}
