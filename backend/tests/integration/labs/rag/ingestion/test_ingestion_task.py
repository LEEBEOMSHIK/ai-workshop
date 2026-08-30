import hashlib
from asyncio import gather, to_thread
from collections.abc import AsyncIterator
from threading import Barrier, Event, Lock
from uuid import UUID, uuid4

import pytest
from celery.exceptions import Retry
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from ai_workshop.config import get_settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.labs.rag.chunking import StructuralChunker
from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.labs.rag.documents.models import (
    RagProjectionRecord,
    RetrievalChunkRecord,
    StructuralElementRecord,
)
from ai_workshop.labs.rag.ingestion.domain import (
    EnsureIndexedCommand,
    ReadinessVerification,
)
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.ingestion.repository import SqlAlchemyRagIngestionCommandRepository
from ai_workshop.labs.rag.ingestion.serialization import (
    deserialize_chunking_result,
    deserialize_parsed_document,
)
from ai_workshop.labs.rag.ingestion.service import RagIngestionService, RagIngestionWorkflow
from ai_workshop.labs.rag.ingestion.tasks import SqlAlchemyRagIngestionLifecycle
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.labs.rag.parsing import plain_text
from ai_workshop.labs.rag.parsing.contracts import ParsingError
from ai_workshop.labs.rag.parsing.registry import ParserRegistry
from ai_workshop.labs.rag.parsing.service import ParsingService
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.jobs.domain import JobStatus, JobType
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from ai_workshop.shared.db import create_engine, create_session_factory
from ai_workshop.worker import RAG_INGESTION_TASK, create_celery

SYNTHETIC_CONTENT = b"Synthetic public fixture evidence."


async def bytes_source(content: bytes) -> AsyncIterator[bytes]:
    yield content


async def seed_command_dependencies() -> tuple[UUID, UUID, UUID, UUID, UUID]:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    requested_by = uuid4()
    duplicate_requester = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    asset_version_id = uuid4()
    indexing_profile_id = uuid4()
    object_key = f"synthetic/{asset_version_id}.txt"
    stored = await LocalObjectStore(settings.object_store_root).put(
        object_key, bytes_source(SYNTHETIC_CONTENT)
    )
    try:
        async with sessions.begin() as session:
            session.add_all(
                [
                    UserRecord(
                        id=user_id,
                        display_name=f"Synthetic Requester {position}",
                        email=f"synthetic-{user_id}@example.test",
                        normalized_email=f"synthetic-{user_id}@example.test",
                        password_hash="synthetic-password-hash",
                        role="owner",
                        is_active=True,
                    )
                    for position, user_id in enumerate((requested_by, duplicate_requester), 1)
                ]
            )
            await session.flush()
            session.add(
                WorkspaceRecord(
                    id=workspace_id,
                    name=f"Synthetic Workspace {workspace_id}",
                    kind="personal",
                    created_by=requested_by,
                    expires_at=None,
                )
            )
            await session.flush()
            session.add_all(
                [
                    DocumentRecord(
                        id=document_id,
                        workspace_id=workspace_id,
                        folder_id=None,
                        name="synthetic.txt",
                        active_version_id=None,
                    ),
                    ProfileRecord(
                        id=indexing_profile_id,
                        kind="indexing",
                        name=f"synthetic-indexing-{indexing_profile_id}",
                        version=1,
                        config={
                            "chunker": {
                                "name": "structure-aware",
                                "version": 2,
                                "target_tokens": 380,
                                "overlap_tokens": 60,
                            }
                        },
                        evaluation_state="draft",
                        is_default=False,
                    ),
                ]
            )
            await session.flush()
            session.add(
                AssetVersionRecord(
                    id=asset_version_id,
                    document_id=document_id,
                    number=1,
                    object_key=stored.key,
                    sha256=stored.sha256,
                    media_type="text/plain",
                    size=stored.size,
                    status="stored",
                )
            )
    finally:
        await engine.dispose()
    return (
        requested_by,
        duplicate_requester,
        workspace_id,
        asset_version_id,
        indexing_profile_id,
    )


