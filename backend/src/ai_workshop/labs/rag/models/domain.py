from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from re import fullmatch
from types import MappingProxyType
from uuid import UUID, uuid4

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type FrozenJsonValue = JsonScalar | tuple[FrozenJsonValue, ...] | Mapping[str, FrozenJsonValue]


class ModelKind(StrEnum):
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    LLM = "llm"


class ProfileKind(StrEnum):
    INDEXING = "indexing"
    RETRIEVAL = "retrieval"
    GENERATION = "generation"


class EvaluationState(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class ProfileValidationError(ValueError):
    pass


def freeze_json(value: JsonValue) -> FrozenJsonValue:
    if isinstance(value, dict):
        return MappingProxyType({key: freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze_json(item) for item in value)
    return value


def thaw_json(value: FrozenJsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def _validate_environment_references(config: Mapping[str, JsonValue]) -> None:
    sensitive_suffixes = ("key", "secret", "token", "password", "credential")
    for key, value in config.items():
        normalized = key.casefold()
        if normalized.endswith("_env"):
            if not isinstance(value, str) or fullmatch(r"[A-Z][A-Z0-9_]*", value) is None:
                raise ProfileValidationError(
                    f"{key} must contain an environment variable reference."
                )
        elif normalized in sensitive_suffixes or normalized.endswith(
            tuple(f"_{suffix}" for suffix in sensitive_suffixes)
        ):
            raise ProfileValidationError(
                f"{key} must use an environment variable reference instead of a literal secret."
            )
        if isinstance(value, dict):
            _validate_environment_references(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _validate_environment_references(item)


@dataclass(frozen=True, slots=True)
class ModelDefinition:
    id: UUID
    kind: ModelKind
    name: str
    version: int
    config: Mapping[str, FrozenJsonValue]

    @classmethod
    def create(
        cls,
        *,
        kind: ModelKind,
        name: str,
        version: int,
        config: dict[str, JsonValue],
    ) -> "ModelDefinition":
        if not name.strip() or version < 1:
            raise ProfileValidationError("Model name and positive version are required.")
        _validate_environment_references(config)
        if kind is ModelKind.LLM and (
            config.get("provider") != "openai_compatible"
            or config.get("data_policy") != "local_only"
            or not isinstance(config.get("runtime_model"), str)
            or not str(config["runtime_model"]).strip()
        ):
            raise ProfileValidationError(
                "An LLM model requires a local OpenAI-compatible runtime identity."
            )
        frozen = freeze_json(config)
        if not isinstance(frozen, Mapping):
            raise TypeError("Model configuration must be a mapping.")
        return cls(uuid4(), kind, name.strip(), version, frozen)


@dataclass(frozen=True, slots=True)
class ProfileModelBinding:
    role: ModelKind
    model_id: UUID


@dataclass(frozen=True, slots=True)
class Profile:
    id: UUID
    kind: ProfileKind
    name: str
    version: int
    config: Mapping[str, FrozenJsonValue]
    bindings: tuple[ProfileModelBinding, ...]
    evaluation_state: EvaluationState
    is_default: bool = False

    @classmethod
    def create(
        cls,
        *,
        kind: ProfileKind,
        name: str,
        version: int,
        config: dict[str, JsonValue],
        bindings: tuple[ProfileModelBinding, ...],
        evaluation_state: EvaluationState = EvaluationState.DRAFT,
        is_default: bool = False,
    ) -> "Profile":
        if not name.strip() or version < 1:
            raise ProfileValidationError("Profile name and positive version are required.")
        _validate_environment_references(config)
        _validate_profile_shape(kind, config, bindings)
        if is_default and evaluation_state is not EvaluationState.PASSED:
            raise ProfileValidationError("A default profile requires a passed evaluation.")
        frozen = freeze_json(config)
        if not isinstance(frozen, Mapping):
            raise TypeError("Profile configuration must be a mapping.")
        return cls(
            uuid4(),
            kind,
            name.strip(),
            version,
            frozen,
            tuple(bindings),
            evaluation_state,
            is_default,
        )

    def as_default(self) -> "Profile":
        if self.evaluation_state is not EvaluationState.PASSED:
            raise ProfileValidationError("A passed evaluation is required for default promotion.")
        return replace(self, is_default=True)


def _validate_profile_shape(
    kind: ProfileKind,
    config: Mapping[str, JsonValue],
    bindings: tuple[ProfileModelBinding, ...],
) -> None:
    roles = {binding.role for binding in bindings}
    if kind is ProfileKind.INDEXING:
        if "chunker" not in config:
            raise ProfileValidationError("An indexing profile requires a chunker configuration.")
        if roles != {ModelKind.EMBEDDING}:
            raise ProfileValidationError("An indexing profile requires an embedding model.")
    elif kind is ProfileKind.RETRIEVAL:
        if "bm25" not in config:
            raise ProfileValidationError("A retrieval profile requires BM25 configuration.")
        if ModelKind.LLM in roles:
            raise ProfileValidationError("An LLM cannot be bound directly to retrieval.")
        has_dense = "dense" in config
        if has_dense and ("rrf" not in config or "indexing_profile_id" not in config):
            raise ProfileValidationError(
                "Dense retrieval requires RRF and an indexing profile reference."
            )
        if ModelKind.RERANKER in roles and "reranker" not in config:
            raise ProfileValidationError("A reranker binding requires reranker configuration.")
    else:
        _validate_generation_profile(config, bindings)


def _validate_generation_profile(
    config: Mapping[str, JsonValue],
    bindings: tuple[ProfileModelBinding, ...],
) -> None:
    required = {
        "prompt_ref",
        "context_prompt_ref",
        "citation_mode",
        "context_policy",
        "generation",
    }
    if not required.issubset(config):
        raise ProfileValidationError(
            "A generation profile requires prompt, context, citation, and output settings."
        )
    if any(
        not isinstance(config[key], str) or not str(config[key]).strip()
        for key in ("prompt_ref", "context_prompt_ref")
    ):
        raise ProfileValidationError("A generation profile requires nonempty prompt references.")
    if config["citation_mode"] != "required":
        raise ProfileValidationError("A generation profile requires citation validation.")
    if len(bindings) != 1 or bindings[0].role is not ModelKind.LLM:
        raise ProfileValidationError("A generation profile requires exactly one LLM model.")

    context = config["context_policy"]
    generation = config["generation"]
    if not isinstance(context, Mapping) or not isinstance(generation, Mapping):
        raise ProfileValidationError("A generation profile requires structured settings.")
    max_turns = context.get("max_history_turns")
    max_context_tokens = context.get("max_history_tokens")
    if (
        not isinstance(max_turns, int)
        or isinstance(max_turns, bool)
        or max_turns < 1
        or not isinstance(max_context_tokens, int)
        or isinstance(max_context_tokens, bool)
        or max_context_tokens < 1
    ):
        raise ProfileValidationError("A generation profile requires positive context limits.")

    timeout = generation.get("timeout_seconds")
    max_output_tokens = generation.get("max_output_tokens")
    temperature = generation.get("temperature")
    schema_version = generation.get("response_schema_version")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ProfileValidationError("A generation profile requires a positive timeout.")
    if (
        not isinstance(max_output_tokens, int)
        or isinstance(max_output_tokens, bool)
        or max_output_tokens < 1
    ):
        raise ProfileValidationError("A generation profile requires a positive output token limit.")
    if (
        not isinstance(temperature, (int, float))
        or isinstance(temperature, bool)
        or not 0 <= temperature <= 2
    ):
        raise ProfileValidationError(
            "A generation profile temperature must be between zero and two."
        )
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version < 1
    ):
        raise ProfileValidationError("A generation profile requires a response schema version.")
