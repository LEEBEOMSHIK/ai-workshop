from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.generation.profile import resolve_generation_profile
from ai_workshop.labs.rag.models.domain import (
    ModelDefinition,
    ModelKind,
    Profile,
    ProfileKind,
    ProfileModelBinding,
)

MODEL_ID = UUID("10000000-0000-0000-0000-000000000001")


def llm_model() -> ModelDefinition:
    return replace(
        ModelDefinition.create(
            kind=ModelKind.LLM,
            name="local-llm",
            version=3,
            config={
                "provider": "openai_compatible",
                "runtime_model": "runtime/exact-model",
                "data_policy": "local_only",
            },
        ),
        id=MODEL_ID,
    )


def generation_profile(*, model_id: UUID = MODEL_ID) -> Profile:
    return Profile.create(
        kind=ProfileKind.GENERATION,
        name="grounded-generation",
        version=2,
        config={
            "prompt_ref": "rag-answer-v1",
            "context_prompt_ref": "rag-contextualize-v1",
            "citation_mode": "required",
            "context_policy": {"max_history_turns": 6, "max_history_tokens": 1024},
            "generation": {
                "timeout_seconds": 30,
                "max_output_tokens": 512,
                "temperature": 0.1,
                "response_schema_version": 1,
            },
        },
        bindings=(),
        deployment_version_id=model_id,
    )


def deployment(*, model_id: UUID = MODEL_ID) -> ModelDeploymentVersion:
    return ModelDeploymentVersion.create(
        deployment_id=uuid4(),
        version=4,
        display_name="OpenAI grounded answers",
        description="Synthetic deployment",
        model_definition_id=model_id,
        provider=ProviderKind.OPENAI_RESPONSES,
        location=ExecutionLocation.EXTERNAL,
        allowed_environments=(DeploymentEnvironment.PRODUCTION,),
        provider_model_id="approved-model-version",
        endpoint_ref="openai-responses",
        secret_ref="openai-primary",
        capabilities=(DeploymentCapability.STRUCTURED_OUTPUT,),
        external_transfer=True,
        transmitted_data_categories=("question", "evidence"),
        data_processing_notice_ref="public-notice-v1",
        timeout_seconds=30,
        max_retries=1,
        retry_backoff_seconds=0.5,
        healthcheck_enabled=True,
        development_only=False,
        created_by=uuid4(),
    )


def test_resolver_keeps_exact_profile_model_and_policy_versions() -> None:
    exact_deployment = deployment()
    profile = replace(
        generation_profile(model_id=exact_deployment.id),
        deployment_version_id=exact_deployment.id,
    )
    resolved = resolve_generation_profile(profile, exact_deployment, llm_model())

    assert resolved.profile_version == 2
    assert resolved.deployment == exact_deployment
    assert resolved.model_version == 3
    assert resolved.deployment.provider_model_id == "approved-model-version"
    assert resolved.context_policy.max_history_turns == 6
    assert resolved.max_output_tokens == 512


def test_resolver_rejects_deployment_outside_exact_profile_binding() -> None:
    exact_deployment = deployment()
    with pytest.raises(ValueError, match="binding"):
        resolve_generation_profile(
            generation_profile(
                model_id=UUID("10000000-0000-0000-0000-000000000099")
            ),
            exact_deployment,
            llm_model(),
        )


def test_legacy_generation_profile_is_not_resolved_for_execution() -> None:
    legacy = replace(
        generation_profile(),
        bindings=(ProfileModelBinding(ModelKind.LLM, MODEL_ID),),
        deployment_version_id=None,
    )

    with pytest.raises(ValueError, match="Deployment"):
        resolve_generation_profile(legacy, deployment(), llm_model())
