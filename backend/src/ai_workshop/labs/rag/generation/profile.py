from collections.abc import Mapping

from ai_workshop.labs.rag.deployments.domain import ModelDeploymentVersion
from ai_workshop.labs.rag.generation.domain import ContextPolicy, GenerationProfile
from ai_workshop.labs.rag.models.domain import ModelDefinition, ModelKind, Profile, ProfileKind


def resolve_generation_profile(
    profile: Profile,
    deployment: ModelDeploymentVersion | ModelDefinition,
    model: ModelDefinition | None = None,
) -> GenerationProfile:
    if profile.kind is not ProfileKind.GENERATION:
        raise ValueError("A generation profile is required.")
    if not isinstance(deployment, ModelDeploymentVersion) or model is None:
        raise ValueError("The generation profile requires an exact Deployment binding.")
    if (
        profile.bindings
        or profile.deployment_version_id != deployment.id
        or deployment.model_definition_id != model.id
        or model.kind is not ModelKind.LLM
    ):
        raise ValueError("The generation profile requires an exact Deployment binding.")

    context = _mapping(profile.config.get("context_policy"), "context policy")
    generation = _mapping(profile.config.get("generation"), "generation settings")
    return GenerationProfile(
        profile_id=profile.id,
        profile_name=profile.name,
        profile_version=profile.version,
        model_id=model.id,
        model_name=model.name,
        model_version=model.version,
        runtime_model=deployment.provider_model_id,
        prompt_ref=_text(profile.config.get("prompt_ref"), "prompt"),
        context_prompt_ref=_text(
            profile.config.get("context_prompt_ref"),
            "context prompt",
        ),
        context_policy=ContextPolicy(
            max_history_turns=_integer(
                context.get("max_history_turns"),
                "history turn limit",
            ),
            max_history_tokens=_integer(
                context.get("max_history_tokens"),
                "history token limit",
            ),
        ),
        timeout_seconds=_number(generation.get("timeout_seconds"), "timeout"),
        max_output_tokens=_integer(
            generation.get("max_output_tokens"),
            "output token limit",
        ),
        temperature=_number(generation.get("temperature"), "temperature"),
        response_schema_version=_integer(
            generation.get("response_schema_version"),
            "response schema version",
        ),
        deployment=deployment,
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"The generation {name} is invalid.")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"The generation {name} is invalid.")
    return value


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"The generation {name} is invalid.")
    return value


def _number(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"The generation {name} is invalid.")
    return float(value)
