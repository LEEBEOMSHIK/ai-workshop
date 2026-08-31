import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from elastic_transport import (
    ApiError,
    ApiResponseMeta,
    HttpHeaders,
    NodeConfig,
)
from elastic_transport import (
    ConnectionError as ElasticsearchConnectionError,
)
from elasticsearch import AsyncElasticsearch
from sqlalchemy import delete, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

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
from ai_workshop.labs.rag.ingestion.service import (
    RagIngestionService,
    RagIngestionWorkflow,
    ReadinessVerifierPort,
)
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
from ai_workshop.platform.jobs.domain import JobStatus
from ai_workshop.platform.jobs.models import JobRecord
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


class AsyncTestChunker:
    def __init__(self) -> None:
        self.delegate = StructuralChunker(WordTokenCounter())

    async def chunk(self, document, *, projection_id, indexing_profile_id, config):
        del indexing_profile_id
        return self.delegate.chunk(
            document, projection_id=projection_id, config=config
        )


def elasticsearch_api_error(status: int) -> ApiError:
    return ApiError(
        "synthetic Elasticsearch response",
        ApiResponseMeta(
            status=status,
            http_version="1.1",
            headers=HttpHeaders(),
            duration=0.0,
            node=NodeConfig("http", "localhost", 9200),
        ),
        {},
    )


class FailFirstActivationIndex:
    def __init__(
        self, delegate: ElasticsearchSearchIndex, *, failure_mode: str
    ) -> None:
        self.delegate = delegate
        self.failure_mode = failure_mode
        self.failed = False
        self.unexpected_error = ValueError("synthetic search-index programming error")

    async def create(self, descriptor: IndexDescriptor) -> None:
        await self.delegate.create(descriptor)

    async def bulk_upsert(
        self, index_name: str, documents: Sequence[IndexDocument]
    ) -> int:
        return await self.delegate.bulk_upsert(index_name, documents)

    async def count_projection(self, index_name: str, projection_id: UUID) -> int:
        return await self.delegate.count_projection(index_name, projection_id)

    async def replace_active_targets(
        self, alias: str, index_names: Sequence[str]
    ) -> bool:
        if not self.failed:
            self.failed = True
            if self.failure_mode == "acknowledgement":
                return False
            if self.failure_mode == "connection":
                raise ElasticsearchConnectionError("synthetic connection loss")
            if self.failure_mode == "api-503":
                raise elasticsearch_api_error(503)
            if self.failure_mode == "generic-value":
                raise self.unexpected_error
            raise AssertionError(f"Unexpected failure mode: {self.failure_mode}")
        return await self.delegate.replace_active_targets(alias, index_names)

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


class CorruptEmbeddingMetadataLifecycle(SqlAlchemyRagIngestionLifecycle):
    def __init__(self, settings: Settings, *, field: str, value: object) -> None:
        super().__init__(settings)
        self.field = field
        self.value = value

    async def complete_embedding(self, job_id: UUID, *, embedding_count: int):
        execution = await super().complete_embedding(
            job_id, embedding_count=embedding_count
        )
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions.begin() as session:
                ingestion = await session.scalar(
                    select(RagIngestionJobRecord)
                    .where(RagIngestionJobRecord.job_id == job_id)
                    .with_for_update()
                )
                assert ingestion is not None
                setattr(ingestion, self.field, self.value)
        finally:
            await engine.dispose()
        return execution


class ProjectionStatusTamperingVerifier:
    def __init__(
        self,
        settings: Settings,
        delegate: ProductionReadinessVerifier,
        status: ProjectionStatus,
    ) -> None:
        self.settings = settings
        self.delegate = delegate
        self.status = status

    async def verify(
        self, *, projection_id: UUID, indexing_profile_id: UUID
    ) -> ReadinessVerification:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions.begin() as session:
                projection = await session.get(RagProjectionRecord, projection_id)
                assert projection is not None
                projection.status = self.status
        finally:
            await engine.dispose()
        return await self.delegate.verify(
            projection_id=projection_id,
            indexing_profile_id=indexing_profile_id,
        )


class NeverSearchIndexFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise AssertionError("Elasticsearch factory must not be called for corrupt metadata.")


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
                        active_version_id=asset_id,
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
                        status="ready",
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
    verifier: ReadinessVerifierPort,
    *,
    lifecycle: SqlAlchemyRagIngestionLifecycle | None = None,
    indexing: ProductionIndexingStage | None = None,
) -> RagIngestionWorkflow:
    store = LocalObjectStore(settings.object_store_root)
    return RagIngestionWorkflow(
        lifecycle or SqlAlchemyRagIngestionLifecycle(settings),
        store,
        ParsingService(store, ParserRegistry((PlainTextParser(),))),
        AsyncTestChunker(),
        ProductionEmbeddingStage(settings, store, embedding_factory=fake_embedding),
        indexing or ProductionIndexingStage(settings, store),
        verifier,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("chunk_count", 2, "indexing_input_mismatch"),
        ("embedding_count", 2, "indexing_input_mismatch"),
        ("embedding_sha256", "0" * 64, "artifact_checksum_mismatch"),
    ],
)
async def test_corrupt_persisted_embedding_metadata_rejects_before_es_factory(
    field: str,
    value: object,
    error_code: str,
) -> None:
    settings = get_settings().model_copy(
        update={"elasticsearch_index_prefix": f"rag-task7-corrupt-{uuid4().hex}"}
    )
    owner_id, profile_id, job_ids, source_keys, inserted_model = await seed_two_jobs(
        settings
    )
    store = LocalObjectStore(settings.object_store_root)
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    artifact_keys: list[str] = []
    search_factory = NeverSearchIndexFactory()
    try:
        with pytest.raises(RagIngestionError) as exc_info:
            await workflow(
                settings,
                ProductionReadinessVerifier(settings),
                lifecycle=CorruptEmbeddingMetadataLifecycle(
                    settings, field=field, value=value
                ),
                indexing=ProductionIndexingStage(
                    settings,
                    store,
                    search_index_session=search_factory,
                ),
            ).run(job_ids[0])

        assert exc_info.value.code == error_code
        assert search_factory.calls == 0
    finally:
        async with sessions() as session:
            ingestions = list(
                await session.scalars(
                    select(RagIngestionJobRecord).where(
                        RagIngestionJobRecord.job_id.in_(job_ids)
                    )
                )
            )
            artifact_keys = [
                key
                for ingestion in ingestions
                for key in (
                    ingestion.parsed_object_key,
                    ingestion.chunk_object_key,
                    ingestion.embedding_object_key,
                )
                if key is not None
            ]
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


