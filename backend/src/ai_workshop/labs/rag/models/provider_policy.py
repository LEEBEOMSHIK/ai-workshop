"""Explicit generation sampling and native-provider compatibility policy (ADR-0053)."""

from collections.abc import Mapping
from typing import Literal

from ai_workshop.labs.rag.deployments.domain import ModelDeploymentVersion, ProviderKind

type SamplingMode = Literal["explicit", "provider_default"]


def resolve_sampling_mode(generation: Mapping[str, object]) -> SamplingMode:
    mode = generation.get("sampling_mode", "explicit")
    if mode not in ("explicit", "provider_default") or type(mode) is not str:
        raise ValueError("Unknown generation sampling mode.")
    return "provider_default" if mode == "provider_default" else "explicit"


def validate_provider_sampling(
    deployment: ModelDeploymentVersion | None,
    mode: SamplingMode,
    temperature: object,
    schema_version: object,
) -> None:
    native = deployment is not None and deployment.provider is ProviderKind.ANTHROPIC_MESSAGES
    if native:
        if (
            mode != "provider_default"
            or type(temperature) not in (int, float)
            or temperature != 1.0
            or type(schema_version) is not int
            or schema_version != 1
        ):
            raise ValueError("Anthropic requires schema1 and explicit provider-default sampling.")
    elif mode != "explicit":
        raise ValueError("Provider-default sampling is only supported by Anthropic Messages.")


def validate_provider_profile_config(
    config: Mapping[str, object],
    deployment: ModelDeploymentVersion,
) -> None:
    generation = config.get("generation")
    values = generation if isinstance(generation, Mapping) else {}
    validate_provider_sampling(
        deployment,
        resolve_sampling_mode(values),
        values.get("temperature"),
        values.get("response_schema_version"),
    )
    if deployment.provider is not ProviderKind.ANTHROPIC_MESSAGES:
        return
    if (
        set(config)
        != {"prompt_ref", "context_prompt_ref", "citation_mode", "context_policy", "generation"}
        or config.get("prompt_ref") != "rag-answer-v1"
        or config.get("context_prompt_ref") != "rag-contextualize-v1"
        or set(values)
        != {
            "timeout_seconds",
            "max_output_tokens",
            "temperature",
            "response_schema_version",
            "sampling_mode",
        }
    ):
        raise ValueError("Unsupported Anthropic generation profile settings.")
