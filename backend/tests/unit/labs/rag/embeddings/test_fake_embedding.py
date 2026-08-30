import math

import pytest

from ai_workshop.labs.rag.embeddings.fake import DeterministicFakeEmbedding


def test_fake_is_deterministic_fixed_dimension_and_normalized() -> None:
    embedding = DeterministicFakeEmbedding(
        dimension=12,
        query_prefix="query: ",
        document_prefix="passage: ",
    )

    first = embedding.encode_documents(["alpha beta"])[0]
    second = embedding.encode_documents(["alpha beta"])[0]

    assert first == second
    assert len(first) == 12
    assert all(math.isfinite(value) for value in first)
    assert math.sqrt(sum(value * value for value in first)) == pytest.approx(1.0)


def test_fake_hashes_query_and_document_prefixes_differently() -> None:
    embedding = DeterministicFakeEmbedding(
        dimension=16,
        query_prefix="query: ",
        document_prefix="passage: ",
    )

    assert embedding.encode_query("same text") != embedding.encode_documents(["same text"])[0]
    assert embedding.count_tokens("one two  three") == 4
    assert embedding.count_query_tokens("one two  three") == 4


def test_fake_one_dimension_vectors_never_divide_by_a_zero_hash_bucket() -> None:
    embedding = DeterministicFakeEmbedding(
        dimension=1,
        query_prefix="",
        document_prefix="",
    )

    assert embedding.encode_documents(["token-415"])[0] == [1.0]