@pytest.mark.asyncio
async def test_production_readiness_rejects_a_non_current_asset_version() -> None:
    base = get_settings()
    prefix = f"rag-task14a-inactive-{uuid4().hex}"
    settings = base.model_copy(update={"elasticsearch_index_prefix": prefix})
    owner_id, profile_id, job_ids, source_keys, inserted_model = await seed_two_jobs(
        settings
    )
    store = LocalObjectStore(settings.object_store_root)
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    client = create_elasticsearch(settings)
    artifact_keys: list[str] = []
    index_names: list[str] = []
    try:
        async with sessions.begin() as session:
            ingestion = await session.scalar(
                select(RagIngestionJobRecord).where(
                    RagIngestionJobRecord.job_id == job_ids[0]
                )
            )
            assert ingestion is not None
            asset = await session.get(AssetVersionRecord, ingestion.asset_version_id)
            assert asset is not None
            document = await session.get(DocumentRecord, asset.document_id)
            assert document is not None
            document.active_version_id = None

        with pytest.raises(RagIngestionError) as exc_info:
            await workflow(settings, ProductionReadinessVerifier(settings)).run(
                job_ids[0]
            )

        assert exc_info.value.code == "index_source_inactive"
        assert exc_info.value.retryable is False
    finally:
        async with sessions() as session:
            ingestions = list(
                await session.scalars(
                    select(RagIngestionJobRecord).where(
                        RagIngestionJobRecord.job_id.in_(job_ids)
                    )
                )
            )
            index_names = list(
                await session.scalars(
                    select(RagIndexBuildRecord.index_name).where(
                        RagIndexBuildRecord.indexing_profile_id == profile_id,
                        RagIndexBuildRecord.index_name.is_not(None),
                    )
                )
            )
            artifact_keys = [
                key
                for ingestion in ingestions
                for key in (
                    ingestion.parsed_object_key,
                    ingestion.chunk_object_key,
                    ingestion.embedding_object_key,
                )
                if key is not None
            ]
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_status",
    [
        ProjectionStatus.PENDING,
        ProjectionStatus.PARSING,
        ProjectionStatus.CHUNKING,
        ProjectionStatus.EMBEDDING,
        ProjectionStatus.FAILED,
        ProjectionStatus.PARTIAL_READY,
    ],
)
async def test_production_readiness_rejects_invalid_projection_status_before_alias(
    invalid_status: ProjectionStatus,
) -> None:
    base = get_settings()
    prefix = f"rag-task14a-status-{uuid4().hex}"
    settings = base.model_copy(update={"elasticsearch_index_prefix": prefix})
    owner_id, profile_id, job_ids, source_keys, inserted_model = await seed_two_jobs(
        settings
    )
    store = LocalObjectStore(settings.object_store_root)
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    client = create_elasticsearch(settings)
    search_factory = NeverSearchIndexFactory()
    artifact_keys: list[str] = []
    index_names: list[str] = []
    try:
        verifier = ProjectionStatusTamperingVerifier(
            settings,
            ProductionReadinessVerifier(
                settings,
                search_index_session=search_factory,
            ),
            invalid_status,
        )
        with pytest.raises(RagIngestionError) as exc_info:
            await workflow(settings, verifier).run(job_ids[0])

        assert exc_info.value.code == "indexing_stage_conflict"
        assert exc_info.value.retryable is False
        assert search_factory.calls == 0
    finally:
        async with sessions() as session:
            ingestions = list(
                await session.scalars(
                    select(RagIngestionJobRecord).where(
                        RagIngestionJobRecord.job_id.in_(job_ids)
                    )
                )
            )
            index_names = list(
                await session.scalars(
                    select(RagIndexBuildRecord.index_name).where(
                        RagIndexBuildRecord.indexing_profile_id == profile_id,
                        RagIndexBuildRecord.index_name.is_not(None),
                    )
                )
            )
            artifact_keys = [
                key
                for ingestion in ingestions
                for key in (
                    ingestion.parsed_object_key,
                    ingestion.chunk_object_key,
                    ingestion.embedding_object_key,
                )
                if key is not None
            ]
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_mode", ["acknowledgement", "connection", "api-503", "generic-value"]
)
async def test_competing_builds_preserve_errors_and_retryable_paths_converge(
    failure_mode: str,
) -> None:
    base = get_settings()
    prefix = f"rag-task7-{uuid4().hex}"
    settings = base.model_copy(update={"elasticsearch_index_prefix": prefix})
    owner_id, profile_id, job_ids, source_keys, inserted_model = await seed_two_jobs(
        settings
    )
    client: AsyncElasticsearch = create_elasticsearch(settings)
    activation_index = FailFirstActivationIndex(
        ElasticsearchSearchIndex(client), failure_mode=failure_mode
    )

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
        if failure_mode == "generic-value":
            assert failures[0] is activation_index.unexpected_error
            return
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
        assert {build.id for build in active} == {build.id for build in builds}
        alias = IndexDescriptor(768, "cosine").active_alias(prefix, profile_id)
        assert await activation_index.active_targets(alias) == tuple(
            sorted(build.index_name for build in active if build.index_name is not None)
        )
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
        async with sessions() as session:
            cleanup_ingestions = list(
                await session.scalars(
                    select(RagIngestionJobRecord).where(
                        RagIngestionJobRecord.job_id.in_(job_ids)
                    )
                )
            )
            artifact_keys = list(
                dict.fromkeys(
                    [
                        *artifact_keys,
                        *[
                            key
                            for ingestion in cleanup_ingestions
                            for key in (
                                ingestion.parsed_object_key,
                                ingestion.chunk_object_key,
                                ingestion.embedding_object_key,
                            )
                            if key is not None
                        ],
                    ]
                )
            )
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


