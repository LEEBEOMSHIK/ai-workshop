from typing import Any, cast
from uuid import UUID

import pytest
from elasticsearch import AsyncElasticsearch

from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, IndexDocument
from ai_workshop.labs.rag.indexing.elasticsearch import (
    ElasticsearchSearchIndex,
    build_mapping,
)


class BulkClient:
    def __init__(self) -> None:
        self.operations: list[dict[str, object]] | None = None
        self.refresh: bool | None = None

    async def bulk(self, **kwargs: Any) -> dict[str, object]:
        self.operations = kwargs["operations"]
        self.refresh = kwargs["refresh"]
        return {"errors": False, "items": []}


class AliasIndices:
    def __init__(self, *, acknowledged: bool) -> None:
        self.acknowledged = acknowledged

    async def get_alias(self, *, name: str) -> dict[str, object]:
        return {}

    async def update_aliases(self, *, actions: list[dict[str, object]]) -> dict[str, bool]:
        return {"acknowledged": self.acknowledged}


class AliasClient:
    def __init__(self, *, acknowledged: bool) -> None:
        self.indices = AliasIndices(acknowledged=acknowledged)


def test_mapping_carries_immutable_rag_descriptor_metadata() -> None:
    profile_id = UUID("00000000-0000-0000-0000-000000000504")
    build_id = UUID("00000000-0000-0000-0000-000000000505")
    projection_id = UUID("00000000-0000-0000-0000-000000000506")
    descriptor = IndexDescriptor(vector_dimension=1024, similarity="cosine").for_index(
        "rag-profile-build",
        indexing_profile_id=profile_id,
        index_build_id=build_id,
        projection_id=projection_id,
    )

    mapping = build_mapping(descriptor)

    assert mapping["mappings"]["_meta"] == {
        "rag": {
            "mapping_version": 1,
            "index_build_id": str(build_id),
            "projection_id": str(projection_id),
            "indexing_profile_id": str(profile_id),
            "vector_dimension": 1024,
        }
    }
    properties = mapping["mappings"]["properties"]
    assert properties["indexing_profile_id"] == {"type": "keyword"}
    assert properties["rag_mapping_version"] == {"type": "integer"}


def _document() -> IndexDocument:
    return IndexDocument(
        chunk_id=UUID("00000000-0000-0000-0000-000000000501"),
        projection_id=UUID("00000000-0000-0000-0000-000000000502"),
        asset_version_id=UUID("00000000-0000-0000-0000-000000000503"),
        workspace_id=UUID("00000000-0000-0000-0000-000000000504"),
        folder_id=None,
        allowed_user_ids=(),
        status="ready",
        title="fixture",
        section_path=(),
        text="fixture",
        evidence_units=(),
        embedding=None,
        index_build_id=UUID("00000000-0000-0000-0000-000000000505"),
    )


@pytest.mark.asyncio
async def test_bulk_uses_chunk_uuid_as_stable_id_without_refresh() -> None:
    client = BulkClient()
    adapter = ElasticsearchSearchIndex(cast(AsyncElasticsearch, client))

    indexed = await adapter.bulk_upsert("concrete-index", (_document(),))

    assert indexed == 1
    assert client.refresh is False
    assert client.operations == [
        {
            "index": {
                "_index": "concrete-index",
                "_id": "00000000-0000-0000-0000-000000000501",
            }
        },
        _document().to_projection(),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("acknowledged", [False, True])
async def test_alias_activation_returns_elasticsearch_acknowledgement(
    acknowledged: bool,
) -> None:
    adapter = ElasticsearchSearchIndex(
        cast(AsyncElasticsearch, AliasClient(acknowledged=acknowledged))
    )

    activated = await adapter.activate("profile-active", "concrete-index")

    assert activated is acknowledged
