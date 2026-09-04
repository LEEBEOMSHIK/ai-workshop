from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.configurations.schemas import ExternalTransferApprovalInput
from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.deployments.repository import (
    DeploymentCatalogEntry,
    DeploymentHealthCheck,
)
from ai_workshop.labs.rag.deployments.schemas import (
    DeploymentAdminResponse,
    DeploymentOptionResponse,
)
from ai_workshop.labs.rag.generation.domain import (
    ContextPolicy,
    GenerationProfile,
    generation_disclosure,
    generation_execution_snapshot,
)
from ai_workshop.main import create_app

VERSION_ID = UUID("10000000-0000-0000-0000-000000000001")
DEPLOYMENT_ID = UUID("10000000-0000-0000-0000-000000000002")
MODEL_ID = UUID("10000000-0000-0000-0000-000000000003")
ACTOR_ID = UUID("10000000-0000-0000-0000-000000000004")
HEALTH_ID = UUID("10000000-0000-0000-0000-000000000005")
CREATED_AT = datetime(2026, 9, 5, 1, 2, 3, tzinfo=UTC)


def deployment(*, location: ExecutionLocation) -> ModelDeploymentVersion:
    is_external = location is ExecutionLocation.EXTERNAL
    return ModelDeploymentVersion(
        id=VERSION_ID,
        deployment_id=DEPLOYMENT_ID,
        version=2,
        display_name="Synthetic exact deployment",
        description="Public synthetic fixture",
        model_definition_id=MODEL_ID,
        provider=(
            ProviderKind.OPENAI_RESPONSES
            if is_external
            else ProviderKind.LOCAL_OPENAI_COMPATIBLE
        ),
        location=location,
        allowed_environments=(DeploymentEnvironment.PRODUCTION,),
        provider_model_id="synthetic/exact-model",
        endpoint_ref="private-endpoint-reference",
        secret_ref="private-secret-reference" if is_external else None,
        capabilities=frozenset(
            {
                DeploymentCapability.STRUCTURED_OUTPUT,
                DeploymentCapability.TOKEN_ACCOUNTING,
            }
        ),
        external_transfer=is_external,
        transmitted_data_categories=("question", "evidence") if is_external else (),
        data_processing_notice_ref="private-notice-reference" if is_external else None,
        timeout_seconds=20.0,
        max_retries=1,
        retry_backoff_seconds=0.25,
        healthcheck_enabled=True,
        development_only=False,
        created_by=ACTOR_ID,
        created_at=CREATED_AT,
    )


def profile(exact_deployment: ModelDeploymentVersion) -> GenerationProfile:
    return GenerationProfile(
        profile_id=UUID("10000000-0000-0000-0000-000000000006"),
        profile_name="Synthetic generation profile",
        profile_version=1,
        model_id=MODEL_ID,
        model_name="Synthetic model",
        model_version=3,
        runtime_model=exact_deployment.provider_model_id,
        prompt_ref="grounded-answer-v1",
        context_prompt_ref="contextualize-v1",
        context_policy=ContextPolicy(max_history_turns=4, max_history_tokens=256),
        timeout_seconds=20.0,
        max_output_tokens=500,
        temperature=0.0,
        response_schema_version=1,
        deployment=exact_deployment,
    )


def health(*, status: str = "ready") -> DeploymentHealthCheck:
    return DeploymentHealthCheck(
        id=HEALTH_ID,
        deployment_version_id=VERSION_ID,
        status=status,
        safe_error_code=None if status == "ready" else "provider_unavailable",
        observed_provider_model_id=(
            "synthetic/exact-model" if status == "ready" else None
        ),
        latency_ms=17,
        checked_by=ACTOR_ID,
        created_at=CREATED_AT,
    )


def entry(
    exact_deployment: ModelDeploymentVersion,
    *,
    latest_health: DeploymentHealthCheck | None = None,
) -> DeploymentCatalogEntry:
    return DeploymentCatalogEntry(
        deployment=exact_deployment,
        model_name="Synthetic model",
        model_version=3,
        latest_health=latest_health,
    )


def test_external_option_uses_the_same_versioned_disclosure_as_execution() -> None:
    exact_deployment = deployment(location=ExecutionLocation.EXTERNAL)
    disclosure = generation_disclosure(exact_deployment)
    execution = generation_execution_snapshot(profile(exact_deployment))
    option = DeploymentOptionResponse.from_entry(entry(exact_deployment))

    assert option.deployment_version_id == VERSION_ID
    assert option.approval.model_dump() == {
        "required": True,
        "disclosure_version": "external-generation-v1",
        "disclosure": (
            "OpenAI 외부 API로 현재 질문, 제한된 이전 대화와 선별된 문서 근거가 "
            "전송됩니다."
        ),
        "transmitted_data_categories": ["question", "evidence"],
    }
    assert option.approval.disclosure_version == disclosure.version
    assert option.approval.disclosure == disclosure.text == execution.disclosure
    assert execution.disclosure_version == disclosure.version


