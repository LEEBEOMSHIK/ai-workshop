from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.indexing.tracking_contracts import (
    IndexBinding,
    IndexResource,
    IndexTrackingError,
)


def test_binding_rejects_endpoint_and_blank_cluster():
    for store, cluster in [("https://secret", "cluster"), ("rag", ""), ("rag", "cluster secret")]:
        with pytest.raises(ValueError):
            IndexBinding(store, cluster)


def test_resource_rejects_nonpositive_revision():
    ids = [uuid4() for _ in range(8)]
    resource = IndexResource(
        *ids,
        1,
        IndexBinding("rag", "opaque-cluster"),
        "rag-index",
        "rag-active",
        1,
        3,
        "cosine",
        None,
        None,
    )
    with pytest.raises(ValueError):
        replace(resource, revision=0)


def test_error_payload_is_allowlisted():
    assert str(IndexTrackingError("rag_index_attempt_busy")) == "rag_index_attempt_busy"
    with pytest.raises(ValueError, match="Invalid index tracking code"):
        IndexTrackingError("https://user:secret@example.test")


def test_chunk_fingerprint_is_order_independent_and_rejects_duplicate_ids():
    from ai_workshop.labs.rag.indexing.tracking_contracts import index_chunk_ids_fingerprint

    first, second = uuid4(), uuid4()
    assert index_chunk_ids_fingerprint([first, second]) == index_chunk_ids_fingerprint(
        [second, first]
    )
    assert index_chunk_ids_fingerprint([first]) != index_chunk_ids_fingerprint([second])
    with pytest.raises(IndexTrackingError):
        index_chunk_ids_fingerprint([first, first])


def test_resource_rejects_invalid_chunk_ids_digest():
    ids = [uuid4() for _ in range(8)]
    with pytest.raises(ValueError):
        IndexResource(
            *ids,
            1,
            IndexBinding("rag", "cluster"),
            "index",
            "alias",
            1,
            3,
            "cosine",
            None,
            "a" * 64,
            "secret",
        )
