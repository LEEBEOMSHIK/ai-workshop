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
        if "prompt_ref" not in config:
            raise ProfileValidationError("A generation profile requires a prompt reference.")
        if roles != {ModelKind.LLM}:
            raise ProfileValidationError("A generation profile requires an LLM model.")
