import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from elasticsearch import AsyncElasticsearch
from sqlalchemy import delete, select

from ai_workshop.config import Settings, get_settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.chunking import StructuralChunker
from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord, RagProjectionRecord
from ai_workshop.labs.rag.embeddings.contracts import EmbeddingModelConfig
from ai_workshop.labs.rag.embeddings.fake import DeterministicFakeEmbedding
from ai_workshop.labs.rag.indexing.contracts import (
    IndexDescriptor,
    IndexDocument,
    SearchIndexPort,
)
from ai_workshop.labs.rag.indexing.elasticsearch import ElasticsearchSearchIndex
from ai_workshop.labs.rag.ingestion.domain import (
    EnsureIndexedCommand,
    RagIngestionError,
    ReadinessVerification,
)
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.ingestion.repository import SqlAlchemyRagIngestionCommandRepository
from ai_workshop.labs.rag.ingestion.service import RagIngestionService, RagIngestionWorkflow
from ai_workshop.labs.rag.ingestion.stages import (
    ProductionEmbeddingStage,
    ProductionIndexingStage,
    ProductionReadinessVerifier,
)
from ai_workshop.labs.rag.ingestion.tasks import SqlAlchemyRagIngestionLifecycle
from ai_workshop.labs.rag.models.catalog import ModelCatalogImporter, load_model_catalog
from ai_workshop.labs.rag.models.models import (
    ModelDefinitionRecord,
    ProfileModelBindingRecord,
    ProfileRecord,
)
from ai_workshop.labs.rag.models.repository import SqlAlchemyModelRegistryRepository
from ai_workshop.labs.rag.parsing.plain_text import PlainTextParser
from ai_workshop.labs.rag.parsing.registry import ParserRegistry
from ai_workshop.labs.rag.parsing.service import ParsingService
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.shared.db import create_engine, create_session_factory

pytestmark = pytest.mark.integration

CATALOG_ROOT = Path(__file__).resolve().parents[6] / "model-profiles" / "rag" / "models"
E5_ID = UUID("00000000-0000-0000-0000-000000000101")


async def bytes_source(content: bytes) -> AsyncIterator[bytes]:
    yield content


class WordTokenCounter:
    def count(self, text: str) -> int:
        return len(text.split())


class FailFirstActivationIndex:
    def __init__(self, delegate: ElasticsearchSearchIndex) -> None:
        self.delegate = delegate
        self.failed = False

    async def create(self, descriptor: IndexDescriptor) -> None:
        await self.delegate.create(descriptor)

    async def bulk_upsert(
        self, index_name: str, documents: Sequence[IndexDocument]
    ) -> int:
        return await self.delegate.bulk_upsert(index_name, documents)

    async def count_projection(self, index_name: str, projection_id: UUID) -> int:
        return await self.delegate.count_projection(index_name, projection_id)

    async def activate(self, alias: str, index_name: str) -> bool:
        if not self.failed:
            self.failed = True
            return False
        return await self.delegate.activate(alias, index_name)

    async def active_targets(self, alias: str) -> tuple[str, ...]:
        return await self.delegate.active_targets(alias)


class CoordinatedVerifier:
    def __init__(self, delegate: ProductionReadinessVerifier) -> None:
        self.delegate = delegate
        self.barrier = asyncio.Barrier(2)

    async def verify(
        self, *, projection_id: UUID, indexing_profile_id: UUID
    ) -> ReadinessVerification:
        await self.barrier.wait()
        return await self.delegate.verify(
            projection_id=projection_id,
            indexing_profile_id=indexing_profile_id,
        )


def fake_embedding(
    config: EmbeddingModelConfig, _cache_folder: Path
) -> DeterministicFakeEmbedding:
    return DeterministicFakeEmbedding(
        dimension=config.dimension,
        query_prefix=config.query_prefix,
        document_prefix=config.document_prefix,
    )


