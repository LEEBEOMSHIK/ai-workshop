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
    def __init__(
        self,
        *,
        acknowledged: bool,
        current_targets: tuple[str, ...] = (),
    ) -> None:
        self.acknowledged = acknowledged
        self.current_targets = current_targets
        self.actions: list[dict[str, object]] | None = None

    async def get_alias(self, *, name: str) -> dict[str, object]:
        return {target: {"aliases": {name: {}}} for target in self.current_targets}

    async def update_aliases(self, *, actions: list[dict[str, object]]) -> dict[str, bool]:
        self.actions = actions
        return {"acknowledged": self.acknowledged}


class AliasClient:
    def __init__(
        self,
        *,
        acknowledged: bool,
        current_targets: tuple[str, ...] = (),
    ) -> None:
        self.indices = AliasIndices(
            acknowledged=acknowledged,
            current_targets=current_targets,
        )


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
async def test_exact_alias_replacement_is_sorted_and_returns_acknowledgement(
    acknowledged: bool,
) -> None:
    profile_id = UUID("00000000-0000-0000-0000-000000000510")
    first_build_id = UUID("00000000-0000-0000-0000-000000000511")
    second_build_id = UUID("00000000-0000-0000-0000-000000000512")
    alias = f"rag-{profile_id}-active"
    first = f"rag-{profile_id}-{first_build_id}"
    second = f"rag-{profile_id}-{second_build_id}"
    stale = f"rag-{profile_id}-00000000-0000-0000-0000-000000000513"
    client = AliasClient(acknowledged=acknowledged, current_targets=(stale,))
    adapter = ElasticsearchSearchIndex(cast(AsyncElasticsearch, client))

    activated = await adapter.replace_active_targets(alias, (second, first))

    assert activated is acknowledged
    assert client.indices.actions == [
        {"remove": {"index": stale, "alias": alias}},
        {"add": {"index": first, "alias": alias}},
        {"add": {"index": second, "alias": alias}},
    ]


@pytest.mark.asyncio
async def test_exact_alias_replacement_is_idempotent_without_an_update() -> None:
    profile_id = UUID("00000000-0000-0000-0000-000000000520")
    first = f"rag-{profile_id}-00000000-0000-0000-0000-000000000521"
    second = f"rag-{profile_id}-00000000-0000-0000-0000-000000000522"
    alias = f"rag-{profile_id}-active"
    client = AliasClient(
        acknowledged=True,
        current_targets=(second, first),
    )
    adapter = ElasticsearchSearchIndex(cast(AsyncElasticsearch, client))

    activated = await adapter.replace_active_targets(alias, (first, second))

    assert activated is True
    assert client.indices.actions is None
    assert await adapter.active_targets(alias) == (first, second)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "targets",
    [
        (),
        (
            "rag-00000000-0000-0000-0000-000000000530-"
            "00000000-0000-0000-0000-000000000531",
        )
        * 2,
        ("rag-00000000-0000-0000-0000-000000000999-00000000-0000-0000-0000-000000000531",),
        ("rag-00000000-0000-0000-0000-000000000530-*,other",),
    ],
    ids=("empty", "duplicate", "other-profile", "injected"),
)
async def test_exact_alias_replacement_rejects_unsafe_target_sets(
    targets: tuple[str, ...],
) -> None:
    profile_id = UUID("00000000-0000-0000-0000-000000000530")
    alias = f"rag-{profile_id}-active"
    client = AliasClient(acknowledged=True)
    adapter = ElasticsearchSearchIndex(cast(AsyncElasticsearch, client))

    with pytest.raises(ValueError):
        await adapter.replace_active_targets(alias, targets)

    assert client.indices.actions is None


@pytest.mark.asyncio
async def test_recovery_alias_replacement_removes_every_stale_target() -> None:
    profile_id = UUID("00000000-0000-0000-0000-000000000540")
    alias = f"rag-{profile_id}-active"
    first = f"rag-{profile_id}-00000000-0000-0000-0000-000000000541"
    second = f"rag-{profile_id}-00000000-0000-0000-0000-000000000542"
    client = AliasClient(
        acknowledged=True,
        current_targets=(second, first),
    )
    adapter = ElasticsearchSearchIndex(cast(AsyncElasticsearch, client))

    reconciled = await adapter.reconcile_active_targets(alias, ())

    assert reconciled is True
    assert client.indices.actions == [
        {"remove": {"index": first, "alias": alias}},
        {"remove": {"index": second, "alias": alias}},
    ]


@pytest.mark.asyncio
async def test_recovery_empty_set_still_rejects_unsafe_profile_alias() -> None:
    client = AliasClient(acknowledged=True)
    adapter = ElasticsearchSearchIndex(cast(AsyncElasticsearch, client))

    with pytest.raises(ValueError, match="safe profile alias"):
        await adapter.reconcile_active_targets("rag-*-active", ())

    assert client.indices.actions is None