async def delete_fixture(requested_by: UUID, duplicate_requester: UUID) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    artifact_keys: list[str] = []
    try:
        async with sessions.begin() as session:
            artifact_rows = await session.execute(
                select(
                    RagIngestionJobRecord.parsed_object_key,
                    RagIngestionJobRecord.chunk_object_key,
                ).where(RagIngestionJobRecord.requested_by == requested_by)
            )
            artifact_keys = [
                key
                for row in artifact_rows
                for key in row
                if key is not None
            ]
            await session.execute(
                delete(WorkspaceRecord).where(WorkspaceRecord.created_by == requested_by)
            )
            await session.execute(
                delete(UserRecord).where(UserRecord.id.in_((requested_by, duplicate_requester)))
            )
    finally:
        await engine.dispose()
    store = LocalObjectStore(settings.object_store_root)
    for key in artifact_keys:
        await store.delete(key)


class WordTokenCounter:
    def count(self, text: str) -> int:
        return len(text.split())


class ExplicitVerifiedStages:
    async def embed(self, *, projection_id: UUID, indexing_profile_id: UUID) -> int:
        return 1

    async def index(self, *, projection_id: UUID, indexing_profile_id: UUID) -> None:
        return None

    async def verify(
        self, *, projection_id: UUID, indexing_profile_id: UUID
    ) -> ReadinessVerification:
        return ReadinessVerification(1, 1, 1, 1, True)


class FailOnceParser:
    def __init__(self, delegate: ParsingService) -> None:
        self.delegate = delegate
        self.attempts = 0

    async def materialize_and_parse(self, asset_version, filename):
        self.attempts += 1
        if self.attempts == 1:
            raise OSError("synthetic transient parser failure")
        return await self.delegate.materialize_and_parse(asset_version, filename)


class ExplicitFailingParser:
    def __init__(self) -> None:
        self.calls = 0
        self.fallback_calls = 0

    async def materialize_and_parse(self, asset_version, filename):
        self.calls += 1
        raise ParsingError("synthetic_parser_failure", "The explicit parser failed.")


class BarrierParser:
    def __init__(self, delegate: ParsingService) -> None:
        self.delegate = delegate
        self.barrier = Barrier(2)
        self.lock = Lock()
        self.element_ids: list[UUID] = []

    async def materialize_and_parse(self, asset_version, filename):
        document = await self.delegate.materialize_and_parse(asset_version, filename)
        with self.lock:
            self.element_ids.append(document.elements[0].id)
        self.barrier.wait(timeout=10)
        return document


class PublicationCoordinator:
    def __init__(self) -> None:
        self.lock = Lock()
        self.parsed_put_calls = 0
        self.chunk_put_calls = 0
        self.first_transition_completed = Event()
        self.second_chunk_transition_completed = Event()


class OrderedPublicationStore:
    def __init__(self, delegate: LocalObjectStore, coordinator: PublicationCoordinator) -> None:
        self.delegate = delegate
        self.coordinator = coordinator

    async def put(self, key: str, source: AsyncIterator[bytes]):
        content = b"".join([part async for part in source])
        if key.startswith("rag/parsed/"):
            with self.coordinator.lock:
                call = self.coordinator.parsed_put_calls
                self.coordinator.parsed_put_calls += 1
            if call == 1:
                self.coordinator.first_transition_completed.wait(timeout=10)
        return await self.delegate.put(key, bytes_source(content))

    async def put_if_absent(self, key: str, source: AsyncIterator[bytes]):
        content = b"".join([part async for part in source])
        if key.startswith("rag/chunks/"):
            with self.coordinator.lock:
                call = self.coordinator.chunk_put_calls
                self.coordinator.chunk_put_calls += 1
            stored = await self.delegate.put_if_absent(key, bytes_source(content))
            if call == 0:
                self.coordinator.second_chunk_transition_completed.wait(timeout=10)
            return stored
        return await self.delegate.put_if_absent(key, bytes_source(content))

    def open(self, key: str) -> AsyncIterator[bytes]:
        return self.delegate.open(key)

    async def delete(self, key: str) -> None:
        await self.delegate.delete(key)


