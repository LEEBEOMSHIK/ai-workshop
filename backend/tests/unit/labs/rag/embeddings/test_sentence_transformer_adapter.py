import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingModelConfig,
    EmbeddingValidationError,
)
from ai_workshop.labs.rag.embeddings.sentence_transformers import (
    SentenceTransformerEmbedding,
)


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
    def __init__(self, *, dimension: int = 3, output: list[list[float]] | None = None) -> None:
        self.dimension = dimension
        self.output = output
        self.tokenizer = RecordingTokenizer()
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def get_sentence_embedding_dimension(self) -> int:
        return self.dimension

    def encode(self, texts: Sequence[str], **kwargs: object) -> list[list[float]]:
        self.calls.append((list(texts), kwargs))
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
