from typing import Any, cast
from uuid import UUID

import pytest
from elasticsearch import AsyncElasticsearch

from ai_workshop.labs.rag.indexing.contracts import IndexDocument
from ai_workshop.labs.rag.indexing.elasticsearch import ElasticsearchSearchIndex


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
