from dataclasses import FrozenInstanceError, replace
from typing import Any
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    DeploymentValidationError,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)


def deployment_values() -> dict[str, Any]:
    return {
        "deployment_id": uuid4(),
        "version": 1,
        "display_name": "OpenAI financial answers",
        "description": "Approved external generation",
        "model_definition_id": uuid4(),
        "provider": ProviderKind.OPENAI_RESPONSES,
        "location": ExecutionLocation.EXTERNAL,
        "allowed_environments": (DeploymentEnvironment.PRODUCTION,),
        "provider_model_id": "approved-model-version",
        "endpoint_ref": "openai-responses",
        "secret_ref": "openai-primary",
        "capabilities": frozenset({DeploymentCapability.STRUCTURED_OUTPUT}),
        "external_transfer": True,
        "transmitted_data_categories": ("question", "bounded_history", "evidence"),
        "data_processing_notice_ref": "openai-processing-notice-v1",
        "timeout_seconds": 30.0,
        "max_retries": 1,
        "retry_backoff_seconds": 0.5,
        "healthcheck_enabled": True,
        "development_only": False,
        "created_by": uuid4(),
    }


def create_deployment(**overrides: object) -> ModelDeploymentVersion:
    values = deployment_values()
    values.update(overrides)
    return ModelDeploymentVersion.create(**values)


def test_create_returns_an_immutable_version_with_a_uuid_identity() -> None:
    deployment = create_deployment(display_name="  OpenAI financial answers  ")

    assert isinstance(deployment.id, UUID)
    assert deployment.display_name == "OpenAI financial answers"
    assert deployment.capabilities == frozenset({DeploymentCapability.STRUCTURED_OUTPUT})
    with pytest.raises(FrozenInstanceError):
        deployment.display_name = "changed"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"display_name": "  "}, "name"),
        ({"version": 0}, "version"),
        ({"timeout_seconds": 0.0}, "timeout"),
        ({"capabilities": frozenset()}, "capability"),
    ],
)
def test_create_rejects_missing_required_deployment_contract(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(DeploymentValidationError, match=message):
        create_deployment(**overrides)


def test_create_rejects_unnamed_capabilities() -> None:
    with pytest.raises(DeploymentValidationError, match="capability"):
        create_deployment(capabilities=frozenset({"structured_output"}))


def test_create_rejects_an_unnamed_provider_kind() -> None:
    with pytest.raises(DeploymentValidationError, match="Provider"):
        create_deployment(provider="openai_responses")


@pytest.mark.parametrize(
    "overrides",
    [
        {"external_transfer": False},
        {"location": ExecutionLocation.LOCAL},
    ],
)
def test_external_deployment_requires_matching_external_transfer_location(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(DeploymentValidationError, match="external"):
        create_deployment(**overrides)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"endpoint_ref": None}, "endpoint"),
        ({"secret_ref": None}, "secret"),
        ({"transmitted_data_categories": ()}, "categories"),
        ({"data_processing_notice_ref": None}, "notice"),
    ],
)
def test_external_deployment_requires_external_transfer_contract(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(DeploymentValidationError, match=message):
        create_deployment(**overrides)


@pytest.mark.parametrize(
    "location", [ExecutionLocation.LOCAL, ExecutionLocation.ON_PREMISE]
)
def test_local_provider_accepts_only_non_external_execution_locations(
    location: ExecutionLocation,
) -> None:
    deployment = create_deployment(
        provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
        location=location,
        secret_ref=None,
        external_transfer=False,
        transmitted_data_categories=(),
        data_processing_notice_ref=None,
    )

    assert deployment.location is location
    assert deployment.external_transfer is False


def test_local_provider_rejects_external_execution() -> None:
    with pytest.raises(DeploymentValidationError, match="local Provider"):
        create_deployment(provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE)


def test_caller_owned_collections_cannot_mutate_a_created_version() -> None:
    environments = [DeploymentEnvironment.DEVELOPMENT]
    categories: list[str] = []
    deployment = create_deployment(
        provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
        location=ExecutionLocation.LOCAL,
        allowed_environments=environments,
        secret_ref=None,
        external_transfer=False,
        transmitted_data_categories=categories,
        data_processing_notice_ref=None,
    )

    environments.append(DeploymentEnvironment.PRODUCTION)
    categories.append("question")

    assert deployment.allowed_environments == (DeploymentEnvironment.DEVELOPMENT,)
    assert deployment.transmitted_data_categories == ()


def test_frozen_version_cannot_be_replaced_with_an_invalid_value() -> None:
    deployment = create_deployment()

    with pytest.raises(DeploymentValidationError, match="timeout"):
        replace(deployment, timeout_seconds=0)