@pytest.mark.asyncio
async def test_replacement_version_retains_other_document_and_isolates_other_profile() -> None:
    base = get_settings()
    prefix = f"rag-task14a-replacement-{uuid4().hex}"
    settings = base.model_copy(update={"elasticsearch_index_prefix": prefix})
    owner_id, profile_id, job_ids, source_keys, inserted_model = await seed_two_jobs(
        settings
    )
    store = LocalObjectStore(settings.object_store_root)
    replacement_key = f"synthetic/{uuid4()}.txt"
    replacement = await store.put(
        replacement_key,
        bytes_source(b"Synthetic alpha replacement evidence."),
    )
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    client = create_elasticsearch(settings)
    artifact_keys: list[str] = []
    index_names: list[str] = []
    replacement_job_id: UUID | None = None
    replacement_asset_id = uuid4()
    other_profile_id = uuid4()
    other_projection_id = uuid4()
    other_build_id = uuid4()
    other_index_name = f"{prefix}-{other_profile_id}-{other_build_id}"
    try:
        async with sessions.begin() as session:
            first_ingestion = await session.scalar(
                select(RagIngestionJobRecord).where(
                    RagIngestionJobRecord.job_id == job_ids[0]
                )
            )
            assert first_ingestion is not None
            other_profile = ProfileRecord(
                id=other_profile_id,
                kind="indexing",
                name=f"synthetic-other-profile-{other_profile_id}",
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
            other_profile.bindings = [
                ProfileModelBindingRecord(role="embedding", model_id=E5_ID)
            ]
            session.add(other_profile)
            await session.flush()
            session.add(
                RagProjectionRecord(
                    id=other_projection_id,
                    asset_version_id=first_ingestion.asset_version_id,
                    indexing_profile_id=other_profile_id,
                    status=ProjectionStatus.READY,
                )
            )
            await session.flush()
            session.add(
                RagIndexBuildRecord(
                    id=other_build_id,
                    projection_id=other_projection_id,
                    indexing_profile_id=other_profile_id,
                    index_name=other_index_name,
                    expected_document_count=1,
                    indexed_document_count=1,
                    vector_dimension=768,
                    status="ready",
                    is_active=True,
                )
            )

        verifier = ProductionReadinessVerifier(settings)
        await workflow(settings, verifier).run(job_ids[0])
        await workflow(settings, verifier).run(job_ids[1])

        async with sessions.begin() as session:
            first_ingestion = await session.scalar(
                select(RagIngestionJobRecord).where(
                    RagIngestionJobRecord.job_id == job_ids[0]
                )
            )
            assert first_ingestion is not None
            first_asset = await session.get(
                AssetVersionRecord, first_ingestion.asset_version_id
            )
            assert first_asset is not None
            first_document = await session.get(DocumentRecord, first_asset.document_id)
            assert first_document is not None
            session.add(
                AssetVersionRecord(
                    id=replacement_asset_id,
                    document_id=first_document.id,
                    number=2,
                    object_key=replacement.key,
                    sha256=replacement.sha256,
                    media_type="text/plain",
                    size=replacement.size,
                    status="ready",
                )
            )
            first_document.active_version_id = replacement_asset_id
            await session.flush()
            replacement_job_id = await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(session)
            ).ensure_indexed(
                EnsureIndexedCommand(replacement_asset_id, profile_id, owner_id)
            )

        await workflow(settings, ProductionReadinessVerifier(settings)).run(
            replacement_job_id
        )

        async with sessions() as session:
            rows = (
                await session.execute(
                    select(
                        RagIndexBuildRecord,
                        RagProjectionRecord,
                        AssetVersionRecord,
                    )
                    .join(
                        RagProjectionRecord,
                        RagProjectionRecord.id == RagIndexBuildRecord.projection_id,
                    )
                    .join(
                        AssetVersionRecord,
                        AssetVersionRecord.id == RagProjectionRecord.asset_version_id,
                    )
                    .where(RagIndexBuildRecord.indexing_profile_id == profile_id)
                )
            ).all()
            active_rows = [row for row in rows if row[0].is_active]
            old_first_row = next(
                row for row in rows if row[2].id == first_ingestion.asset_version_id
            )
            index_names = [
                row[0].index_name for row in rows if row[0].index_name is not None
            ]
            ingestions = list(
                await session.scalars(
                    select(RagIngestionJobRecord).where(
                        RagIngestionJobRecord.job_id.in_((*job_ids, replacement_job_id))
                    )
                )
            )
            artifact_keys = [
                key
                for ingestion in ingestions
                for key in (
                    ingestion.parsed_object_key,
                    ingestion.chunk_object_key,
                    ingestion.embedding_object_key,
                )
                if key is not None
            ]
            isolated_build = await session.get(RagIndexBuildRecord, other_build_id)
        active_asset_ids = {row[2].id for row in active_rows}
        assert replacement_asset_id in active_asset_ids
        assert first_ingestion.asset_version_id not in active_asset_ids
        assert len(active_asset_ids) == 2
        assert old_first_row[0].is_active is False
        assert isolated_build is not None
        assert isolated_build.index_name == other_index_name
        assert isolated_build.status == "ready"
        assert isolated_build.is_active is True
        alias = IndexDescriptor(768, "cosine").active_alias(prefix, profile_id)
        active_names = tuple(
            sorted(
                row[0].index_name
                for row in active_rows
                if row[0].index_name is not None
            )
        )
        assert await ElasticsearchSearchIndex(client).active_targets(alias) == active_names
        await client.indices.refresh(index=alias)
        hits = await client.search(index=alias, query={"match_all": {}}, size=10)
        assert {
            UUID(hit["_source"]["asset_version_id"])
            for hit in hits["hits"]["hits"]
        } == active_asset_ids
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
        if not artifact_keys:
            async with sessions() as session:
                ingestions = list(
                    await session.scalars(
                        select(RagIngestionJobRecord).where(
                            RagIngestionJobRecord.job_id.in_(
                                (*job_ids, *((replacement_job_id,) if replacement_job_id else ()))
                            )
                        )
                    )
                )
                artifact_keys = [
                    key
                    for ingestion in ingestions
                    for key in (
                        ingestion.parsed_object_key,
                        ingestion.chunk_object_key,
                        ingestion.embedding_object_key,
                    )
                    if key is not None
                ]
        async with sessions.begin() as session:
            await session.execute(
                delete(WorkspaceRecord).where(WorkspaceRecord.created_by == owner_id)
            )
            await session.execute(
                delete(ProfileRecord).where(
                    ProfileRecord.id.in_((profile_id, other_profile_id))
                )
            )
            await session.execute(delete(UserRecord).where(UserRecord.id == owner_id))
            if inserted_model:
                await session.execute(
                    delete(ModelDefinitionRecord).where(
                        ModelDefinitionRecord.id == E5_ID
                    )
                )
        await engine.dispose()
        for key in (*source_keys, replacement_key, *artifact_keys):
            await store.delete(key)


