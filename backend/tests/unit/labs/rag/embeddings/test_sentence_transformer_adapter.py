import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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


def config(*, dimension: int = 3) -> EmbeddingModelConfig:
    return EmbeddingModelConfig(
        repo_id="intfloat/multilingual-e5-base",
        revision="d128750597153bb5987e10b1c3493a34e5a4502a",
        dimension=dimension,
        max_tokens=512,
        query_prefix="query: ",
        document_prefix="passage: ",
        normalize=True,
        device="cpu",
        dtype="float32",
        output_mode="dense",
        data_policy="local_only",
        batch_size=7,
    )


class RecordingTokenizer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(
        self, text: str, *, add_special_tokens: bool, truncation: bool
    ) -> dict[str, list[int]]:
        assert add_special_tokens is True
        assert truncation is False
        self.calls.append(text)
        return {"input_ids": list(range(len(text.split()) + 2))}


class RecordingModel:
    def __init__(
        self,
        *,
        dimension: int = 3,
        output: list[list[float]] | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.dimension = dimension
        self.output = output
        self.failure = failure
        self.tokenizer = RecordingTokenizer()
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def get_sentence_embedding_dimension(self) -> int:
        return self.dimension

    def encode(self, texts: Sequence[str], **kwargs: object) -> list[list[float]]:
        self.calls.append((list(texts), kwargs))
        if self.failure is not None:
            raise self.failure
        if self.output is not None:
            return self.output
        return [[1.0, 0.0, 0.0] for _ in texts]


class RecordingLoader:
    def __init__(self, model: RecordingModel) -> None:
        self.model = model
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, repo_id: str, **kwargs: Any) -> RecordingModel:
        self.calls.append((repo_id, kwargs))
        return self.model


