from typing import Any, cast
from uuid import UUID

import pytest
from elasticsearch import AsyncElasticsearch, TransportError

from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.retrieval.domain import (
    FrozenIndexIdentity,
    FrozenIndexTarget,
    ResolvedSearchScope,
)
from ai_workshop.labs.rag.retrieval.elasticsearch import (
    ElasticsearchSparseRetriever,
    FrozenIndexDriftError,
    FrozenIndexReindexRequiredError,
    PointInTimeCleanupError,
    describe_frozen_index,
)

PROFILE_ID = UUID("00000000-0000-0000-0000-000000000701")
BUILD_ID = UUID("00000000-0000-0000-0000-000000000702")
PROJECTION_ID = UUID("00000000-0000-0000-0000-000000000703")
ASSET_ID = UUID("00000000-0000-0000-0000-000000000704")
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000705")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000706")
INDEX_NAME = f"task11-{PROFILE_ID}-{BUILD_ID}"


def _metadata(*, index_uuid: str = "index-uuid-1", include_rag: bool = True) -> dict[str, Any]:
    mappings: dict[str, Any] = {}
    if include_rag:
        mappings["_meta"] = {
            "rag": {
                "mapping_version": 1,
                "index_build_id": str(BUILD_ID),
                "projection_id": str(PROJECTION_ID),
                "indexing_profile_id": str(PROFILE_ID),
                "vector_dimension": 2,
            }
        }
    return {
        INDEX_NAME: {
            "settings": {"index": {"uuid": index_uuid}},
            "mappings": mappings,
        }
    }


class PitIndices:
    def __init__(self, owner: "PitClient") -> None:
        self.owner = owner

    async def resolve_index(self, **kwargs: Any) -> dict[str, Any]:
        self.owner.events.append(("resolve", kwargs))
        return {
            "indices": [{"name": INDEX_NAME, "aliases": []}],
            "aliases": [],
            "data_streams": [],
        }

    async def get(self, **kwargs: Any) -> dict[str, Any]:
        self.owner.events.append(("get", kwargs))
        return self.owner.metadata


class PitClient:
    def __init__(self) -> None:
        self.indices = PitIndices(self)
        self.metadata = _metadata()
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.swap_after_open = False
        self.search_failure: Exception | None = None
        self.close_failure: Exception | None = None

    async def open_point_in_time(self, **kwargs: Any) -> dict[str, str]:
        self.events.append(("open", kwargs))
        if self.swap_after_open:
            self.metadata = _metadata(index_uuid="replacement-uuid")
        return {"id": "pit-1"}

    async def search(self, **kwargs: Any) -> dict[str, Any]:
        self.events.append(("search", kwargs))
        if self.search_failure is not None:
            raise self.search_failure
        return {
            "pit_id": "pit-2",
            "hits": {
                "hits": [
                    {
                        "_score": 1.0,
                        "_source": {
                            "chunk_id": "00000000-0000-0000-0000-000000000707",
                            "projection_id": str(PROJECTION_ID),
                            "asset_version_id": str(ASSET_ID),
                            "workspace_id": str(WORKSPACE_ID),
                            "folder_id": None,
                            "index_build_id": str(BUILD_ID),
                            "indexing_profile_id": str(PROFILE_ID),
                            "rag_mapping_version": 1,
                            "title": "Frozen",
                            "section_path": [],
                            "text": "frozen evidence",
                            "evidence_units": [],
                        },
                    }
                ]
            },
        }

    async def close_point_in_time(self, **kwargs: Any) -> dict[str, bool]:
        self.events.append(("close", kwargs))
        if self.close_failure is not None:
            raise self.close_failure
        return {"succeeded": True}


def _target() -> FrozenIndexTarget:
    return FrozenIndexTarget(
        descriptor=IndexDescriptor(vector_dimension=2, similarity="cosine"),
        index_prefix="task11",
        indexing_profile_id=PROFILE_ID,
        identities=(
            FrozenIndexIdentity(
                index_name=INDEX_NAME,
                index_uuid="index-uuid-1",
                index_build_id=BUILD_ID,
                projection_id=PROJECTION_ID,
                indexing_profile_id=PROFILE_ID,
                vector_dimension=2,
                mapping_version=1,
            ),
        ),
        asset_version_ids=(ASSET_ID,),
    )