class SignalingLifecycle(SqlAlchemyRagIngestionLifecycle):
    def __init__(self, settings, coordinator: PublicationCoordinator) -> None:
        super().__init__(settings)
        self.coordinator = coordinator

    async def complete_parsing(self, job_id, document, artifact):
        execution = await super().complete_parsing(job_id, document, artifact)
        self.coordinator.first_transition_completed.set()
        return execution

    async def complete_chunking(self, job_id, result, artifact):
        execution = await super().complete_chunking(job_id, result, artifact)
        self.coordinator.second_chunk_transition_completed.set()
        return execution


class FailOnceOperationalLifecycle(SqlAlchemyRagIngestionLifecycle):
    def __init__(self, settings) -> None:
        super().__init__(settings)
        self.lock = Lock()
        self.failed = False

    async def complete_parsing(self, job_id, document, artifact):
        with self.lock:
            if not self.failed:
                self.failed = True
                raise OperationalError(
                    "synthetic parsing transition",
                    {},
                    OSError("synthetic transient database failure"),
                )
        return await super().complete_parsing(job_id, document, artifact)


def parsing_service(settings) -> ParsingService:
    return ParsingService(
        LocalObjectStore(settings.object_store_root),
        ParserRegistry((plain_text.PlainTextParser(),)),
    )


def workflow_factory(settings, parser, *, lifecycle=None, object_store=None):
    stages = ExplicitVerifiedStages()
    return RagIngestionWorkflow(
        lifecycle or SqlAlchemyRagIngestionLifecycle(settings),
        object_store or LocalObjectStore(settings.object_store_root),
        parser,
        StructuralChunker(WordTokenCounter()),
        stages,
        stages,
        stages,
    )


async def create_ingestion_job(
    requested_by: UUID, asset_version_id: UUID, indexing_profile_id: UUID
) -> UUID:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions.begin() as session:
            return await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(session)
            ).ensure_indexed(
                EnsureIndexedCommand(asset_version_id, indexing_profile_id, requested_by)
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_persists_the_complete_command_and_global_idempotency_key() -> None:
    (
        requested_by,
        duplicate_requester,
        workspace_id,
        asset_version_id,
        indexing_profile_id,
    ) = await seed_command_dependencies()
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions.begin() as session:
            service = RagIngestionService(SqlAlchemyRagIngestionCommandRepository(session))
            job_id = await service.ensure_indexed(
                EnsureIndexedCommand(asset_version_id, indexing_profile_id, requested_by)
            )
        async with sessions.begin() as session:
            duplicate_job_id = await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(session)
            ).ensure_indexed(
                EnsureIndexedCommand(asset_version_id, indexing_profile_id, duplicate_requester)
            )
        async with sessions() as session:
            ingestion = (
                await session.execute(
                    select(RagIngestionJobRecord).where(
                        RagIngestionJobRecord.job_id == job_id
                    )
                )
            ).scalar_one()
            job = await session.get(JobRecord, job_id)
            projection = await session.get(RagProjectionRecord, ingestion.projection_id)

        assert duplicate_job_id == job_id
        assert ingestion.asset_version_id == asset_version_id
        assert ingestion.indexing_profile_id == indexing_profile_id
        assert ingestion.requested_by == requested_by
        assert ingestion.parsed_object_key is None
        assert ingestion.parsed_sha256 is None
        assert ingestion.chunk_object_key is None
        assert ingestion.chunk_sha256 is None
        assert job is not None
        assert job.user_id == requested_by
        assert job.workspace_id == workspace_id
        assert job.type == JobType.RAG_INGESTION
        assert job.status == JobStatus.QUEUED
        assert job.idempotency_key == (
            f"{asset_version_id}:{indexing_profile_id}:rag_ingestion"
        )
        assert projection is not None
        assert projection.status == ProjectionStatus.PENDING
    finally:
        await engine.dispose()
        await LocalObjectStore(settings.object_store_root).delete(
            f"synthetic/{asset_version_id}.txt"
        )
        await delete_fixture(requested_by, duplicate_requester)


