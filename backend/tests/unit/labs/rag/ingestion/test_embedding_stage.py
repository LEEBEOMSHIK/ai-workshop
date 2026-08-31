from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.chunking.contracts import ChunkingConfig, ChunkingResult
from ai_workshop.labs.rag.documents.domain import (
    ParsedDocument,
    RetrievalChunk,
    SourceLocation,
    StructuralElement,
)
from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingDescriptor,
    EmbeddingModelConfig,
    EmbeddingValidationError,
)
from ai_workshop.labs.rag.embeddings.sentence_transformers import (
    SentenceTransformerEmbedding,
)
from ai_workshop.labs.rag.ingestion.domain import RagIngestionError
from ai_workshop.labs.rag.ingestion.stages import (
    EmbeddingRuntimeProvider,
    chunk_with_model_tokenizer,
    embed_chunks,
    validate_indexing_inputs,
)

PROJECTION_ID = UUID("00000000-0000-0000-0000-000000000301")
PROFILE_ID = UUID("00000000-0000-0000-0000-000000000201")
MODEL_ID = UUID("00000000-0000-0000-0000-000000000101")


def descriptor(*, dimension: int = 3, max_tokens: int = 4) -> EmbeddingDescriptor:
    return EmbeddingDescriptor(
        projection_id=PROJECTION_ID,
        indexing_profile_id=PROFILE_ID,
        model_definition_id=MODEL_ID,
        model_revision="d128750597153bb5987e10b1c3493a34e5a4502a",
        model_config_sha256="a" * 64,
        profile_config_sha256="b" * 64,
        dimension=dimension,
        max_tokens=max_tokens,
        normalize=True,
        output_mode="dense",
    )


def chunks(*texts: str) -> ChunkingResult:
    return ChunkingResult(
        chunks=tuple(
            RetrievalChunk(
                id=UUID(f"00000000-0000-0000-0000-{position:012d}"),
                projection_id=PROJECTION_ID,
                ordinal=position - 1,
                text=text,
                section_path=(),
                evidence_units=(),
            )
            for position, text in enumerate(texts, 1)
        ),
        evidence_units=(),
    )


class RecordingEmbedding:
    def __init__(self, output: list[list[float]]) -> None:
        self.dimension = 3
        self.output = output
        self.encoded: list[list[str]] = []

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.encoded.append(list(texts))
        return self.output

    def encode_query(self, text: str) -> list[float]:
        raise AssertionError("Document embedding must not encode queries.")


class BoundaryTokenizer:
    def __call__(
        self, text: str, *, add_special_tokens: bool, truncation: bool
    ) -> dict[str, list[int]]:
        assert add_special_tokens is True
        assert truncation is False
        return {"input_ids": list(range(len(text.split())))}


class BoundaryModel:
    def __init__(self) -> None:
        self.tokenizer = BoundaryTokenizer()
        self.encoded: list[list[str]] = []

    def get_sentence_embedding_dimension(self) -> int:
        return 3

    def encode(self, texts: Sequence[str], **kwargs: object) -> list[list[float]]:
        self.encoded.append(list(texts))
        return [[1.0, 0.0, 0.0] for _ in texts]


def boundary_embedding(model: BoundaryModel) -> SentenceTransformerEmbedding:
    return SentenceTransformerEmbedding(
        EmbeddingModelConfig(
            repo_id="intfloat/multilingual-e5-base",
            revision="d128750597153bb5987e10b1c3493a34e5a4502a",
            dimension=3,
            max_tokens=2,
            query_prefix="query: ",
            document_prefix="passage: ",
            normalize=True,
            device="cpu",
            dtype="float32",
            output_mode="dense",
            data_policy="local_only",
            batch_size=2,
        ),
        cache_folder=Path("unused-test-cache"),
        loader=lambda *args, **kwargs: model,
    )