def _scope() -> ResolvedSearchScope:
    return ResolvedSearchScope(
        (WORKSPACE_ID,),
        (),
        active_only=False,
        asset_version_ids=(ASSET_ID,),
        index_build_ids=(BUILD_ID,),
    )


@pytest.mark.asyncio
async def test_missing_rag_mapping_metadata_requires_explicit_reindex() -> None:
    client = PitClient()
    client.metadata = _metadata(include_rag=False)

    with pytest.raises(FrozenIndexReindexRequiredError, match="reindex"):
        await describe_frozen_index(cast(AsyncElasticsearch, client), INDEX_NAME)


@pytest.mark.asyncio
async def test_frozen_search_uses_revalidated_pit_and_exact_descriptor_filters() -> None:
    client = PitClient()

    hits = await ElasticsearchSparseRetriever(
        cast(AsyncElasticsearch, client)
    ).search_sparse(
        index_alias=_target(),
        query="frozen",
        actor_id=ACTOR_ID,
        scope=_scope(),
        top_k=2,
    )

    assert hits[0].chunk.index_build_id == BUILD_ID
    names = [name for name, _ in client.events]
    assert names == ["resolve", "get", "open", "resolve", "get", "search", "close"]
    search = next(kwargs for name, kwargs in client.events if name == "search")
    assert "index" not in search
    assert search["pit"] == {"id": "pit-1", "keep_alive": "1m"}
    assert {
        tuple(item["term"].items())[0]
        for item in search["query"]["bool"]["filter"]
        if "term" in item
    } >= {
        ("index_build_id", str(BUILD_ID)),
        ("projection_id", str(PROJECTION_ID)),
        ("indexing_profile_id", str(PROFILE_ID)),
        ("rag_mapping_version", 1),
    }
    assert client.events[-1] == ("close", {"id": "pit-2"})


@pytest.mark.asyncio
async def test_index_recreation_between_pit_open_and_search_fails_closed() -> None:
    client = PitClient()
    client.swap_after_open = True

    with pytest.raises(FrozenIndexDriftError, match="UUID"):
        await ElasticsearchSparseRetriever(
            cast(AsyncElasticsearch, client)
        ).search_sparse(
            index_alias=_target(),
            query="frozen",
            actor_id=ACTOR_ID,
            scope=_scope(),
            top_k=2,
        )

    assert "search" not in [name for name, _ in client.events]
    assert client.events[-1] == ("close", {"id": "pit-1"})


@pytest.mark.asyncio
async def test_pit_cleanup_failure_is_typed_without_masking_primary_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = PitClient()
    primary = TypeError("primary search defect")
    client.search_failure = primary
    client.close_failure = TransportError("close failed")

    with pytest.raises(TypeError) as error:
        await ElasticsearchSparseRetriever(
            cast(AsyncElasticsearch, client)
        ).search_sparse(
            index_alias=_target(),
            query="frozen",
            actor_id=ACTOR_ID,
            scope=_scope(),
            top_k=2,
        )

    assert error.value is primary
    assert isinstance(
        cast(Any, error.value).pit_cleanup_error, PointInTimeCleanupError
    )
    assert "point-in-time cleanup failed" in caplog.text.lower()


@pytest.mark.asyncio
async def test_pit_cleanup_failure_after_success_is_typed() -> None:
    client = PitClient()
    client.close_failure = TransportError("close failed")

    with pytest.raises(PointInTimeCleanupError, match="cleanup failed"):
        await ElasticsearchSparseRetriever(
            cast(AsyncElasticsearch, client)
        ).search_sparse(
            index_alias=_target(),
            query="frozen",
            actor_id=ACTOR_ID,
            scope=_scope(),
            top_k=2,
        )
