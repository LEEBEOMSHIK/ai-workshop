from uuid import uuid4

import pytest
from elasticsearch import NotFoundError

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, IndexDocument
from ai_workshop.labs.rag.indexing.elasticsearch import ElasticsearchSearchIndex
from ai_workshop.labs.rag.indexing.service import IndexingService
from ai_workshop.labs.rag.retrieval.domain import ActiveIndexAlias, ResolvedSearchScope
from ai_workshop.labs.rag.retrieval.elasticsearch import (
    ElasticsearchDenseRetriever,
    ElasticsearchSparseRetriever,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_bm25_and_knn_prefilters_exclude_private_personal_chunk() -> None:
    client = create_elasticsearch(Settings(secret_key="x" * 32))
    actor_id = uuid4()
    other_actor_id = uuid4()
    company_workspace_id = uuid4()
    private_workspace_id = uuid4()
    company_chunk_id = uuid4()
    private_chunk_id = uuid4()
    profile_id = uuid4()
    build_id = uuid4()
    projection_id = uuid4()
    company_asset_version_id = uuid4()
    service = IndexingService(
        ElasticsearchSearchIndex(client),
        index_prefix=f"rag-task8-{uuid4().hex}",
    )
    descriptor = IndexDescriptor(vector_dimension=4, similarity="cosine")
    concrete_index = descriptor.concrete_index_name(service.index_prefix, profile_id, build_id)
    active_alias = ActiveIndexAlias(descriptor, service.index_prefix, profile_id)
    alias = active_alias.name
    documents = (
        IndexDocument(
            chunk_id=company_chunk_id,
            projection_id=projection_id,
            asset_version_id=company_asset_version_id,
            workspace_id=company_workspace_id,
            folder_id=None,
            allowed_user_ids=(actor_id,),
            status="ready",
            title="Company synthetic policy",
            section_path=("Limits",),
            text="테스트전용손실한도 기준",
            evidence_units=(),
            embedding=(0.8, 0.6, 0.0, 0.0),
            index_build_id=build_id,
        ),
        IndexDocument(
            chunk_id=private_chunk_id,
            projection_id=projection_id,
            asset_version_id=uuid4(),
            workspace_id=private_workspace_id,
            folder_id=None,
            allowed_user_ids=(other_actor_id,),
            status="ready",
            title="Private personal synthetic policy",
            section_path=("Private",),
            text="테스트전용손실한도 테스트전용손실한도 테스트전용손실한도",
            evidence_units=(),
            embedding=(1.0, 0.0, 0.0, 0.0),
            index_build_id=build_id,
        ),
    )

    try:
        await service.index_projection(
            descriptor=descriptor,
            profile_id=profile_id,
            build_id=build_id,
            projection_id=projection_id,
            expected_chunk_count=2,
            documents=documents,
        )
        await client.indices.refresh(index=concrete_index)
        scope = ResolvedSearchScope(
            (company_workspace_id,),
            (),
            asset_version_ids=(company_asset_version_id,),
            index_build_ids=(build_id,),
        )

        sparse_hits = await ElasticsearchSparseRetriever(client).search_sparse(
            index_alias=active_alias,
            query="테스트전용손실한도",
            actor_id=actor_id,
            scope=scope,
            top_k=10,
        )
        dense_hits = await ElasticsearchDenseRetriever(client).search_dense(
            index_alias=active_alias,
            query_vector=(1.0, 0.0, 0.0, 0.0),
            actor_id=actor_id,
            scope=scope,
            top_k=10,
        )

        assert [hit.chunk_id for hit in sparse_hits] == [company_chunk_id]
        assert [hit.chunk_id for hit in dense_hits] == [company_chunk_id]
        assert private_chunk_id not in {hit.chunk_id for hit in (*sparse_hits, *dense_hits)}
    finally:
        try:
            await client.indices.delete_alias(index=concrete_index, name=alias)
        except NotFoundError:
            pass
        finally:
            await client.indices.delete(index=concrete_index, ignore_unavailable=True)
            await client.close()


async def _assert_stale_alias_target_cannot_displace_b(label: str) -> None:
    client = create_elasticsearch(Settings(secret_key="x" * 32))
    actor_id = uuid4()
    workspace_id = uuid4()
    profile_id = uuid4()
    b_asset_id, b_build_id, b_projection_id, b_chunk_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    stale_asset_id, stale_build_id, stale_projection_id, stale_chunk_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    service = IndexingService(
        ElasticsearchSearchIndex(client),
        index_prefix=f"rag-task14a-{label}-{uuid4().hex}",
    )
    descriptor = IndexDescriptor(vector_dimension=4, similarity="cosine")
    active_alias = ActiveIndexAlias(descriptor, service.index_prefix, profile_id)
    concrete_indices: list[str] = []
    try:
        for build_id, projection_id, document in (
            (
                b_build_id,
                b_projection_id,
                IndexDocument(
                    chunk_id=b_chunk_id,
                    projection_id=b_projection_id,
                    asset_version_id=b_asset_id,
                    workspace_id=workspace_id,
                    folder_id=None,
                    allowed_user_ids=(actor_id,),
                    status="ready",
                    title="Authoritative B",
                    section_path=("B",),
                    text="task14a-ranking-token",
                    evidence_units=(),
                    embedding=(0.8, 0.6, 0.0, 0.0),
                    index_build_id=b_build_id,
                ),
            ),
            (
                stale_build_id,
                stale_projection_id,
                IndexDocument(
                    chunk_id=stale_chunk_id,
                    projection_id=stale_projection_id,
                    asset_version_id=stale_asset_id,
                    workspace_id=workspace_id,
                    folder_id=None,
                    allowed_user_ids=(actor_id,),
                    status="ready",
                    title=f"Stale {label}",
                    section_path=("stale",),
                    text="task14a-ranking-token task14a-ranking-token "
                    "task14a-ranking-token task14a-ranking-token",
                    evidence_units=(),
                    embedding=(1.0, 0.0, 0.0, 0.0),
                    index_build_id=stale_build_id,
                ),
            ),
        ):
            result = await service.index_projection(
                descriptor=descriptor,
                profile_id=profile_id,
                build_id=build_id,
                projection_id=projection_id,
                expected_chunk_count=1,
                documents=(document,),
            )
            concrete_indices.append(result.index_name)
        await client.indices.refresh(index=active_alias.name)
        scope = ResolvedSearchScope(
            workspace_ids=(workspace_id,),
            folder_ids=(),
            asset_version_ids=(b_asset_id,),
            index_build_ids=(b_build_id,),
        )

        sparse_hits = await ElasticsearchSparseRetriever(client).search_sparse(
            index_alias=active_alias,
            query="task14a-ranking-token",
            actor_id=actor_id,
            scope=scope,
            top_k=1,
        )
        dense_hits = await ElasticsearchDenseRetriever(client).search_dense(
            index_alias=active_alias,
            query_vector=(1.0, 0.0, 0.0, 0.0),
            actor_id=actor_id,
            scope=scope,
            top_k=1,
        )

        assert [hit.chunk_id for hit in sparse_hits] == [b_chunk_id]
        assert [hit.chunk_id for hit in dense_hits] == [b_chunk_id]
        assert stale_chunk_id not in {
            hit.chunk_id for hit in (*sparse_hits, *dense_hits)
        }
    finally:
        if concrete_indices:
            await client.indices.delete(
                index=",".join(concrete_indices),
                ignore_unavailable=True,
            )
        await client.close()


@pytest.mark.asyncio
async def test_superseded_a1_cannot_displace_b_before_a2_indexing_finalizes() -> None:
    await _assert_stale_alias_target_cannot_displace_b("superseded-a1")


@pytest.mark.asyncio
async def test_db_inactive_a2_alias_target_cannot_displace_b_after_rollback() -> None:
    await _assert_stale_alias_target_cannot_displace_b("inactive-a2")