def model_config() -> EmbeddingModelConfig:
    return EmbeddingModelConfig(
        repo_id="synthetic/model",
        revision="a" * 40,
        dimension=3,
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


def test_embedding_runtime_provider_loads_exact_config_once_per_workflow() -> None:
    calls: list[EmbeddingModelConfig] = []
    embedding = RecordingEmbedding([[1.0, 0.0, 0.0]])
    provider = EmbeddingRuntimeProvider(
        lambda config, _cache: calls.append(config) or embedding
    )
    config = model_config()

    assert provider.get(config, Path("unused")) is embedding
    assert provider.get(config, Path("unused")) is embedding
    assert calls == [config]


def test_model_tokenizer_rejects_korean_subword_overflow_before_embedding() -> None:
    element_id = uuid4()
    document = ParsedDocument(
        asset_version_id=uuid4(),
        parser_name="synthetic",
        parser_version="2",
        elements=(
            StructuralElement(
                id=element_id,
                ordinal=0,
                kind="paragraph",
                text="한국어하위단어토큰초과문장입니다.",
                section_path=(),
                location=SourceLocation(element_id, None, 0, 18, None),
                parser_name="synthetic",
                parser_version="2",
                confidence=1.0,
            ),
        ),
    )

    class KoreanSubwordEmbedding(RecordingEmbedding):
        def count_tokens(self, text: str) -> int:
            return len(text) * 2

        def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
            raise AssertionError("Oversized content must fail before embedding.")

    with pytest.raises(RagIngestionError) as error:
        chunk_with_model_tokenizer(
            document,
            projection_id=uuid4(),
            config=ChunkingConfig(8, 0, 10),
            embedding=KoreanSubwordEmbedding([]),
        )

    assert error.value.code == "chunk_token_limit_exceeded"
    assert error.value.retryable is False


def test_embedding_stage_validates_every_token_count_before_encoding() -> None:
    embedding = RecordingEmbedding([[1.0, 0.0, 0.0]])

    with pytest.raises(EmbeddingValidationError, match="token limit"):
        embed_chunks(
            chunks("one two", "one two three four five"),
            embedding=embedding,
            descriptor=descriptor(),
        )

    assert embedding.encoded == []


def test_embedding_stage_rejects_prefix_induced_overflow_before_model_encode() -> None:
    model = BoundaryModel()

    with pytest.raises(EmbeddingValidationError, match="token limit"):
        embed_chunks(
            chunks("one two"),
            embedding=boundary_embedding(model),
            descriptor=descriptor(max_tokens=2),
        )

    assert model.encoded == []


@pytest.mark.parametrize(
    ("output", "message"),
    [
        ([[1.0, 0.0, 0.0]], "count"),
        ([[1.0, 0.0], [1.0, 0.0]], "dimension"),
        ([[1.0, 1.0, 0.0], [1.0, 0.0, 0.0]], "normalized"),
    ],
)
def test_embedding_stage_rejects_invalid_output_before_artifact_publication(
    output: list[list[float]], message: str
) -> None:
    with pytest.raises(EmbeddingValidationError, match=message):
        embed_chunks(
            chunks("one", "two"),
            embedding=RecordingEmbedding(output),
            descriptor=descriptor(),
        )


def test_embedding_stage_preserves_authoritative_chunk_ids_and_order() -> None:
    source = chunks("one", "two")

    result = embed_chunks(
        source,
        embedding=RecordingEmbedding([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
        descriptor=descriptor(),
    )

    assert tuple(vector.chunk_id for vector in result.vectors) == tuple(
        chunk.id for chunk in source.chunks
    )


def test_indexing_preflight_accepts_only_exact_chunk_vector_order_and_descriptor() -> None:
    source = chunks("one", "two")
    expected = descriptor()
    embedded = embed_chunks(
        source,
        embedding=RecordingEmbedding([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
        descriptor=expected,
    )

    validate_indexing_inputs(source, embedded, expected_descriptor=expected)

    with pytest.raises(EmbeddingValidationError, match="order"):
        validate_indexing_inputs(
            source,
            replace(embedded, vectors=tuple(reversed(embedded.vectors))),
            expected_descriptor=expected,
        )
    with pytest.raises(EmbeddingValidationError, match="descriptor"):
        validate_indexing_inputs(
            source,
            embedded,
            expected_descriptor=replace(expected, profile_config_sha256="c" * 64),
        )
