"""Owner setup metadata, projected from settings without resolving any remote resource.

The versioned presets are explicit draft starting points, never runtime defaults. Their
bounded history/output/evidence policy is part of each preset version; changing it requires
a new preset ID and fresh evaluation. No model identity, endpoint, credential, private prompt
body, provider-specific reasoning or orchestration policy is included. OpenAI Responses and
native Anthropic support schema1; local HTTP supports the contextual schema2 answer prompt.
"""

from ai_workshop.config import Settings, _is_safe_provider_reference_name
from ai_workshop.labs.rag.deployments.domain import DeploymentEnvironment, ProviderKind
from ai_workshop.labs.rag.deployments.schemas import (
    DeploymentEndpointSetupOption,
    DeploymentSetupOptionsResponse,
    GenerationSetupPreset,
)
from ai_workshop.labs.rag.models.domain import JsonValue

# The public reference bound matches DeploymentVersionCreate's named-reference contract.
_REFERENCE_MAX_LENGTH = 120
_DEPLOYMENT_ENVIRONMENTS = {
    "local": DeploymentEnvironment.DEVELOPMENT,
    "test": DeploymentEnvironment.DEVELOPMENT,
    "production": DeploymentEnvironment.PRODUCTION,
}


def deployment_setup_options(settings: Settings) -> DeploymentSetupOptionsResponse:
    return DeploymentSetupOptionsResponse(
        endpoints=[
            DeploymentEndpointSetupOption(
                reference=reference,
                dialect=settings.provider_endpoint_dialects.get(reference, "openai"),
            )
            for reference, value in sorted(settings.provider_endpoint_refs.items())
            if _safe_reference(reference) and value.strip()
        ],
        secret_references=[
            reference
            for reference, value in sorted(settings.provider_secret_refs.items())
            if _safe_reference(reference) and value.get_secret_value().strip()
        ],
        environment=_DEPLOYMENT_ENVIRONMENTS[settings.environment],
        generation_presets=_generation_presets(),
    )


def _safe_reference(reference: str) -> bool:
    return len(reference) <= _REFERENCE_MAX_LENGTH and _is_safe_provider_reference_name(reference)


def _generation_presets() -> list[GenerationSetupPreset]:
    # Fresh dictionaries isolate the three explicit presets and every response. Common budgets
    # bound the starting candidate; existing versioned profiles are never read or modified.
    def common_config(*, prompt_ref: str, schema_version: int) -> dict[str, JsonValue]:
        return {
            "prompt_ref": prompt_ref,
            "context_prompt_ref": "rag-contextualize-v1",
            "citation_mode": "required",
            "context_policy": {"max_history_turns": 6, "max_history_tokens": 1024},
            "generation": {
                "timeout_seconds": 120,
                "max_output_tokens": 1024,
                "temperature": 0.0,
                "response_schema_version": schema_version,
            },
        }

    local_config = common_config(prompt_ref="rag-answer-v3", schema_version=2)
    local_config["context_evidence"] = {
        "version": 1, "max_groups": 8, "max_units": 32, "max_characters": 12000,
    }
    native_config = common_config(prompt_ref="rag-answer-v1", schema_version=1)
    native_config["generation"] = {
        "timeout_seconds": 120, "max_output_tokens": 1024, "temperature": 1.0,
        "response_schema_version": 1, "sampling_mode": "provider_default",
    }
    return [
        GenerationSetupPreset(
            id="grounded-anthropic-schema1-v1", name="Claude 근거 제한 답변",
            description=(
                "Anthropic 기본 샘플링과 필수 인용을 사용하는 답변 후보입니다. "
                "적용 전 평가가 필요합니다."
            ),
            supported_providers=[ProviderKind.ANTHROPIC_MESSAGES], config=native_config,
        ),
        GenerationSetupPreset(
            id="grounded-local-schema2-v1",
            name="로컬 근거 제한 답변",
            description=(
                "문서 문맥과 필수 인용을 사용하는 로컬 답변 후보입니다. 적용 전 평가가 필요합니다."
            ),
            supported_providers=[ProviderKind.LOCAL_OPENAI_COMPATIBLE],
            config=local_config,
        ),
        GenerationSetupPreset(
            id="grounded-openai-schema1-v1",
            name="OpenAI 근거 제한 답변",
            description=(
                "OpenAI Responses의 근거·필수 인용 답변 후보입니다. 적용 전 평가가 필요합니다."
            ),
            supported_providers=[ProviderKind.OPENAI_RESPONSES],
            config=common_config(prompt_ref="rag-answer-v1", schema_version=1),
        ),
    ]
