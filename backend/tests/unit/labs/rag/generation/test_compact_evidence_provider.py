"""Reject unsupported v5 configurations before any provider or model I/O."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_workshop.labs.rag.deployments.domain import (
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from tests.unit.labs.rag.deployments.test_domain import codex_deployment
from tests.unit.labs.rag.generation.test_openai_compatible import local_deployment, profile
from tests.unit.labs.rag.generation.test_openai_responses import deployment as external_deployment
from tests.unit.labs.rag.generation.test_readiness import PROFILE_ID, readiness


def candidate(kind: str) -> ModelDeploymentVersion | None:
    if kind == "missing":
        return None
    if kind == "transformers":
        return replace(
            local_deployment(), provider=ProviderKind.LOCAL_TRANSFORMERS,
            endpoint_ref=None, local_model_ref="synthetic-model",
        )
    if kind == "external":
        return external_deployment()
    if kind == "codex":
        return codex_deployment()
    return local_deployment(
        location=ExecutionLocation.ON_PREMISE if kind == "on_premise" else ExecutionLocation.LOCAL
    )


@pytest.mark.parametrize("kind", ["missing", "transformers", "external", "codex", "on_premise"])
def test_v5_rejects_unsupported_provider_before_runtime_creation(kind: str) -> None:
    selected = candidate(kind)
    original = profile()
    fields = {
        "deployment": selected,
        "model_id": selected.model_definition_id if selected else original.model_id,
        "runtime_model": selected.provider_model_id if selected else original.runtime_model,
    }
    for version in range(1, 5):
        assert replace(original, prompt_ref=f"rag-answer-v{version}", **fields)
    with pytest.raises(ValueError, match="compact answer prompt requires a local HTTP deployment"):
        replace(original, prompt_ref="rag-answer-v5", **fields)


@pytest.mark.parametrize(
    "kind", ["local", "missing", "transformers", "external", "codex", "on_premise"]
)
def test_v5_readiness_does_not_call_unsupported_provider_health(kind: str) -> None:
    selected = candidate(kind)
    service = readiness(
        SimpleNamespace(
            bindings=(), deployment_version_id=PROFILE_ID,
            config={"prompt_ref": "rag-answer-v5", "generation": {"response_schema_version": 1}},
        ),
        None,
    )
    service.deployments.get_version = AsyncMock(return_value=selected)
    service.deployments.latest_health_check = AsyncMock(return_value=SimpleNamespace(
        status="ready", safe_error_code=None,
        observed_provider_model_id=selected.provider_model_id if selected else "unused",
    ))
    operation = service.is_ready(PROFILE_ID)
    try:
        operation.send(None)
    except StopIteration as completed:
        assert completed.value is (kind == "local")
    else:
        pytest.fail("Readiness unexpectedly suspended; only in-memory mocks are permitted.")
    finally:
        operation.close()
    assert service.deployments.latest_health_check.await_count == (1 if kind == "local" else 0)
