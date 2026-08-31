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


@pytest.mark.asyncio
async def test_active_alias_searches_two_projections_and_removes_superseded_version() -> None:
    client = create_elasticsearch(Settings(secret_key="x" * 32))
    profile_id = uuid4()
    workspace_id = uuid4()
    service = IndexingService(
        ElasticsearchSearchIndex(client), index_prefix=f"rag-task14a-{uuid4().hex}"
    )
    descriptor = IndexDescriptor(vector_dimension=2, similarity="cosine")
    first_build_id, second_build_id, replacement_build_id = uuid4(), uuid4(), uuid4()
    first_projection_id, second_projection_id, replacement_projection_id = (
        uuid4(),
        uuid4(),
        uuid4(),
    )
    first_chunk_id, second_chunk_id, replacement_chunk_id = uuid4(), uuid4(), uuid4()

    def document(
        *,
        build_id,
        projection_id,
        chunk_id,
        text: str,
        embedding: tuple[float, float],
    ) -> IndexDocument:
        return IndexDocument(
            chunk_id=chunk_id,
            projection_id=projection_id,
            asset_version_id=uuid4(),
            workspace_id=workspace_id,
            folder_id=None,
            allowed_user_ids=(),
            status="ready",
            title="Task 14A synthetic fixture",
            section_path=(),
            text=text,
            evidence_units=(),
            embedding=embedding,
            index_build_id=build_id,
        )

    first = document(
        build_id=first_build_id,
        projection_id=first_projection_id,
        chunk_id=first_chunk_id,
        text="synthetic first-version-only alpha evidence",
        embedding=(1.0, 0.0),
    )
    second = document(
        build_id=second_build_id,
        projection_id=second_projection_id,
        chunk_id=second_chunk_id,
        text="synthetic retained beta evidence",
        embedding=(0.0, 1.0),
    )
    replacement = document(
        build_id=replacement_build_id,
        projection_id=replacement_projection_id,
        chunk_id=replacement_chunk_id,
        text="synthetic replacement alpha evidence",
        embedding=(1.0, 0.0),
    )
    index_names = tuple(
        descriptor.concrete_index_name(service.index_prefix, profile_id, build_id)
        for build_id in (first_build_id, second_build_id, replacement_build_id)
    )
    alias = descriptor.active_alias(service.index_prefix, profile_id)

    try:
        await service.index_projection(
            descriptor=descriptor,
            profile_id=profile_id,
            build_id=first_build_id,
            projection_id=first_projection_id,
            expected_chunk_count=1,
            documents=(first,),
        )
        await service.index_projection(
            descriptor=descriptor,
            profile_id=profile_id,
            build_id=second_build_id,
            projection_id=second_projection_id,
            expected_chunk_count=1,
            documents=(second,),
        )
        await client.indices.refresh(index=alias)

        bm25 = await client.search(
            index=alias,
            query={"match": {"text": "synthetic evidence"}},
            size=10,
        )
        dense = await client.search(
            index=alias,
            knn={
                "field": "embedding",
                "query_vector": [1.0, 0.0],
                "k": 2,
                "num_candidates": 2,
            },
            size=2,
        )
        assert {hit["_id"] for hit in bm25["hits"]["hits"]} == {
            str(first_chunk_id),
            str(second_chunk_id),
        }
        assert {hit["_id"] for hit in dense["hits"]["hits"]} == {
            str(first_chunk_id),
            str(second_chunk_id),
        }

        prepared = await service.prepare_projection(
            descriptor=descriptor,
            profile_id=profile_id,
            build_id=replacement_build_id,
            projection_id=replacement_projection_id,
            expected_chunk_count=1,
            documents=(replacement,),
        )
        await service.activate_prepared(
            prepared,
            intended_targets=(index_names[1], index_names[2]),
        )
        await client.indices.refresh(index=alias)

        active = await client.search(index=alias, query={"match_all": {}}, size=10)
        removed = await client.search(
            index=alias,
            query={"match": {"text": "first-version-only"}},
            size=10,
        )
        assert {hit["_id"] for hit in active["hits"]["hits"]} == {
            str(second_chunk_id),
            str(replacement_chunk_id),
        }
        assert removed["hits"]["total"]["value"] == 0
    finally:
        await client.indices.delete(index=",".join(index_names), ignore_unavailable=True)
        await client.close()
