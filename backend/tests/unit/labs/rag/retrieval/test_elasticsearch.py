from typing import Any, cast
from uuid import UUID

import pytest
from elasticsearch import AsyncElasticsearch

from ai_workshop.labs.rag.retrieval.domain import ResolvedSearchScope
from ai_workshop.labs.rag.retrieval.elasticsearch import (
    ElasticsearchDenseRetriever,
    ElasticsearchSparseRetriever,
)


class RecordingClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def search(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(kwargs)
        return self.response


def _response() -> dict[str, object]:
    chunk_id = "00000000-0000-0000-0000-000000000801"
    projection_id = "00000000-0000-0000-0000-000000000802"
    return {
        "hits": {
            "hits": [
                {
                    "_score": 2.5,
                    "_source": {
                        "chunk_id": chunk_id,
                        "projection_id": projection_id,
                        "asset_version_id": "00000000-0000-0000-0000-000000000803",
                        "workspace_id": "00000000-0000-0000-0000-000000000804",
                        "folder_id": "00000000-0000-0000-0000-000000000805",
                        "index_build_id": "00000000-0000-0000-0000-000000000806",
                        "title": "Synthetic source",
                        "section_path": ["Policy", "Limits"],
                        "text": "Synthetic evidence text",
                        "evidence_units": [
                            {
                                "id": "00000000-0000-0000-0000-000000000807",
                                "chunk_id": chunk_id,
                                "projection_id": projection_id,
                                "ordinal": 0,
                                "text": "Synthetic evidence text",
                                "element_id": "00000000-0000-0000-0000-000000000808",
                                "page": 2,
                                "char_start": 10,
                                "char_end": 33,
                                "bbox": [1.0, 2.0, 3.0, 4.0],
                            }
                        ],
                    },
                }
            ]
        }
    }


@pytest.mark.asyncio
async def test_sparse_and_dense_use_equivalent_acl_prefilters_and_hide_vectors() -> None:
    actor_id = UUID("00000000-0000-0000-0000-000000000809")
    workspace_id = UUID("00000000-0000-0000-0000-000000000804")
    folder_id = UUID("00000000-0000-0000-0000-000000000805")
    scope = ResolvedSearchScope((workspace_id,), (folder_id,))
    client = RecordingClient(_response())
    sparse = ElasticsearchSparseRetriever(cast(AsyncElasticsearch, client))
    dense = ElasticsearchDenseRetriever(cast(AsyncElasticsearch, client))

    sparse_hits = await sparse.search_sparse(
        index_alias="profile-active",
        query="synthetic",
        actor_id=actor_id,
        scope=scope,
        top_k=5,
    )
    dense_hits = await dense.search_dense(
        index_alias="profile-active",
        query_vector=(1.0, 0.0),
        actor_id=actor_id,
        scope=scope,
        top_k=5,
    )

    sparse_filter = cast(dict[str, Any], client.calls[0]["query"])["bool"]["filter"]
    dense_filter = cast(dict[str, Any], client.calls[1]["knn"])["filter"]["bool"][
        "filter"
    ]
    assert sparse_filter == dense_filter == [
        {"terms": {"workspace_id": [str(workspace_id)]}},
        {"term": {"allowed_user_ids": str(actor_id)}},
        {"terms": {"folder_id": [str(folder_id)]}},
        {"term": {"status": "ready"}},
    ]
    assert all(
        "embedding" not in cast(dict[str, list[str]], call["source"])["includes"]
        for call in client.calls
    )
    assert sparse_hits[0].chunk == dense_hits[0].chunk
    evidence = sparse_hits[0].chunk.evidence_units[0]
    assert evidence.location.bbox == (1.0, 2.0, 3.0, 4.0)
    assert evidence.location.char_start == 10
    assert evidence.projection_id == sparse_hits[0].chunk.projection_id
