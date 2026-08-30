import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from ai_workshop.labs.rag.models.domain import ModelDefinition, ModelKind


class EmbeddingValidationError(ValueError):
    pass


class EmbeddingRuntimeUnavailableError(RuntimeError):
    pass


class EmbeddingPort(Protocol):
    dimension: int

    def count_tokens(self, text: str) -> int:
        raise NotImplementedError

    def count_query_tokens(self, text: str) -> int:
        raise NotImplementedError

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    def encode_query(self, text: str) -> list[float]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class EmbeddingDescriptor:
    projection_id: UUID
    indexing_profile_id: UUID
    model_definition_id: UUID
    model_revision: str
    model_config_sha256: str
    profile_config_sha256: str
    dimension: int
    max_tokens: int
    normalize: bool
    output_mode: str

    def __post_init__(self) -> None:
        if len(self.model_revision) != 40 or any(
            character not in "0123456789abcdef" for character in self.model_revision
        ):
            raise EmbeddingValidationError("The embedding descriptor requires a pinned revision.")
        if len(self.model_config_sha256) != 64 or len(self.profile_config_sha256) != 64:
            raise EmbeddingValidationError("Embedding descriptor hashes must be SHA-256 digests.")
        if self.dimension < 1 or self.max_tokens < 1:
            raise EmbeddingValidationError(
                "Embedding descriptor dimension and max_tokens must be positive."
            )
        if not self.normalize:
            raise EmbeddingValidationError("Embedding descriptor output must be normalized.")
        if self.output_mode != "dense":
            raise EmbeddingValidationError("Embedding descriptor supports dense output only.")


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    chunk_id: UUID
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    descriptor: EmbeddingDescriptor
    vectors: tuple[EmbeddingVector, ...]

    def __post_init__(self) -> None:
        chunk_ids = [vector.chunk_id for vector in self.vectors]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise EmbeddingValidationError("Embedding vector chunk IDs must be unique.")
        for vector in self.vectors:
            if len(vector.values) != self.descriptor.dimension:
                raise EmbeddingValidationError(
                    "Embedding vector dimension does not match its immutable descriptor."
                )
            if not all(math.isfinite(value) for value in vector.values):
                raise EmbeddingValidationError("Embedding vectors must contain only finite values.")
            norm = math.sqrt(sum(value * value for value in vector.values))
            if not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
                raise EmbeddingValidationError("Embedding vectors must be normalized.")


@dataclass(frozen=True, slots=True)
class EmbeddingModelConfig:
    repo_id: str
    revision: str
    dimension: int
    max_tokens: int
    query_prefix: str
    document_prefix: str
    normalize: bool
    device: str
    dtype: str
    output_mode: str
    data_policy: str
    batch_size: int
    sparse_enabled: bool = False
    colbert_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.repo_id.strip():
            raise EmbeddingValidationError("repo_id must be a non-empty model repository.")
        if len(self.revision) != 40 or any(
            character not in "0123456789abcdef" for character in self.revision
        ):
            raise EmbeddingValidationError("revision must be a full 40-character commit hash.")
        if self.dimension < 1:
            raise EmbeddingValidationError("dimension must be positive.")
        if self.max_tokens < 1:
            raise EmbeddingValidationError("max_tokens must be positive.")
        if not self.normalize:
            raise EmbeddingValidationError("Embedding output must be normalized.")
        if not self.device.strip():
            raise EmbeddingValidationError("device must be explicit.")
        if self.dtype not in {"float32", "float16", "bfloat16"}:
            raise EmbeddingValidationError("dtype must be an explicitly supported floating type.")
        if self.output_mode != "dense":
            raise EmbeddingValidationError("Only dense output_mode is supported.")
        if self.sparse_enabled:
            raise EmbeddingValidationError("sparse_enabled must remain false in V1.")
        if self.colbert_enabled:
            raise EmbeddingValidationError("colbert_enabled must remain false in V1.")
        if self.data_policy != "local_only":
            raise EmbeddingValidationError("Embedding data_policy must be local_only.")
        if self.batch_size < 1:
            raise EmbeddingValidationError(
                "batch_size must be a positive integer from the profile."
            )

    @classmethod
    def from_definition(
        cls,
        definition: ModelDefinition,
        *,
        profile_config: Mapping[str, object],
    ) -> "EmbeddingModelConfig":
        if definition.kind is not ModelKind.EMBEDDING:
            raise EmbeddingValidationError("An embedding definition must have embedding kind.")
        values = definition.config
        required = (
            "repo_id",
            "revision",
            "dimension",
            "max_tokens",
            "query_prefix",
            "document_prefix",
            "normalize",
            "device",
            "dtype",
            "output_mode",
            "data_policy",
        )
        for field in required:
            if field not in values:
                raise EmbeddingValidationError(f"{field} is required.")
        batch_size = profile_config.get("batch_size")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int):
            raise EmbeddingValidationError(
                "batch_size must be a positive integer from the profile."
            )
        return cls(
            repo_id=_string(values["repo_id"], "repo_id"),
            revision=_string(values["revision"], "revision"),
            dimension=_integer(values["dimension"], "dimension"),
            max_tokens=_integer(values["max_tokens"], "max_tokens"),
            query_prefix=_string(values["query_prefix"], "query_prefix", allow_empty=True),
            document_prefix=_string(
                values["document_prefix"], "document_prefix", allow_empty=True
            ),
            normalize=_boolean(values["normalize"], "normalize"),
            device=_string(values["device"], "device"),
            dtype=_string(values["dtype"], "dtype"),
            output_mode=_string(values["output_mode"], "output_mode"),
            data_policy=_string(values["data_policy"], "data_policy"),
            batch_size=batch_size,
            sparse_enabled=_optional_boolean(values.get("sparse_enabled"), "sparse_enabled"),
            colbert_enabled=_optional_boolean(values.get("colbert_enabled"), "colbert_enabled"),
        )


def _string(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise EmbeddingValidationError(f"{name} must be a string.")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EmbeddingValidationError(f"{name} must be an integer.")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise EmbeddingValidationError(f"{name} must be a boolean.")
    return value


def _optional_boolean(value: object | None, name: str) -> bool:
    if value is None:
        return False
    return _boolean(value, name)
