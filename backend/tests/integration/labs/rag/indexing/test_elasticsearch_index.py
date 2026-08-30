from uuid import uuid4

import pytest
from elasticsearch import NotFoundError

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, IndexDocument
from ai_workshop.labs.rag.indexing.elasticsearch import ElasticsearchSearchIndex
from ai_workshop.labs.rag.indexing.service import IndexingService

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_bm25_finds_korean_product_only_in_authorized_workspace() -> None:
    client = create_elasticsearch(Settings(secret_key="x" * 32))
    profile_id = uuid4()
    build_id = uuid4()
    projection_id = uuid4()
    authorized_workspace = uuid4()
    mismatched_workspace = uuid4()
    service = IndexingService(
        ElasticsearchSearchIndex(client), index_prefix=f"rag-task6-{uuid4().hex}"
    )
    descriptor = IndexDescriptor(vector_dimension=768, similarity="cosine")
    document = IndexDocument(
        chunk_id=uuid4(),
        projection_id=projection_id,
        asset_version_id=uuid4(),
        workspace_id=authorized_workspace,
        folder_id=None,
        allowed_user_ids=(uuid4(),),
        status="ready",
        title="Korean BM25 fixture",
        section_path=("상품",),
        text="테스트전용한국상품명 수익률 안내",
        evidence_units=(),
        embedding=None,
        index_build_id=build_id,
    )
    concrete_index = descriptor.concrete_index_name(service.index_prefix, profile_id, build_id)
    alias = descriptor.active_alias(service.index_prefix, profile_id)

    try:
        await service.index_projection(
            descriptor=descriptor,
            profile_id=profile_id,
            build_id=build_id,
            projection_id=projection_id,
            expected_chunk_count=1,
            documents=(document,),
        )
        await client.indices.refresh(index=concrete_index)
        found = await client.search(
            index=alias,
            query={
                "bool": {
                    "must": [{"match": {"text": "테스트전용한국상품명"}}],
                    "filter": [{"term": {"workspace_id": str(authorized_workspace)}}],
                }
            },
        )
        denied = await client.search(
            index=alias,
            query={
                "bool": {
                    "must": [{"match": {"text": "테스트전용한국상품명"}}],
                    "filter": [{"term": {"workspace_id": str(mismatched_workspace)}}],
                }
            },
        )

        assert found["hits"]["total"]["value"] == 1
        assert denied["hits"]["total"]["value"] == 0
    finally:
        try:
            await client.indices.delete_alias(index=concrete_index, name=alias)
        except NotFoundError:
            pass
        finally:
            await client.indices.delete(index=concrete_index, ignore_unavailable=True)
            await client.close()