def test_adapter_is_lazy_and_loads_exact_pinned_local_runtime_options(tmp_path: Path) -> None:
    loader = RecordingLoader(RecordingModel())
    embedding = SentenceTransformerEmbedding(
        config(), cache_folder=tmp_path, loader=loader, local_files_only=True
    )

    assert loader.calls == []

    vectors = embedding.encode_documents(["첫 문서", "둘째 문서"])

    assert vectors == [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    assert loader.calls == [
        (
            "intfloat/multilingual-e5-base",
            {
                "revision": "d128750597153bb5987e10b1c3493a34e5a4502a",
                "cache_folder": str(tmp_path),
                "device": "cpu",
                "trust_remote_code": False,
                "local_files_only": True,
                "dtype": "float32",
            },
        )
    ]
    texts, options = loader.model.calls[0]
    assert texts == ["passage: 첫 문서", "passage: 둘째 문서"]
    assert options == {
        "batch_size": 7,
        "normalize_embeddings": True,
        "convert_to_numpy": True,
        "show_progress_bar": False,
    }


def test_adapter_counts_document_and_query_tokens_with_the_exact_model_prefix(
    tmp_path: Path,
) -> None:
    loader = RecordingLoader(RecordingModel())
    embedding = SentenceTransformerEmbedding(config(), cache_folder=tmp_path, loader=loader)

    assert embedding.count_tokens("one two") == 5
    assert embedding.count_query_tokens("one two") == 5
    assert loader.model.tokenizer.calls == ["passage: one two", "query: one two"]


def test_adapter_uses_query_prefix_without_double_prefixing(tmp_path: Path) -> None:
    loader = RecordingLoader(RecordingModel())
    embedding = SentenceTransformerEmbedding(config(), cache_folder=tmp_path, loader=loader)

    assert embedding.encode_query("같은 입력") == [1.0, 0.0, 0.0]
    assert loader.model.calls[0][0] == ["query: 같은 입력"]


@pytest.mark.parametrize(
    "failure",
    [OSError("document cache unavailable"), RuntimeError("document runtime failed")],
)
def test_document_embedding_translates_model_operational_failure(
    tmp_path: Path,
    failure: Exception,
) -> None:
    embedding = SentenceTransformerEmbedding(
        config(),
        cache_folder=tmp_path,
        loader=RecordingLoader(RecordingModel(failure=failure)),
    )

    with pytest.raises(EmbeddingRuntimeUnavailableError) as caught:
        embedding.encode_documents(["synthetic document"])

    assert caught.value.__cause__ is failure


def test_document_embedding_translates_loader_operational_failure(
    tmp_path: Path,
) -> None:
    failure = OSError("document model missing")

    def loader(repo_id: str, **kwargs: Any) -> RecordingModel:
        del repo_id, kwargs
        raise failure

    embedding = SentenceTransformerEmbedding(
        config(), cache_folder=tmp_path, loader=loader
    )

    with pytest.raises(EmbeddingRuntimeUnavailableError) as caught:
        embedding.encode_documents(["synthetic document"])

    assert caught.value.__cause__ is failure


@pytest.mark.parametrize(
    "failure",
    [AssertionError("assert defect"), TypeError("type defect"), ValueError("value defect")],
)
def test_document_embedding_propagates_model_programming_defect(
    tmp_path: Path,
    failure: Exception,
) -> None:
    embedding = SentenceTransformerEmbedding(
        config(),
        cache_folder=tmp_path,
        loader=RecordingLoader(RecordingModel(failure=failure)),
    )

    with pytest.raises(type(failure)) as caught:
        embedding.encode_documents(["synthetic document"])

    assert caught.value is failure


@pytest.mark.parametrize(
    ("model", "message"),
    [
        (RecordingModel(dimension=2), "definition dimension"),
        (RecordingModel(output=[[1.0, 0.0]]), "output dimension"),
        (RecordingModel(output=[[math.nan, 0.0, 0.0]]), "finite"),
        (RecordingModel(output=[[1.0, 1.0, 0.0]]), "normalized"),
    ],
)
def test_adapter_rejects_model_or_output_that_disagrees_with_definition(
    tmp_path: Path, model: RecordingModel, message: str
) -> None:
    embedding = SentenceTransformerEmbedding(
        config(), cache_folder=tmp_path, loader=RecordingLoader(model)
    )

    with pytest.raises(EmbeddingValidationError, match=message):
        embedding.encode_documents(["synthetic text"])


def test_adapter_rejects_output_count_mismatch(tmp_path: Path) -> None:
    embedding = SentenceTransformerEmbedding(
        config(),
        cache_folder=tmp_path,
        loader=RecordingLoader(RecordingModel(output=[[1.0, 0.0, 0.0]])),
    )

    with pytest.raises(EmbeddingValidationError, match="output count"):
        embedding.encode_documents(["one", "two"])


@pytest.mark.parametrize(
    "operation", ["count_tokens", "count_query_tokens", "encode_query", "encode_documents"]
)
def test_close_drops_owned_model_and_never_reloads_it(tmp_path, operation):
    import weakref

    models = []

    def load(*args, **kwargs):
        model = RecordingModel()
        models.append(weakref.ref(model))
        return model

    embedding = SentenceTransformerEmbedding(config(), cache_folder=tmp_path, loader=load)
    assert embedding.encode_query("synthetic") == [1.0, 0.0, 0.0]
    assert models[0]() is not None
    embedding.close()
    embedding.close()
    assert models[0]() is None
    argument = ["synthetic"] if operation == "encode_documents" else "synthetic"
    with pytest.raises(EmbeddingRuntimeUnavailableError, match="closed"):
        getattr(embedding, operation)(argument)
    assert len(models) == 1


def test_close_unused_adapter_does_not_load_model(tmp_path):
    loader = RecordingLoader(RecordingModel())
    embedding = SentenceTransformerEmbedding(config(), cache_folder=tmp_path, loader=loader)
    embedding.close()
    with pytest.raises(EmbeddingRuntimeUnavailableError, match="closed"):
        embedding.count_tokens("synthetic")
    assert loader.calls == []


@pytest.mark.parametrize(
    "operation", ["count_tokens", "count_query_tokens", "encode_query", "encode_documents"]
)
@pytest.mark.parametrize("failure_type", [ImportError, ModuleNotFoundError])
def test_dependency_import_failure_uses_safe_runtime_error(
    tmp_path: Path, operation: str, failure_type: type[ImportError]
) -> None:
    failure = failure_type("synthetic private path and dependency detail")
    calls = 0

    def loader(repo_id: str, **kwargs: Any) -> RecordingModel:
        nonlocal calls
        calls += 1
        raise failure

    embedding = SentenceTransformerEmbedding(config(), cache_folder=tmp_path, loader=loader)
    argument = ["synthetic"] if operation == "encode_documents" else "synthetic"

    with pytest.raises(EmbeddingRuntimeUnavailableError) as caught:
        getattr(embedding, operation)(argument)

    assert caught.value.__cause__ is failure
    assert str(failure) not in str(caught.value)
    assert calls == 1


@pytest.mark.parametrize("operation", ["encode_query", "encode_documents"])
def test_lazy_encode_import_failure_uses_safe_runtime_error(
    tmp_path: Path, operation: str
) -> None:
    failure = ImportError("synthetic native extension unavailable")
    model = RecordingModel(failure=failure)
    embedding = SentenceTransformerEmbedding(
        config(), cache_folder=tmp_path, loader=RecordingLoader(model)
    )
    argument = ["synthetic"] if operation == "encode_documents" else "synthetic"

    with pytest.raises(EmbeddingRuntimeUnavailableError) as caught:
        getattr(embedding, operation)(argument)

    assert caught.value.__cause__ is failure
    assert str(failure) not in str(caught.value)
    assert len(model.calls) == 1


@pytest.mark.parametrize("operation", ["count_tokens", "count_query_tokens"])
def test_lazy_tokenizer_import_failure_uses_safe_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    failure = ImportError("synthetic tokenizer dependency unavailable")

    def tokenizer(*args: object, **kwargs: object) -> dict[str, list[int]]:
        raise failure

    model = RecordingModel()
    monkeypatch.setattr(model, "tokenizer", tokenizer)
    embedding = SentenceTransformerEmbedding(
        config(), cache_folder=tmp_path, loader=RecordingLoader(model)
    )

    with pytest.raises(EmbeddingRuntimeUnavailableError) as caught:
        getattr(embedding, operation)("synthetic")

    assert caught.value.__cause__ is failure
    assert str(failure) not in str(caught.value)


@pytest.mark.parametrize("operation", ["encode_query", "count_query_tokens"])
def test_dependency_failure_reaches_query_unavailable_contract(
    tmp_path: Path, operation: str
) -> None:
    failure = ImportError("synthetic dependency detail")

    def loader(repo_id: str, **kwargs: Any) -> RecordingModel:
        raise failure

    query = RetrievalQueryEmbedding(
        SentenceTransformerEmbedding(config(), cache_folder=tmp_path, loader=loader)
    )

    with pytest.raises(QueryEmbeddingUnavailableError) as caught:
        getattr(query, operation)("synthetic")

    operational = caught.value.__cause__
    assert isinstance(operational, EmbeddingRuntimeUnavailableError)
    assert operational.__cause__ is failure
    assert str(failure) not in str(caught.value)
