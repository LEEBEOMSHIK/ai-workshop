import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingModelConfig,
    EmbeddingRuntimeUnavailableError,
    EmbeddingValidationError,
)


class _SentenceTransformerModel(Protocol):
    tokenizer: Callable[..., Mapping[str, object]]

    def get_sentence_embedding_dimension(self) -> int | None: ...

    def encode(self, texts: Sequence[str], **kwargs: object) -> object: ...


type SentenceTransformerLoader = Callable[..., _SentenceTransformerModel]


class SentenceTransformerEmbedding:
    def __init__(
        self,
        config: EmbeddingModelConfig,
        *,
        cache_folder: Path,
        loader: SentenceTransformerLoader | None = None,
        local_files_only: bool = True,
    ) -> None:
        self.config = config
        self.dimension = config.dimension
        self.cache_folder = cache_folder
        self._loader = loader or _load_sentence_transformer
        self._local_files_only = local_files_only
        self._model: _SentenceTransformerModel | None = None

    def count_tokens(self, text: str) -> int:
        return self._count_tokens(self._document_input(text))

    def count_query_tokens(self, text: str) -> int:
        return self._count_tokens(self._query_input(text))

    def _count_tokens(self, model_input: str) -> int:
        try:
            return self._count_input(model_input)
        except EmbeddingRuntimeUnavailableError:
            raise
        except (OSError, RuntimeError) as exc:
            raise EmbeddingRuntimeUnavailableError(
                "The local embedding tokenizer runtime is unavailable."
            ) from exc

    def _count_input(self, model_input: str) -> int:
        encoded = self._load().tokenizer(
            model_input,
            add_special_tokens=True,
            truncation=False,
        )
        token_ids = encoded.get("input_ids")
        if not isinstance(token_ids, Sequence) or isinstance(token_ids, (str, bytes)):
            raise EmbeddingValidationError("The model tokenizer returned invalid token IDs.")
        return len(token_ids)

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        model_inputs = [self._document_input(text) for text in texts]
        try:
            return self._encode(model_inputs)
        except EmbeddingRuntimeUnavailableError:
            raise
        except (OSError, RuntimeError) as exc:
            raise EmbeddingRuntimeUnavailableError(
                "The local embedding model runtime is unavailable."
            ) from exc

    def encode_query(self, text: str) -> list[float]:
        try:
            vectors = self._encode([self._query_input(text)])
        except EmbeddingRuntimeUnavailableError:
            raise
        except (OSError, RuntimeError) as exc:
            raise EmbeddingRuntimeUnavailableError(
                "The local embedding model runtime is unavailable."
            ) from exc
        return vectors[0]

    def _document_input(self, text: str) -> str:
        return f"{self.config.document_prefix}{text}"

    def _query_input(self, text: str) -> str:
        return f"{self.config.query_prefix}{text}"

    def _load(self) -> _SentenceTransformerModel:
        if self._model is None:
            model = self._loader(
                self.config.repo_id,
                revision=self.config.revision,
                cache_folder=str(self.cache_folder),
                device=self.config.device,
                trust_remote_code=False,
                local_files_only=self._local_files_only,
                dtype=self.config.dtype,
            )
            actual_dimension = model.get_sentence_embedding_dimension()
            if actual_dimension != self.dimension:
                raise EmbeddingValidationError(
                    "The loaded model definition dimension does not match its pinned definition."
                )
            self._model = model
        return self._model

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        raw = self._load().encode(
            texts,
            batch_size=self.config.batch_size,
            normalize_embeddings=self.config.normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise EmbeddingValidationError("The model returned an invalid embedding output.")
        if len(raw) != len(texts):
            raise EmbeddingValidationError("The embedding output count does not match the input.")
        vectors: list[list[float]] = []
        for item in raw:
            if not isinstance(item, Sequence) or isinstance(item, (str, bytes)):
                raise EmbeddingValidationError("The model returned an invalid embedding vector.")
            try:
                vector = [
                    float(cast(float | int | str, value))
                    for value in cast(Sequence[object], item)
                ]
            except (TypeError, ValueError) as exc:
                raise EmbeddingValidationError(
                    "The model returned a non-numeric embedding value."
                ) from exc
            if len(vector) != self.dimension:
                raise EmbeddingValidationError(
                    "The embedding output dimension does not match the definition dimension."
                )
            if not all(math.isfinite(value) for value in vector):
                raise EmbeddingValidationError("Embedding vectors must contain only finite values.")
            norm = math.sqrt(sum(value * value for value in vector))
            if not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
                raise EmbeddingValidationError("Embedding vectors must be normalized.")
            vectors.append(vector)
        return vectors


def _load_sentence_transformer(repo_id: str, **kwargs: Any) -> _SentenceTransformerModel:
    from sentence_transformers import SentenceTransformer
    from torch import bfloat16, float16, float32

    dtype_name = kwargs.pop("dtype")
    dtypes = {"float32": float32, "float16": float16, "bfloat16": bfloat16}
    kwargs["model_kwargs"] = {"torch_dtype": dtypes[dtype_name]}
    return cast(_SentenceTransformerModel, SentenceTransformer(repo_id, **kwargs))
