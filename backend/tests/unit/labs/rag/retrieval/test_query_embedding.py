from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn

import pytest

from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingModelConfig,
    EmbeddingRuntimeUnavailableError,
    EmbeddingValidationError,
)
from ai_workshop.labs.rag.embeddings.sentence_transformers import (
    SentenceTransformerEmbedding,
)
from ai_workshop.labs.rag.retrieval.domain import QueryEmbeddingUnavailableError
from ai_workshop.labs.rag.retrieval.query_embedding import RetrievalQueryEmbedding


def _config(*, dimension: int = 2) -> EmbeddingModelConfig:
    return EmbeddingModelConfig(
        repo_id="synthetic/local-model",
        revision="a" * 40,
        dimension=dimension,
        max_tokens=32,
        query_prefix="query: ",
        document_prefix="passage: ",
        normalize=True,
        device="cpu",
        dtype="float32",
        output_mode="dense",
        data_policy="local_only",
        batch_size=2,
    )


class _Model:
    def __init__(
        self,
        *,
        dimension: int = 2,
        failure: Exception | None = None,
        tokenizer: Callable[..., Mapping[str, object]] | None = None,
    ) -> None:
        self.dimension = dimension
        self.failure = failure
        self.tokenizer = tokenizer or (lambda *args, **kwargs: {"input_ids": [1, 2]})

    def get_sentence_embedding_dimension(self) -> int:
        return self.dimension

    def encode(self, texts: Sequence[str], **kwargs: object) -> list[list[float]]:
        del texts, kwargs
        if self.failure is not None:
            raise self.failure
        return [[1.0, 0.0]]


class _GenericRuntimeDefectEmbedding:
    dimension = 2

    def __init__(self, failure: RuntimeError) -> None:
        self.failure = failure

    def count_tokens(self, text: str) -> int:
        return len(text)

    def count_query_tokens(self, text: str) -> int:
        return len(text)

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        del texts
        return []

    def encode_query(self, text: str) -> NoReturn:
        del text
        raise self.failure


def _embedding(
    tmp_path: Path,
    loader: Callable[..., Any],
) -> SentenceTransformerEmbedding:
    return SentenceTransformerEmbedding(
        _config(),
        cache_folder=tmp_path,
        loader=loader,
    )


def test_query_wrapper_translates_production_model_loader_oserror(tmp_path: Path) -> None:
    failure = OSError("local model cache unavailable")

    def loader(repo_id: str, **kwargs: Any) -> NoReturn:
        del repo_id, kwargs
        raise failure

    query_embedding = RetrievalQueryEmbedding(_embedding(tmp_path, loader))

    with pytest.raises(QueryEmbeddingUnavailableError) as error:
        query_embedding.encode_query("synthetic query")

    operational = error.value.__cause__
    assert isinstance(operational, EmbeddingRuntimeUnavailableError)
    assert operational.__cause__ is failure


def test_query_wrapper_translates_production_model_runtime_error(tmp_path: Path) -> None:
    failure = RuntimeError("model runtime unavailable")
    model = _Model(failure=failure)
    query_embedding = RetrievalQueryEmbedding(
        _embedding(tmp_path, lambda *args, **kwargs: model)
    )

    with pytest.raises(QueryEmbeddingUnavailableError) as error:
        query_embedding.encode_query("synthetic query")

    operational = error.value.__cause__
    assert isinstance(operational, EmbeddingRuntimeUnavailableError)
    assert operational.__cause__ is failure


def test_query_wrapper_does_not_translate_untyped_generic_runtime_error() -> None:
    failure = RuntimeError("non-model programming defect")
    query_embedding = RetrievalQueryEmbedding(_GenericRuntimeDefectEmbedding(failure))

    with pytest.raises(RuntimeError) as error:
        query_embedding.encode_query("synthetic query")

    assert error.value is failure


@pytest.mark.parametrize(
    "failure",
    [AssertionError("assert defect"), TypeError("type defect"), ValueError("value defect")],
)
def test_query_wrapper_propagates_loader_programming_defect_unchanged(
    tmp_path: Path,
    failure: Exception,
) -> None:
    def loader(repo_id: str, **kwargs: Any) -> NoReturn:
        del repo_id, kwargs
        raise failure

    query_embedding = RetrievalQueryEmbedding(_embedding(tmp_path, loader))

    with pytest.raises(type(failure)) as error:
        query_embedding.encode_query("synthetic query")

    assert error.value is failure


def test_query_wrapper_propagates_production_dimension_contract_defect(
    tmp_path: Path,
) -> None:
    model = _Model(dimension=3)
    query_embedding = RetrievalQueryEmbedding(
        _embedding(tmp_path, lambda *args, **kwargs: model)
    )

    with pytest.raises(EmbeddingValidationError, match="dimension"):
        query_embedding.encode_query("synthetic query")


def test_query_wrapper_does_not_translate_tokenizer_contract_defect(
    tmp_path: Path,
) -> None:
    model = _Model(tokenizer=lambda *args, **kwargs: {"input_ids": "invalid"})
    query_embedding = RetrievalQueryEmbedding(
        _embedding(tmp_path, lambda *args, **kwargs: model)
    )

    with pytest.raises(EmbeddingValidationError, match="token IDs"):
        query_embedding.count_query_tokens("synthetic query")