@pytest.mark.asyncio
async def test_alias_success_then_database_commit_failure_reuses_build_and_converges() -> None:
    base = get_settings()
    prefix = f"rag-task7-commit-{uuid4().hex}"
    settings = base.model_copy(update={"elasticsearch_index_prefix": prefix})
    owner_id, profile_id, job_ids, source_keys, inserted_model = await seed_two_jobs(
        settings
    )
    client: AsyncElasticsearch = create_elasticsearch(settings)
    delegate = ElasticsearchSearchIndex(client)
    commit_failed = False
    listener_armed = False

    def fail_first_commit(_connection) -> None:
        nonlocal commit_failed
        if not commit_failed:
            commit_failed = True
            raise OperationalError(
                "synthetic readiness commit failure", {}, OSError("connection lost")
            )

    class ArmCommitFailureAfterAlias:
        async def create(self, descriptor: IndexDescriptor) -> None:
            await delegate.create(descriptor)

        async def bulk_upsert(
            self, index_name: str, documents: Sequence[IndexDocument]
        ) -> int:
            return await delegate.bulk_upsert(index_name, documents)

        async def count_projection(
            self, index_name: str, projection_id: UUID
        ) -> int:
            return await delegate.count_projection(index_name, projection_id)

        async def replace_active_targets(
            self, alias: str, index_names: Sequence[str]
        ) -> bool:
            nonlocal listener_armed
            acknowledged = await delegate.replace_active_targets(alias, index_names)
            if acknowledged and not listener_armed:
                event.listen(Engine, "commit", fail_first_commit)
                listener_armed = True
            return acknowledged

        async def active_targets(self, alias: str) -> tuple[str, ...]:
            return await delegate.active_targets(alias)

    armed_index = ArmCommitFailureAfterAlias()

    @asynccontextmanager
    async def activation_session() -> AsyncIterator[SearchIndexPort]:
        yield armed_index

    store = LocalObjectStore(settings.object_store_root)
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    artifact_keys: list[str] = []
    index_names: list[str] = []
    try:
        await workflow(settings, ProductionReadinessVerifier(settings)).run(job_ids[1])
        async with sessions() as session:
            prior_ingestion = await session.scalar(
                select(RagIngestionJobRecord).where(
                    RagIngestionJobRecord.job_id == job_ids[1]
                )
            )
            assert prior_ingestion is not None
            prior_build = await session.get(
                RagIndexBuildRecord, prior_ingestion.index_build_id
            )
        assert prior_build is not None
        assert prior_build.status == "ready"
        assert prior_build.is_active is True
        assert prior_build.index_name is not None

        with pytest.raises(OperationalError, match="readiness commit failure"):
            await workflow(
                settings,
                ProductionReadinessVerifier(
                    settings, search_index_session=activation_session
                ),
            ).run(job_ids[0])
        assert commit_failed is True
        if listener_armed:
            event.remove(Engine, "commit", fail_first_commit)
            listener_armed = False

        async with sessions() as session:
            ingestion = await session.scalar(
                select(RagIngestionJobRecord).where(
                    RagIngestionJobRecord.job_id == job_ids[0]
                )
            )
            assert ingestion is not None
            original_build_id = ingestion.index_build_id
            original_vector_key = ingestion.embedding_object_key
            original_vector_hash = ingestion.embedding_sha256
            build = await session.get(RagIndexBuildRecord, original_build_id)
            job = await session.get(JobRecord, job_ids[0])
            projection = await session.get(RagProjectionRecord, ingestion.projection_id)
        assert build is not None
        assert build.status == "prepared"
        assert build.is_active is False
        assert build.index_name is not None
        assert job is not None and job.status == JobStatus.RUNNING.value
        assert projection is not None
        assert projection.status == ProjectionStatus.INDEXING
        alias = IndexDescriptor(768, "cosine").active_alias(prefix, profile_id)
        assert await delegate.active_targets(alias) == tuple(
            sorted((prior_build.index_name, build.index_name))
        )

        await workflow(settings, ProductionReadinessVerifier(settings)).run(job_ids[0])

        async with sessions() as session:
            ingestion = await session.scalar(
                select(RagIngestionJobRecord).where(
                    RagIngestionJobRecord.job_id == job_ids[0]
                )
            )
            assert ingestion is not None
            reloaded_build = await session.get(
                RagIndexBuildRecord, ingestion.index_build_id
            )
            job = await session.get(JobRecord, job_ids[0])
            projection = await session.get(RagProjectionRecord, ingestion.projection_id)
            active_builds = list(
                await session.scalars(
                    select(RagIndexBuildRecord).where(
                        RagIndexBuildRecord.indexing_profile_id == profile_id,
                        RagIndexBuildRecord.is_active.is_(True),
                    )
                )
            )
            index_names = list(
                await session.scalars(
                    select(RagIndexBuildRecord.index_name).where(
                        RagIndexBuildRecord.indexing_profile_id == profile_id,
                        RagIndexBuildRecord.index_name.is_not(None),
                    )
                )
            )
            artifact_keys = [
                key
                for key in (
                    ingestion.parsed_object_key,
                    ingestion.chunk_object_key,
                    ingestion.embedding_object_key,
                )
                if key is not None
            ]
        assert ingestion.index_build_id == original_build_id
        assert ingestion.embedding_object_key == original_vector_key
        assert ingestion.embedding_sha256 == original_vector_hash
        assert reloaded_build is not None
        assert reloaded_build.status == "ready"
        assert reloaded_build.is_active is True
        assert {item.id for item in active_builds} == {
            prior_build.id,
            reloaded_build.id,
        }
        assert job is not None and job.status == JobStatus.SUCCEEDED.value
        assert projection is not None and projection.status == ProjectionStatus.READY
        assert await delegate.active_targets(alias) == tuple(
            sorted(
                item.index_name
                for item in active_builds
                if item.index_name is not None
            )
        )
    finally:
        if listener_armed:
            event.remove(Engine, "commit", fail_first_commit)
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
        async with sessions() as session:
            ingestions = list(
                await session.scalars(
                    select(RagIngestionJobRecord).where(
                        RagIngestionJobRecord.job_id.in_(job_ids)
                    )
                )
            )
            artifact_keys = list(
                dict.fromkeys(
                    [
                        *artifact_keys,
                        *[
                            key
                            for ingestion in ingestions
                            for key in (
                                ingestion.parsed_object_key,
                                ingestion.chunk_object_key,
                                ingestion.embedding_object_key,
                            )
                            if key is not None
                        ],
                    ]
                )
            )
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
