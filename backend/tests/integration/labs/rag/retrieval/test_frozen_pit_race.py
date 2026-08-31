from contextlib import suppress
from typing import Any, cast
from uuid import uuid4

import pytest
from elasticsearch import AsyncElasticsearch, NotFoundError

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, IndexDocument
from ai_workshop.labs.rag.indexing.elasticsearch import (
    ElasticsearchSearchIndex,
    build_mapping,
)
from ai_workshop.labs.rag.indexing.service import IndexingService
from ai_workshop.labs.rag.retrieval.domain import (
    FrozenIndexTarget,
    ResolvedSearchScope,
)
from ai_workshop.labs.rag.retrieval.elasticsearch import (
    ElasticsearchFrozenIndexInspector,
    ElasticsearchSparseRetriever,
    FrozenIndexDriftError,
)

pytestmark = pytest.mark.integration


class RecreateAfterPitClient:
    def __init__(
        self,
        delegate: AsyncElasticsearch,
        descriptor: IndexDescriptor,
    ) -> None:
        self.delegate = delegate
        self.indices = delegate.indices
        self.descriptor = descriptor
        self.search_called = False
        self.close_called = False

    async def open_point_in_time(self, **kwargs: Any) -> Any:
        opened = await self.delegate.open_point_in_time(**kwargs)
        await self.delegate.indices.delete(index=self.descriptor.index_name)
        await self.delegate.indices.create(
            index=self.descriptor.index_name,
            **build_mapping(self.descriptor),
        )
        return opened

    async def search(self, **kwargs: Any) -> Any:
        self.search_called = True
        return await self.delegate.search(**kwargs)

    async def close_point_in_time(self, **kwargs: Any) -> Any:
        self.close_called = True
        return await self.delegate.close_point_in_time(**kwargs)


@pytest.mark.asyncio
async def test_real_elasticsearch_recreation_after_pit_never_searches_replacement() -> None:
    settings = Settings(  # type: ignore[call-arg]
        secret_key="task11-real-pit-race-secret-key-value",
        elasticsearch_url="http://127.0.0.1:9200",
        elasticsearch_index_prefix=f"task11-pit-race-{uuid4().hex}",
    )
    client = create_elasticsearch(settings)
    profile_id = uuid4()
    build_id = uuid4()
    projection_id = uuid4()
    asset_version_id = uuid4()
    workspace_id = uuid4()
    actor_id = uuid4()
    descriptor = IndexDescriptor(2, "cosine")
    index_name = descriptor.concrete_index_name(
        settings.elasticsearch_index_prefix, profile_id, build_id
    )
    physical_descriptor = descriptor.for_index(
        index_name,
        indexing_profile_id=profile_id,
        index_build_id=build_id,
        projection_id=projection_id,
    )
    try:
        await IndexingService(
            ElasticsearchSearchIndex(client),
            index_prefix=settings.elasticsearch_index_prefix,
        ).index_projection(
            descriptor=descriptor,
            profile_id=profile_id,
            build_id=build_id,
            projection_id=projection_id,
            expected_chunk_count=1,
            documents=(
                IndexDocument(
                    chunk_id=uuid4(),
                    projection_id=projection_id,
                    asset_version_id=asset_version_id,
                    workspace_id=workspace_id,
                    folder_id=None,
                    allowed_user_ids=(actor_id,),
                    status="ready",
                    title="old frozen index",
                    section_path=(),
                    text="must never come from a replacement index",
                    evidence_units=(),
                    embedding=(1.0, 0.0),
                    index_build_id=build_id,
                ),
            ),
        )
        identity = await ElasticsearchFrozenIndexInspector(client).describe(index_name)
        target = FrozenIndexTarget(
            descriptor=descriptor,
            index_prefix=settings.elasticsearch_index_prefix,
            indexing_profile_id=profile_id,
            identities=(identity,),
            asset_version_ids=(asset_version_id,),
        )
        race_client = RecreateAfterPitClient(client, physical_descriptor)

        with pytest.raises(FrozenIndexDriftError, match="UUID"):
            await ElasticsearchSparseRetriever(
                cast(AsyncElasticsearch, race_client)
            ).search_sparse(
                index_alias=target,
                query="replacement",
                actor_id=actor_id,
                scope=ResolvedSearchScope(
                    (workspace_id,),
                    (),
                    active_only=False,
                    asset_version_ids=(asset_version_id,),
                    index_build_ids=(build_id,),
                ),
                top_k=5,
            )

        assert race_client.search_called is False
        assert race_client.close_called is True
    finally:
        with suppress(NotFoundError):
            await client.indices.delete(index=index_name)
        await client.close()