async def seed_two_jobs(
    settings: Settings,
) -> tuple[UUID, UUID, tuple[UUID, UUID], tuple[str, str], bool]:
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    store = LocalObjectStore(settings.object_store_root)
    owner_id = uuid4()
    workspace_id = uuid4()
    profile_id = uuid4()
    object_keys = (f"synthetic/{uuid4()}.txt", f"synthetic/{uuid4()}.txt")
    stored = (
        await store.put(object_keys[0], bytes_source(b"Synthetic alpha local evidence.")),
        await store.put(object_keys[1], bytes_source(b"Synthetic beta local evidence.")),
    )
    try:
        async with sessions.begin() as session:
            e5_definition = next(
                model
                for model in load_model_catalog(CATALOG_ROOT)
                if model.id == E5_ID
            )
            catalog_result = await ModelCatalogImporter(
                SqlAlchemyModelRegistryRepository(session)
            ).import_definitions((e5_definition,))
            session.add(
                UserRecord(
                    id=owner_id,
                    display_name="Synthetic Embedding Owner",
                    email=f"embedding-{owner_id}@example.test",
                    normalized_email=f"embedding-{owner_id}@example.test",
                    password_hash="synthetic-password-hash",
                    role="owner",
                    is_active=True,
                )
            )
            await session.flush()
            session.add(
                WorkspaceRecord(
                    id=workspace_id,
                    name=f"Synthetic Embedding Workspace {workspace_id}",
                    kind="personal",
                    created_by=owner_id,
                    expires_at=None,
                )
            )
            await session.flush()
            session.add(
                WorkspaceMembershipRecord(
                    workspace_id=workspace_id,
                    user_id=owner_id,
                    role="owner",
                )
            )
            profile = ProfileRecord(
                id=profile_id,
                kind="indexing",
                name=f"synthetic-e5-{profile_id}",
                version=1,
                config={
                    "chunker": {
                        "name": "structure-aware",
                        "version": 2,
                        "target_tokens": 380,
                        "overlap_tokens": 60,
                    },
                    "embedding": {"batch_size": 8, "similarity": "cosine"},
                },
                evaluation_state="draft",
                is_default=False,
            )
            profile.bindings = [
                ProfileModelBindingRecord(role="embedding", model_id=E5_ID)
            ]
            session.add(profile)
            await session.flush()
            asset_ids: list[UUID] = []
            for position, item in enumerate(stored, 1):
                document_id = uuid4()
                asset_id = uuid4()
                asset_ids.append(asset_id)
                session.add(
                    DocumentRecord(
                        id=document_id,
                        workspace_id=workspace_id,
                        folder_id=None,
                        name=f"synthetic-{position}.txt",
                        active_version_id=None,
                    )
                )
                await session.flush()
                session.add(
                    AssetVersionRecord(
                        id=asset_id,
                        document_id=document_id,
                        number=1,
                        object_key=item.key,
                        sha256=item.sha256,
                        media_type="text/plain",
                        size=item.size,
                        status="stored",
                    )
                )
            await session.flush()
            job_ids = tuple(
                [
                    await RagIngestionService(
                        SqlAlchemyRagIngestionCommandRepository(session)
                    ).ensure_indexed(
                        EnsureIndexedCommand(asset_id, profile_id, owner_id)
                    )
                    for asset_id in asset_ids
                ]
            )
        assert len(job_ids) == 2
        return (
            owner_id,
            profile_id,
            (job_ids[0], job_ids[1]),
            object_keys,
            catalog_result.inserted == 1,
        )
    except Exception:
        for key in object_keys:
            await store.delete(key)
        raise
    finally:
        await engine.dispose()


def workflow(
    settings: Settings,
    verifier: CoordinatedVerifier | ProductionReadinessVerifier,
) -> RagIngestionWorkflow:
    store = LocalObjectStore(settings.object_store_root)
    return RagIngestionWorkflow(
        SqlAlchemyRagIngestionLifecycle(settings),
        store,
        ParsingService(store, ParserRegistry((PlainTextParser(),))),
        StructuralChunker(WordTokenCounter()),
        ProductionEmbeddingStage(settings, store, embedding_factory=fake_embedding),
        ProductionIndexingStage(settings, store),
        verifier,
    )


