"""Real PG/ES movement contract, confined to the audited disposable namespace."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ai_workshop.config import get_settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagIndexBuildRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
    StructuralElementRecord,
)
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, IndexDocument
from ai_workshop.labs.rag.indexing.elasticsearch import ElasticsearchSearchIndex
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.retrieval.domain import ActiveIndexAlias, FrozenIndexTarget
from ai_workshop.labs.rag.retrieval.elasticsearch import (
    ElasticsearchDenseRetriever,
    ElasticsearchFrozenIndexInspector,
    ElasticsearchSparseRetriever,
)
from ai_workshop.labs.rag.retrieval.rrf import rrf_fuse
from ai_workshop.labs.rag.retrieval.scope import (
    SearchScopeResolver,
    SqlAlchemySearchScopeRepository,
)
from ai_workshop.labs.rag.search.repository import SqlAlchemySearchSourceResolver
from ai_workshop.labs.rag.search.viewer_repository import SqlAlchemyViewerResourceAccessRepository
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord, FolderRecord
from ai_workshop.platform.assets.movement import AssetMovementService
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.jobs.domain import JobStatus, JobType
from ai_workshop.platform.jobs.models import JobRecord
from tests.integration.labs.rag.retrieval.test_search_scope_repository import (
    _add_version,
    _seed_authorized_scope,
)
from tests.integration.rag_isolation_support import (
    create_isolated_elasticsearch,
    isolated_rag_resources,  # noqa: F401
)

pytestmark = pytest.mark.integration


async def _bytes(content: bytes):
    yield content


async def _immutable_rows(session: AsyncSession):
    return tuple(
        [
            tuple((await session.execute(select(model.__table__).order_by(model.id))).all())
            for model in (
                AssetVersionRecord,
                RagProjectionRecord,
                RagIndexBuildRecord,
                RetrievalChunkRecord,
                StructuralElementRecord,
                EvidenceUnitRecord,
            )
        ]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("move_kind", ["document", "folder"])
async def test_move_preserves_index_content_citations_and_current_scope(move_kind: str) -> None:
    settings = get_settings().model_copy(
        update={
            "elasticsearch_index_prefix": get_settings().elasticsearch_index_prefix + "-movement",
        }
    )
    # The helper validates the active namespace BEFORE the client can issue a request.
    client = create_isolated_elasticsearch(settings)
    engine = create_async_engine(settings.database_url)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as seed:
            actor, workspace, profile, processing = await _seed_authorized_scope(seed)
            folder_a, folder_b, child = uuid4(), uuid4(), uuid4()
            seed.add_all(
                [
                    FolderRecord(id=folder_a, workspace_id=workspace, parent_id=None, name="A"),
                    FolderRecord(id=folder_b, workspace_id=workspace, parent_id=None, name="B"),
                ]
            )
            await seed.flush()
            seed.add(
                FolderRecord(id=child, workspace_id=workspace, parent_id=folder_a, name="child")
            )
            await seed.flush()
            original_folder = folder_a if move_kind == "document" else child
            document = DocumentRecord(
                id=uuid4(),
                workspace_id=workspace,
                folder_id=original_folder,
                name="Synthetic movement source",
            )
            seed.add(document)
            await seed.flush()
            lifecycle = await _add_version(
                seed,
                document_id=document.id,
                number=1,
                profile_id=profile,
                processing_profile_id=processing,
                projection_status="ready",
                build_status="ready",
                build_active=True,
            )
            document.active_version_id = lifecycle.asset_version_id
            build = await seed.get(RagIndexBuildRecord, lifecycle.build_id)
            assert build is not None
            projection = build.projection_id
            chunk_id, element_id, evidence_id = uuid4(), uuid4(), uuid4()
            content = b"Synthetic movement evidence remains immutable."
            text = content.decode()
            store = LocalObjectStore(settings.object_store_root)
            version = await seed.get(AssetVersionRecord, lifecycle.asset_version_id)
            assert version is not None
            stored = await store.put(version.object_key, _bytes(content))
            version.sha256, version.size = stored.sha256, stored.size
            seed.add_all(
                [
                    StructuralElementRecord(
                        id=element_id,
                        projection_id=projection,
                        ordinal=0,
                        kind="paragraph",
                        text=text,
                        section_path=["Synthetic"],
                        char_start=0,
                        char_end=len(text),
                        parser_name="synthetic",
                        parser_version="1",
                    ),
                    RetrievalChunkRecord(
                        id=chunk_id,
                        projection_id=projection,
                        ordinal=0,
                        text=text,
                        section_path=["Synthetic"],
                    ),
                ]
            )
            await seed.flush()
            seed.add(
                EvidenceUnitRecord(
                    id=evidence_id,
                    projection_id=projection,
                    retrieval_chunk_id=chunk_id,
                    ordinal=0,
                    text=text,
                    element_id=element_id,
                    char_start=0,
                    char_end=len(text),
                )
            )
            job_id = uuid4()
            seed.add(
                JobRecord(
                    id=job_id,
                    user_id=actor,
                    workspace_id=workspace,
                    asset_version_id=version.id,
                    type=JobType.RAG_INGESTION,
                    idempotency_key=f"movement-{job_id}",
                    status=JobStatus.SUCCEEDED,
                    stage="ready",
                    attempt=1,
                )
            )
            await seed.flush()
            parsed = await store.put(f"parsed/{projection}.json", _bytes(b"{}"))
            seed.add(
                RagIngestionJobRecord(
                    job_id=job_id,
                    projection_id=projection,
                    asset_version_id=version.id,
                    document_processing_profile_id=processing,
                    indexing_profile_id=profile,
                    requested_by=actor,
                    parsed_object_key=parsed.key,
                    parsed_sha256=parsed.sha256,
                    index_build_id=build.id,
                    index_alias_verified=True,
                )
            )
            descriptor = IndexDescriptor(2, "cosine")
            alias = ActiveIndexAlias(
                descriptor, settings.elasticsearch_index_prefix, profile, processing
            )
            index_name = descriptor.concrete_index_name(
                settings.elasticsearch_index_prefix,
                profile,
                build.id,
                document_processing_profile_id=processing,
            )
            build.index_name = index_name
            await seed.commit()
            before_rows = await _immutable_rows(seed)
            index = ElasticsearchSearchIndex(client)
            await index.create(
                descriptor.for_index(
                    index_name,
                    indexing_profile_id=profile,
                    index_build_id=build.id,
                    projection_id=projection,
                )
            )
            evidence = EvidenceUnit(
                evidence_id,
                chunk_id,
                0,
                text,
                SourceLocation(element_id, None, 0, len(text), None),
                projection,
            )
            await index.bulk_upsert(
                index_name,
                (
                    IndexDocument(
                        chunk_id,
                        projection,
                        version.id,
                        workspace,
                        original_folder,
                        (actor,),
                        "ready",
                        document.name,
                        ("Synthetic",),
                        text,
                        (evidence,),
                        (1.0, 0.0),
                        build.id,
                        profile,
                    ),
                ),
            )
            await index.count_projection(index_name, projection)
            await index.replace_active_targets(alias.name, (index_name,))
            raw_before = await client.get(index=index_name, id=str(chunk_id))
            frozen_identity = await ElasticsearchFrozenIndexInspector(client).describe(index_name)
            frozen = FrozenIndexTarget(
                descriptor,
                settings.elasticsearch_index_prefix,
                profile,
                (frozen_identity,),
                (version.id,),
                processing,
            )

            async with AsyncSession(engine, expire_on_commit=False) as reader:
                # Keep a strong reference to a cached pre-move ORM Document.
                stale_document = await reader.get(DocumentRecord, document.id)
                assert stale_document is not None and stale_document.folder_id == original_folder
                resolver = SearchScopeResolver(SqlAlchemySearchScopeRepository(reader))

                async def scope(folder: UUID):
                    return await resolver.resolve(
                        actor_id=actor,
                        workspace_ids=(workspace,),
                        folder_ids=(folder,),
                        indexing_profile_id=profile,
                        document_processing_profile_id=processing,
                    )

                sparse, dense = (
                    ElasticsearchSparseRetriever(client),
                    ElasticsearchDenseRetriever(client),
                )

                async def search(target, resolved):
                    sparse_hits = await sparse.search_sparse(
                        index_alias=target,
                        query="movement",
                        actor_id=actor,
                        scope=resolved,
                        top_k=3,
                    )
                    dense_hits = await dense.search_dense(
                        index_alias=target,
                        query_vector=(1.0, 0.0),
                        actor_id=actor,
                        scope=resolved,
                        top_k=3,
                    )
                    assert tuple(hit.chunk_id for hit in sparse_hits) == tuple(
                        hit.chunk_id for hit in dense_hits
                    )
                    return rrf_fuse(sparse_hits, dense_hits, k=60)

                old_scope = await scope(original_folder)
                before_hits = await search(alias, old_scope)
                assert tuple(hit.chunk_id for hit in before_hits) == (chunk_id,)
                original_hit = before_hits[0]
                assert original_hit.chunk is not None
                cross_pair = replace(
                    original_hit, chunk=replace(original_hit.chunk, projection_id=uuid4())
                )
                assert (
                    await SqlAlchemySearchSourceResolver(reader).resolve(
                        actor_id=actor,
                        indexing_profile_id=profile,
                        hits=(cross_pair,),
                    )
                    == ()
                )
                await SqlAlchemySearchSourceResolver(reader).resolve(
                    actor_id=actor,
                    indexing_profile_id=profile,
                    hits=before_hits,
                )
                async with AsyncSession(engine) as writer:
                    movement = AssetMovementService(SqlAlchemyAssetRepository(writer), max_depth=10)
                    user = User(
                        actor,
                        "Synthetic",
                        "test@example.test",
                        "test@example.test",
                        "fixture-hash",
                        UserRole.OWNER,
                    )
                    if move_kind == "document":
                        await movement.move_document(
                            user=user,
                            workspace_id=workspace,
                            document_id=document.id,
                            destination_folder_id=folder_b,
                            expected_revision=1,
                        )
                    else:
                        await movement.move_folder(
                            user=user,
                            workspace_id=workspace,
                            folder_id=folder_a,
                            destination_folder_id=folder_b,
                            expected_revision=1,
                        )
                    await writer.commit()
                destination = folder_b if move_kind == "document" else child
                after_scope = await scope(destination)
                assert after_scope.authorized_documents == old_scope.authorized_documents
                if move_kind == "document":
                    assert await search(alias, await scope(folder_a)) == ()
                else:
                    assert (
                        await reader.execute(
                            select(FolderRecord.parent_id).where(FolderRecord.id == child)
                        )
                    ).scalar_one() == folder_a
                after_hits = await search(alias, after_scope)
                assert tuple(hit.chunk_id for hit in after_hits) == (chunk_id,)
                sources = await SqlAlchemySearchSourceResolver(reader).resolve(
                    actor_id=actor,
                    indexing_profile_id=profile,
                    hits=after_hits,
                )
                assert sources[0].chunk.folder_id == destination
                assert sources[0].document_id == document.id
                assert sources[0].chunk.evidence_units[0].id == evidence_id
                # Exact original/citation authorization survives movement by stable IDs.
                viewer = await SqlAlchemyViewerResourceAccessRepository(reader).resolve(
                    actor_id=actor,
                    asset_version_id=version.id,
                    projection_id=projection,
                )
                assert viewer is not None and viewer.document_id == document.id
                assert (
                    b"".join([part async for part in store.open(viewer.original_object_key)])
                    == content
                )
                assert viewer.original_sha256 == stored.sha256
                assert (
                    await SqlAlchemyViewerResourceAccessRepository(reader).resolve(
                        actor_id=uuid4(),
                        asset_version_id=version.id,
                        projection_id=projection,
                    )
                    is None
                )
                frozen_scope = replace(old_scope, active_only=False, authorized_documents=())
                assert tuple(hit.chunk_id for hit in await search(frozen, frozen_scope)) == (
                    chunk_id,
                )
                assert await search(frozen, replace(frozen_scope, folder_ids=(folder_b,))) == ()
                assert await _immutable_rows(reader) == before_rows
                raw_after = await client.get(index=index_name, id=str(chunk_id))
                assert raw_after["_source"] == raw_before["_source"]
                assert raw_after["_version"] == raw_before["_version"]
                assert raw_after["_source"]["folder_id"] == str(original_folder)
    finally:
        await client.close()
        await engine.dispose()