@pytest.mark.asyncio
async def test_eager_task_reloads_job_only_payload_and_reaches_ready_idempotently() -> None:
    (
        requested_by,
        duplicate_requester,
        _workspace_id,
        asset_version_id,
        indexing_profile_id,
    ) = await seed_command_dependencies()
    settings = get_settings()
    job_id = await create_ingestion_job(requested_by, asset_version_id, indexing_profile_id)
    app = create_celery(
        settings,
        rag_workflow_factory=lambda _settings: workflow_factory(
            settings, parsing_service(settings)
        ),
    )
    try:
        first = await to_thread(app.tasks[RAG_INGESTION_TASK].delay, str(job_id))
        duplicate = await to_thread(app.tasks[RAG_INGESTION_TASK].delay, str(job_id))
        assert first.get() is None
        assert duplicate.get() is None

        engine = create_engine(settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions() as session:
                ingestion = await session.get(RagIngestionJobRecord, job_id)
                job = await session.get(JobRecord, job_id)
                assert ingestion is not None
                projection = await session.get(
                    RagProjectionRecord, ingestion.projection_id
                )
            assert job is not None and job.status == JobStatus.SUCCEEDED
            assert job.stage == "ready"
            assert projection is not None
            assert projection.status == ProjectionStatus.READY
            assert ingestion.parsed_object_key == (
                f"rag/parsed/{ingestion.projection_id}.json"
            )
            assert ingestion.chunk_object_key == (
                f"rag/chunks/{ingestion.projection_id}.json"
            )
            assert len(ingestion.parsed_sha256 or "") == 64
            assert len(ingestion.chunk_sha256 or "") == 64
            assert ingestion.embedding_count == ingestion.chunk_count == 1
            assert ingestion.indexed_document_count == 1
            assert ingestion.index_alias_verified is True
        finally:
            await engine.dispose()
    finally:
        await LocalObjectStore(settings.object_store_root).delete(
            f"synthetic/{asset_version_id}.txt"
        )
        await delete_fixture(requested_by, duplicate_requester)


@pytest.mark.asyncio
async def test_concurrent_eager_duplicates_publish_one_authoritative_parsed_graph() -> None:
    (
        requested_by,
        duplicate_requester,
        _workspace_id,
        asset_version_id,
        indexing_profile_id,
    ) = await seed_command_dependencies()
    settings = get_settings()
    job_id = await create_ingestion_job(requested_by, asset_version_id, indexing_profile_id)
    parser = BarrierParser(parsing_service(settings))
    coordinator = PublicationCoordinator()
    store = OrderedPublicationStore(
        LocalObjectStore(settings.object_store_root), coordinator
    )
    app = create_celery(
        settings,
        rag_workflow_factory=lambda _settings: workflow_factory(
            settings,
            parser,
            lifecycle=SignalingLifecycle(settings, coordinator),
            object_store=store,
        ),
    )
    try:
        task = app.tasks[RAG_INGESTION_TASK]
        first, second = await gather(
            to_thread(task.apply, args=(str(job_id),), throw=True),
            to_thread(task.apply, args=(str(job_id),), throw=True),
        )
        assert first.successful() is True
        assert second.successful() is True
        assert len(set(parser.element_ids)) == 2

        engine = create_engine(settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions() as session:
                ingestion = await session.get(RagIngestionJobRecord, job_id)
                job = await session.get(JobRecord, job_id)
                assert ingestion is not None
                projection = await session.get(
                    RagProjectionRecord, ingestion.projection_id
                )
                persisted_element_id = await session.scalar(
                    select(StructuralElementRecord.id).where(
                        StructuralElementRecord.projection_id == ingestion.projection_id
                    )
                )
                persisted_chunk_id = await session.scalar(
                    select(RetrievalChunkRecord.id).where(
                        RetrievalChunkRecord.projection_id == ingestion.projection_id
                    )
                )
            assert ingestion.parsed_object_key == (
                f"rag/parsed/{ingestion.projection_id}.json"
            )
            parsed_bytes = b"".join(
                [part async for part in store.open(ingestion.parsed_object_key)]
            )
            authoritative = deserialize_parsed_document(parsed_bytes)
            assert hashlib.sha256(parsed_bytes).hexdigest() == ingestion.parsed_sha256
            assert persisted_element_id == authoritative.elements[0].id
            assert persisted_element_id in parser.element_ids
            assert ingestion.chunk_object_key == (
                f"rag/chunks/{ingestion.projection_id}.json"
            )
            chunk_bytes = b"".join(
                [part async for part in store.open(ingestion.chunk_object_key)]
            )
            authoritative_chunks = deserialize_chunking_result(chunk_bytes)
            assert hashlib.sha256(chunk_bytes).hexdigest() == ingestion.chunk_sha256
            assert persisted_chunk_id == authoritative_chunks.chunks[0].id
            assert job is not None and job.status == JobStatus.SUCCEEDED
            assert projection is not None and projection.status == ProjectionStatus.READY
        finally:
            await engine.dispose()
    finally:
        await LocalObjectStore(settings.object_store_root).delete(
            f"synthetic/{asset_version_id}.txt"
        )
        await delete_fixture(requested_by, duplicate_requester)


@pytest.mark.asyncio
async def test_db_operational_failure_after_publication_retries_without_terminalizing() -> None:
    (
        requested_by,
        duplicate_requester,
        _workspace_id,
        asset_version_id,
        indexing_profile_id,
    ) = await seed_command_dependencies()
    settings = get_settings()
    job_id = await create_ingestion_job(requested_by, asset_version_id, indexing_profile_id)
    parser = parsing_service(settings)
    lifecycle = FailOnceOperationalLifecycle(settings)
    store = LocalObjectStore(settings.object_store_root)
    app = create_celery(
        settings,
        rag_workflow_factory=lambda _settings: workflow_factory(
            settings, parser, lifecycle=lifecycle, object_store=store
        ),
    )
    try:
        with pytest.raises(Retry):
            await to_thread(app.tasks[RAG_INGESTION_TASK].delay, str(job_id))

        engine = create_engine(settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions() as session:
                before_retry = await session.get(RagIngestionJobRecord, job_id)
                running_job = await session.get(JobRecord, job_id)
                assert before_retry is not None
                projection = await session.get(
                    RagProjectionRecord, before_retry.projection_id
                )
            parsed_key = f"rag/parsed/{before_retry.projection_id}.json"
            published_bytes = b"".join([part async for part in store.open(parsed_key)])
            assert running_job is not None and running_job.status == JobStatus.RUNNING
            assert projection is not None and projection.status == ProjectionStatus.PARSING
            assert before_retry.parsed_object_key is None

            completed = await to_thread(
                app.tasks[RAG_INGESTION_TASK].delay, str(job_id)
            )
            assert completed.get() is None

            async with sessions() as session:
                after_retry = await session.get(RagIngestionJobRecord, job_id)
                completed_job = await session.get(JobRecord, job_id)
                assert after_retry is not None
                persisted_element_id = await session.scalar(
                    select(StructuralElementRecord.id).where(
                        StructuralElementRecord.projection_id == after_retry.projection_id
                    )
                )
            authoritative_bytes = b"".join(
                [part async for part in store.open(parsed_key)]
            )
            authoritative = deserialize_parsed_document(authoritative_bytes)
            assert authoritative_bytes == published_bytes
            assert after_retry.parsed_sha256 == hashlib.sha256(
                authoritative_bytes
            ).hexdigest()
            assert persisted_element_id == authoritative.elements[0].id
            assert completed_job is not None
            assert completed_job.status == JobStatus.SUCCEEDED
        finally:
            await engine.dispose()
    finally:
        await LocalObjectStore(settings.object_store_root).delete(
            f"synthetic/{asset_version_id}.txt"
        )
        await delete_fixture(requested_by, duplicate_requester)


@pytest.mark.asyncio
async def test_eager_task_retries_the_same_parser_after_a_transient_failure() -> None:
    (
        requested_by,
        duplicate_requester,
        _workspace_id,
        asset_version_id,
        indexing_profile_id,
    ) = await seed_command_dependencies()
    settings = get_settings()
    job_id = await create_ingestion_job(requested_by, asset_version_id, indexing_profile_id)
    parser = FailOnceParser(parsing_service(settings))
    app = create_celery(
        settings,
        rag_workflow_factory=lambda _settings: workflow_factory(settings, parser),
    )
    try:
        with pytest.raises(Retry):
            await to_thread(app.tasks[RAG_INGESTION_TASK].delay, str(job_id))
        result = await to_thread(app.tasks[RAG_INGESTION_TASK].delay, str(job_id))
        assert result.get() is None

        assert parser.attempts == 2
        engine = create_engine(settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions() as session:
                job = await session.get(JobRecord, job_id)
                ingestion = await session.get(RagIngestionJobRecord, job_id)
                assert ingestion is not None
                projection = await session.get(
                    RagProjectionRecord, ingestion.projection_id
                )
            assert job is not None and job.status == JobStatus.SUCCEEDED
            assert projection is not None and projection.status == ProjectionStatus.READY
        finally:
            await engine.dispose()
    finally:
        await LocalObjectStore(settings.object_store_root).delete(
            f"synthetic/{asset_version_id}.txt"
        )
        await delete_fixture(requested_by, duplicate_requester)


@pytest.mark.asyncio
async def test_parser_failure_is_terminal_without_automatic_substitution() -> None:
    (
        requested_by,
        duplicate_requester,
        _workspace_id,
        asset_version_id,
        indexing_profile_id,
    ) = await seed_command_dependencies()
    settings = get_settings()
    job_id = await create_ingestion_job(requested_by, asset_version_id, indexing_profile_id)
    parser = ExplicitFailingParser()
    app = create_celery(
        settings,
        rag_workflow_factory=lambda _settings: workflow_factory(settings, parser),
    )
    try:
        with pytest.raises(RuntimeError, match="synthetic_parser_failure"):
            await to_thread(app.tasks[RAG_INGESTION_TASK].delay, str(job_id))

        assert parser.calls == 1
        assert parser.fallback_calls == 0
        engine = create_engine(settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions() as session:
                job = await session.get(JobRecord, job_id)
                ingestion = await session.get(RagIngestionJobRecord, job_id)
                assert ingestion is not None
                projection = await session.get(
                    RagProjectionRecord, ingestion.projection_id
                )
            assert job is not None and job.status == JobStatus.FAILED
            assert job.error_code == "synthetic_parser_failure"
            assert projection is not None and projection.status == ProjectionStatus.FAILED
        finally:
            await engine.dispose()
    finally:
        await LocalObjectStore(settings.object_store_root).delete(
            f"synthetic/{asset_version_id}.txt"
        )
        await delete_fixture(requested_by, duplicate_requester)


@pytest.mark.asyncio
async def test_production_composition_fails_instead_of_pretending_ready_without_verifier() -> None:
    (
        requested_by,
        duplicate_requester,
        _workspace_id,
        asset_version_id,
        indexing_profile_id,
    ) = await seed_command_dependencies()
    settings = get_settings()
    job_id = await create_ingestion_job(requested_by, asset_version_id, indexing_profile_id)
    app = create_celery(settings)
    try:
        with pytest.raises(RuntimeError, match="embedding_stage_unavailable"):
            await to_thread(app.tasks[RAG_INGESTION_TASK].delay, str(job_id))

        engine = create_engine(settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions() as session:
                job = await session.get(JobRecord, job_id)
                ingestion = await session.get(RagIngestionJobRecord, job_id)
                assert ingestion is not None
                projection = await session.get(
                    RagProjectionRecord, ingestion.projection_id
                )
            assert job is not None and job.status == JobStatus.FAILED
            assert job.error_code == "embedding_stage_unavailable"
            assert projection is not None and projection.status == ProjectionStatus.FAILED
        finally:
            await engine.dispose()
    finally:
        await LocalObjectStore(settings.object_store_root).delete(
            f"synthetic/{asset_version_id}.txt"
        )
        await delete_fixture(requested_by, duplicate_requester)