@pytest.mark.parametrize(
    ("location", "disclosure_version", "disclosure"),
    [
        (
            ExecutionLocation.LOCAL,
            "local-generation-v1",
            "사내 로컬 모델에서 처리됩니다.",
        ),
        (
            ExecutionLocation.ON_PREMISE,
            "on-premise-generation-v1",
            "사내 온프레미스 모델에서 처리됩니다.",
        ),
    ],
)
def test_non_external_option_explicitly_states_that_approval_is_not_required(
    location: ExecutionLocation,
    disclosure_version: str,
    disclosure: str,
) -> None:
    exact_deployment = deployment(location=location)
    option = DeploymentOptionResponse.from_entry(entry(exact_deployment))

    assert option.approval.model_dump() == {
        "required": False,
        "disclosure_version": disclosure_version,
        "disclosure": disclosure,
        "transmitted_data_categories": [],
    }


def test_admin_summary_serializes_only_the_latest_safe_health_fields() -> None:
    response = DeploymentAdminResponse.from_entry(
        entry(deployment(location=ExecutionLocation.EXTERNAL), latest_health=health()),
        secret_configured=True,
    )

    assert response.latest_health is not None
    assert response.latest_health.model_dump() == {
        "status": "ready",
        "safe_error_code": None,
        "observed_provider_model_id": "synthetic/exact-model",
        "latency_ms": 17,
        "checked_at": CREATED_AT,
    }
    serialized = response.model_dump_json()
    for forbidden in (
        "endpoint_ref",
        "private-endpoint-reference",
        "secret_ref",
        "private-secret-reference",
        "data_processing_notice_ref",
        "private-notice-reference",
        "credential",
        "request_payload",
        "raw_error",
        "internal_trace",
    ):
        assert forbidden not in serialized


def test_admin_summary_has_no_latest_health_before_the_first_check() -> None:
    response = DeploymentAdminResponse.from_entry(
        entry(deployment(location=ExecutionLocation.LOCAL)),
        secret_configured=False,
    )

    assert response.latest_health is None


def test_option_is_ready_only_for_the_exact_latest_healthy_model() -> None:
    exact_deployment = deployment(location=ExecutionLocation.LOCAL)

    response = DeploymentOptionResponse.from_entry(
        entry(exact_deployment, latest_health=health())
    )

    assert response.readiness.model_dump() == {"ready": True, "reason_codes": []}


def test_option_uses_the_latest_safe_health_failure_as_its_disabled_reason() -> None:
    exact_deployment = deployment(location=ExecutionLocation.LOCAL)

    response = DeploymentOptionResponse.from_entry(
        entry(exact_deployment, latest_health=health(status="failed"))
    )

    assert response.readiness.model_dump() == {
        "ready": False,
        "reason_codes": ["provider_unavailable"],
    }


def test_openapi_exposes_the_task_9_safe_metadata_contract() -> None:
    schemas = create_app().openapi()["components"]["schemas"]

    option_properties = schemas["DeploymentOptionResponse"]["properties"]
    admin_properties = schemas["DeploymentAdminResponse"]["properties"]
    health_properties = schemas["DeploymentHealthResponse"]["properties"]

    assert {"deployment_version_id", "approval", "readiness"} <= set(
        option_properties
    )
    assert {"latest_health", "readiness"} <= set(admin_properties)
    assert "checked_at" in health_properties
    serialized = str(
        {
            "option": option_properties,
            "admin": admin_properties,
            "health": health_properties,
        }
    )
    for forbidden in (
        "endpoint_ref",
        "secret_ref",
        "credential",
        "request_payload",
        "raw_error",
        "internal_trace",
    ):
        assert forbidden not in serialized


def test_external_approval_output_and_input_share_the_exact_version_literal() -> None:
    schemas = create_app().openapi()["components"]["schemas"]
    input_version = schemas["ExternalTransferApprovalInput"]["properties"][
        "disclosure_version"
    ]
    output_version = schemas["DeploymentApprovalResponse"]["properties"][
        "disclosure_version"
    ]
    shared_version = schemas["ExternalGenerationDisclosureVersion"]

    assert input_version == output_version == {
        "$ref": "#/components/schemas/ExternalGenerationDisclosureVersion"
    }
    assert shared_version["const"] == "external-generation-v1"
    assert shared_version["type"] == "string"


def test_external_approval_input_rejects_an_unknown_disclosure_version() -> None:
    with pytest.raises(ValidationError):
        ExternalTransferApprovalInput.model_validate(
            {"confirmed": True, "disclosure_version": "unknown-generation-version"}
        )