@pytest.mark.asyncio
async def test_competing_builds_and_activation_retry_converge_db_ready_with_real_alias() -> None:
    base = get_settings()
    prefix = f"rag-task7-{uuid4().hex}"
    settings = base.model_copy(update={"elasticsearch_index_prefix": prefix})
    owner_id, profile_id, job_ids, source_keys, inserted_model = await seed_two_jobs(
        settings
    )
    client: AsyncElasticsearch = create_elasticsearch(settings)
    activation_index = FailFirstActivationIndex(ElasticsearchSearchIndex(client))

    @asynccontextmanager
    async def activation_session() -> AsyncIterator[SearchIndexPort]:
        yield activation_index

    verifier = CoordinatedVerifier(
        ProductionReadinessVerifier(settings, search_index_session=activation_session)
    )
    first_workflow = workflow(settings, verifier)
    second_workflow = workflow(settings, verifier)
    store = LocalObjectStore(settings.object_store_root)
    artifact_keys: list[str] = []
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    index_names: list[str] = []
    try:
        outcomes = await asyncio.gather(
            first_workflow.run(job_ids[0]),
            second_workflow.run(job_ids[1]),
            return_exceptions=True,
        )
        failures = [item for item in outcomes if isinstance(item, Exception)]
        assert len(failures) == 1
        assert isinstance(failures[0], RagIngestionError)
        assert failures[0].retryable is True

        async with sessions() as session:
            ingestions = list(
                (
                    await session.scalars(
                        select(RagIngestionJobRecord).where(
                            RagIngestionJobRecord.job_id.in_(job_ids)
                        )
                    )
                ).all()
            )
            projections = {
                row.id: row
                for row in (
                    await session.scalars(
                        select(RagProjectionRecord).where(
                            RagProjectionRecord.id.in_(
                                tuple(item.projection_id for item in ingestions)
                            )
                        )
                    )
                ).all()
            }
            retry_ingestion = next(
                item
                for item in ingestions
                if projections[item.projection_id].status == ProjectionStatus.INDEXING
            )
            original_build_id = retry_ingestion.index_build_id
            retry_job_id = retry_ingestion.job_id

        await workflow(settings, ProductionReadinessVerifier(settings)).run(
            retry_job_id
        )

        async with sessions() as session:
            ingestions = list(
                (
                    await session.scalars(
                        select(RagIngestionJobRecord).where(
                            RagIngestionJobRecord.job_id.in_(job_ids)
                        )
                    )
                ).all()
            )
            builds = list(
                (
                    await session.scalars(
                        select(RagIndexBuildRecord).where(
                            RagIndexBuildRecord.indexing_profile_id == profile_id
                        )
                    )
                ).all()
            )
            reloaded_retry = await session.scalar(
                select(RagIngestionJobRecord).where(
                    RagIngestionJobRecord.job_id == retry_job_id
                )
            )
            projection_statuses = list(
                await session.scalars(
                    select(RagProjectionRecord.status).where(
                        RagProjectionRecord.id.in_(
                            tuple(item.projection_id for item in ingestions)
                        )
                    )
                )
            )
        assert all(
            item.embedding_object_key == f"rag/embeddings/{item.projection_id}.json"
            for item in ingestions
        )
        assert all(len(item.embedding_sha256 or "") == 64 for item in ingestions)
        assert all(item.embedding_count == item.chunk_count == 1 for item in ingestions)
        assert reloaded_retry is not None
        assert reloaded_retry.index_build_id == original_build_id
        assert projection_statuses == [ProjectionStatus.READY, ProjectionStatus.READY]
        active = [build for build in builds if build.is_active]
        assert len(active) == 1
        assert active[0].id == original_build_id
        alias = IndexDescriptor(768, "cosine").active_alias(prefix, profile_id)
        assert await activation_index.active_targets(alias) == (active[0].index_name,)
        index_names = [build.index_name for build in builds if build.index_name is not None]
        artifact_keys = [
            key
            for item in ingestions
            for key in (
                item.parsed_object_key,
                item.chunk_object_key,
                item.embedding_object_key,
            )
            if key is not None
        ]
    finally:
        if not index_names:
            async with sessions() as session:
                index_names = list(
                    await session.scalars(
                        select(RagIndexBuildRecord.index_name).where(
                            RagIndexBuildRecord.indexing_profile_id == profile_id,
                            RagIndexBuildRecord.index_name.is_not(None),
                        )
                    )
                )
        try:
            if index_names:
                await client.indices.delete(
                    index=",".join(index_names), ignore_unavailable=True
                )
        finally:
            await client.close()
        async with sessions.begin() as session:
            await session.execute(
                delete(WorkspaceRecord).where(WorkspaceRecord.created_by == owner_id)
            )
            await session.execute(delete(ProfileRecord).where(ProfileRecord.id == profile_id))
            await session.execute(delete(UserRecord).where(UserRecord.id == owner_id))
            if inserted_model:
                await session.execute(
                    delete(ModelDefinitionRecord).where(
                        ModelDefinitionRecord.id == E5_ID
                    )
                )
        await engine.dispose()
        for key in (*source_keys, *artifact_keys):
            await store.delete(key)
