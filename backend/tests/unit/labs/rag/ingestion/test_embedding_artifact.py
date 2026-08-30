import math
from dataclasses import replace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingDescriptor,
    EmbeddingResult,
    EmbeddingValidationError,
    EmbeddingVector,
)
from ai_workshop.labs.rag.ingestion.serialization import (
    deserialize_embedding_result,
    serialize_embedding_result,
)

PROJECTION_ID = UUID("00000000-0000-0000-0000-000000000301")
PROFILE_ID = UUID("00000000-0000-0000-0000-000000000201")
MODEL_ID = UUID("00000000-0000-0000-0000-000000000101")
CHUNK_IDS = (
    UUID("00000000-0000-0000-0000-000000000401"),
    UUID("00000000-0000-0000-0000-000000000402"),
)


def descriptor() -> EmbeddingDescriptor:
    return EmbeddingDescriptor(
        projection_id=PROJECTION_ID,
        indexing_profile_id=PROFILE_ID,
        model_definition_id=MODEL_ID,
        model_revision="d128750597153bb5987e10b1c3493a34e5a4502a",
        model_config_sha256="a" * 64,
        profile_config_sha256="b" * 64,
        dimension=3,
        max_tokens=512,
        normalize=True,
        output_mode="dense",
    )


def result() -> EmbeddingResult:
    return EmbeddingResult(
        descriptor(),
        (
            EmbeddingVector(CHUNK_IDS[0], (1.0, 0.0, 0.0)),
            EmbeddingVector(CHUNK_IDS[1], (0.0, -1.0, 0.0)),
        ),
    )


def test_embedding_artifact_round_trip_preserves_descriptor_chunk_order_and_floats() -> None:
    content = serialize_embedding_result(result())

    restored = deserialize_embedding_result(content)

    assert restored == result()
    assert tuple(vector.chunk_id for vector in restored.vectors) == CHUNK_IDS
    assert b"document text" not in content
    assert b"document_text" not in content.lower()


@pytest.mark.parametrize(
    ("vector", "message"),
    [
        ((1.0, 0.0), "dimension"),
        ((math.nan, 0.0, 0.0), "finite"),
        ((1.0, 1.0, 0.0), "normalized"),
    ],
)
def test_embedding_result_rejects_invalid_dense_vector(
    vector: tuple[float, ...], message: str
) -> None:
    with pytest.raises(EmbeddingValidationError, match=message):
        EmbeddingResult(descriptor(), (EmbeddingVector(CHUNK_IDS[0], vector),))


def test_embedding_result_rejects_duplicate_chunk_ids() -> None:
    duplicate = EmbeddingVector(CHUNK_IDS[0], (1.0, 0.0, 0.0))

    with pytest.raises(EmbeddingValidationError, match="unique"):
        EmbeddingResult(descriptor(), (duplicate, duplicate))


def test_embedding_descriptor_rejects_unpinned_or_sparse_identity() -> None:
    with pytest.raises(EmbeddingValidationError, match="revision"):
        replace(descriptor(), model_revision="main")
    with pytest.raises(EmbeddingValidationError, match="dense"):
        replace(descriptor(), output_mode="sparse")
