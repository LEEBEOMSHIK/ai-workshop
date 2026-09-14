from __future__ import annotations

import asyncio
import json
import traceback
from collections.abc import Iterator
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ai_workshop.config import Settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.infrastructure.object_store.tracked import (
    ArtifactStoreError,
    TrackedLocalArtifactStore,
)
from ai_workshop.labs.rag.chunking.contracts import ChunkingResult
from ai_workshop.labs.rag.configurations.api import get_rag_configuration_service
from ai_workshop.labs.rag.documents.domain import (
    EvidenceUnit,
    ParsedDocument,
    RetrievalChunk,
    SourceLocation,
    StructuralElement,
)
from ai_workshop.labs.rag.documents.models import (
    RagProjectionRecord,
    RetrievalChunkRecord,
    StructuralElementRecord,
)
from ai_workshop.labs.rag.ingestion import stages as stage_module
from ai_workshop.labs.rag.ingestion import tasks as task_module
from ai_workshop.labs.rag.ingestion.artifact_contracts import ArtifactPublication, ArtifactRole
from ai_workshop.labs.rag.ingestion.artifact_models import (
    RagArtifactAttemptRecord,
    RagArtifactBundleRecord,
    RagArtifactSlotRecord,
)
from ai_workshop.labs.rag.ingestion.artifact_repository import SqlAlchemyRagArtifactRepository
from ai_workshop.labs.rag.ingestion.artifact_service import (
    RagArtifactPublisher,
    prepare_artifact_admission,
)
from ai_workshop.labs.rag.ingestion.domain import (
    EnsureIndexedCommand,
    RagIngestionError,
    ReadinessVerification,
)
from ai_workshop.labs.rag.ingestion.models import RagIngestionDispatchRecord, RagIngestionJobRecord
from ai_workshop.labs.rag.ingestion.repository import SqlAlchemyRagIngestionCommandRepository
from ai_workshop.labs.rag.ingestion.serialization import serialize_parsed_document
from ai_workshop.labs.rag.ingestion.service import RagIngestionService, RagIngestionWorkflow
from ai_workshop.labs.rag.ingestion.stages import ProductionEmbeddingStage
from ai_workshop.labs.rag.ingestion.tasks import SqlAlchemyRagIngestionLifecycle
from ai_workshop.labs.rag.models.models import (
    ModelDefinitionRecord,
    ProfileModelBindingRecord,
    ProfileRecord,
)
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.worker import RAG_INGESTION_TASK, create_celery
from tests.integration.labs.rag.ingestion.test_artifact_repository import (
    _BINDING,
    _isolated_database_at,
    _seed_official_ingestion,
)
from tests.integration.publishing_support import IsolatedPublishingDatabase
from tests.unit.labs.rag.ingestion.test_embedding_stage import RecordingEmbedding, model_config


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[IsolatedPublishingDatabase]:
    with _isolated_database_at("head") as database:
        yield database


@pytest.fixture(autouse=True)
def ensure_legacy_document_processing_profile(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    """Never invoke the parent fixture against the application database."""
    assert migrated_database.name.startswith("ai_workshop_publishing_")


def _settings(
    database: IsolatedPublishingDatabase, root: Path, *, binding: bool = True
) -> Settings:
    return Settings(
        database_url=database.database_url,
        object_store_root=root,
        secret_key="artifact-lifecycle-synthetic-secret",
        rag_artifact_store_id=_BINDING.store_id if binding else None,
        rag_artifact_store_binding_id=_BINDING.binding_id if binding else None,
    )


def _marker(root: Path) -> None:
    (root / ".ai-workshop-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "store_id": _BINDING.store_id,
                "binding_id": str(_BINDING.binding_id),
            }
        ),
        encoding="utf-8",
    )


async def _command(sessions: async_sessionmaker) -> EnsureIndexedCommand:
    async with sessions.begin() as session:
        seed = await _seed_official_ingestion(session, label="lifecycle")
        await session.execute(
            update(AssetVersionRecord)
            .where(AssetVersionRecord.id == seed.source.asset_version_id)
            .values(status="ready")
        )
        await session.execute(
            update(DocumentRecord)
            .where(DocumentRecord.id == seed.source.document_id)
            .values(active_version_id=seed.source.asset_version_id)
        )
        profile_id = uuid4()
        model_id = uuid4()
        config = asdict(model_config())
        config.pop("batch_size")
        session.add(
            ModelDefinitionRecord(
                id=model_id,
                kind="embedding",
                name=f"artifact-model-{model_id}",
                version=1,
                config=config,
            )
        )
        session.add(
            ProfileRecord(
                id=profile_id,
                kind="indexing",
                name=f"artifact-lifecycle-{profile_id}",
                version=1,
                config={
                    "chunker": {"name": "structure-aware"},
                    "embedding": {"batch_size": 2, "similarity": "cosine"},
                },
                evaluation_state="draft",
                is_default=False,
            )
        )
        await session.flush()
        session.add(
            ProfileModelBindingRecord(profile_id=profile_id, role="embedding", model_id=model_id)
        )
        return EnsureIndexedCommand(seed.source.asset_version_id, profile_id, seed.owner_id)


def _parsed(asset_version_id) -> ParsedDocument:
    element_id = uuid4()
    return ParsedDocument(
        asset_version_id,
        "synthetic",
        "1",
        (
            StructuralElement(
                element_id,
                0,
                "paragraph",
                "Synthetic evidence.",
                (),
                SourceLocation(element_id, page=None, char_start=0, char_end=19, bbox=None),
                "synthetic",
                "1",
                None,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_official_ensure_registers_before_dispatch_and_preserves_existing_without_binding(
    migrated_database: IsolatedPublishingDatabase,
    tmp_path: Path,
) -> None:
    settings = _settings(migrated_database, tmp_path)
    _marker(tmp_path)
    admission = prepare_artifact_admission(settings)
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        command = await _command(sessions)
        async with sessions.begin() as session:
            job_id = await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(
                    session,
                    artifact_admission=admission,
                )
            ).ensure_indexed(command)
        async with sessions() as session:
            bundle = await session.scalar(
                select(RagArtifactBundleRecord).where(RagArtifactBundleRecord.job_id == job_id)
            )
            assert bundle is not None and bundle.revision == 1
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(RagArtifactSlotRecord)
                    .where(RagArtifactSlotRecord.bundle_id == bundle.id)
                )
                == 3
            )
            assert (
                await session.scalar(
                    select(AssetSourceRelationRecord.resource_revision).where(
                        AssetSourceRelationRecord.resource_id == bundle.id
                    )
                )
                == 1
            )
            assert await session.get(RagIngestionDispatchRecord, job_id) is not None
        assert list(tmp_path.rglob("*.json")) == [tmp_path / ".ai-workshop-store.json"]
        async with sessions.begin() as session:
            assert (
                await RagIngestionService(
                    SqlAlchemyRagIngestionCommandRepository(session)
                ).ensure_indexed(command)
                == job_id
            )
        other = await _command(sessions)
        with pytest.raises(RagIngestionError, match="artifact_binding_missing"):
            async with sessions.begin() as session:
                await RagIngestionService(
                    SqlAlchemyRagIngestionCommandRepository(session)
                ).ensure_indexed(other)
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(RagProjectionRecord.id).where(
                        RagProjectionRecord.indexing_profile_id == other.indexing_profile_id
                    )
                )
                is None
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["reserve", "finalize", "commit"])
async def test_artifact_database_errors_are_safe_and_roll_back_caller_transaction(
    migrated_database: IsolatedPublishingDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    settings = _settings(migrated_database, tmp_path)
    _marker(tmp_path)
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    sentinels = ("SYNTHETIC_PRIVATE_ARTIFACT_KEY", "SYNTHETIC_PRIVATE_ARTIFACT_HASH")

    def database_failure():
        return OperationalError(
            "update artifact",
            {"key": sentinels[0], "hash": sentinels[1]},
            RuntimeError("synthetic"),
        )

    try:
        command = await _command(sessions)
        async with sessions.begin() as session:
            job_id = await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(
                    session,
                    artifact_admission=prepare_artifact_admission(settings),
                )
            ).ensure_indexed(command)
        lifecycle = SqlAlchemyRagIngestionLifecycle(settings)
        await lifecycle.begin(job_id)
        document = _parsed(command.asset_version_id)
        publisher = RagArtifactPublisher(settings)
        original = getattr(
            SqlAlchemyRagArtifactRepository,
            "reserve_attempt" if boundary == "reserve" else "finalize",
        )

        async def fail_after_mutation(repository, *args, **kwargs):
            await original(repository, *args, **kwargs)
            raise database_failure()

        def fail_commit(session):
            if any(
                isinstance(row, RagIngestionJobRecord)
                and row.job_id == job_id
                and row.parsed_object_key is not None
                for row in session.identity_map.values()
            ):
                raise database_failure()

        if boundary == "reserve":
            monkeypatch.setattr(
                SqlAlchemyRagArtifactRepository, "reserve_attempt", fail_after_mutation
            )
        publication = None
        if boundary != "reserve":
            publication = await publisher.publish(
                job_id, ArtifactRole.PARSED, serialize_parsed_document(document)
            )
            assert publication is not None
            if boundary == "finalize":
                monkeypatch.setattr(
                    SqlAlchemyRagArtifactRepository, "finalize", fail_after_mutation
                )
            else:
                event.listen(Session, "before_commit", fail_commit)
        try:
            with pytest.raises(RagIngestionError) as raised:
                if publication is None:
                    await publisher.publish(
                        job_id, ArtifactRole.PARSED, serialize_parsed_document(document)
                    )
                else:
                    await lifecycle.complete_parsing(job_id, document, publication[0])
        finally:
            if boundary == "commit":
                event.remove(Session, "before_commit", fail_commit)
        assert raised.value.code == "database_transient" and raised.value.retryable
        formatted = "".join(traceback.format_exception(raised.value))
        assert all(sentinel not in formatted for sentinel in sentinels)
        async with sessions() as observer:
            ingestion = await observer.get(RagIngestionJobRecord, job_id)
            assert ingestion.parsed_object_key is None and ingestion.parsed_sha256 is None
            assert (
                await observer.scalar(select(JobRecord.status).where(JobRecord.id == job_id))
                == "running"
            )
            slot = await observer.scalar(
                select(RagArtifactSlotRecord)
                .join(RagArtifactBundleRecord)
                .where(
                    RagArtifactBundleRecord.job_id == job_id, RagArtifactSlotRecord.role == "parsed"
                )
            )
            assert slot.state == "reserved"
            attempts = list(
                (
                    await observer.scalars(
                        select(RagArtifactAttemptRecord).where(
                            RagArtifactAttemptRecord.slot_id == slot.id
                        )
                    )
                ).all()
            )
            assert len(attempts) == (0 if boundary == "reserve" else 1)
            if attempts:
                assert attempts[0].state == "open"
        if publication is not None:
            assert (tmp_path / publication[0].key).is_file()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_parsing_database_failure_retains_canonical_and_open_attempt(
    migrated_database: IsolatedPublishingDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(migrated_database, tmp_path)
    _marker(tmp_path)
    admission = prepare_artifact_admission(settings)
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        command = await _command(sessions)
        async with sessions.begin() as session:
            job_id = await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(
                    session,
                    artifact_admission=admission,
                )
            ).ensure_indexed(command)
        lifecycle = SqlAlchemyRagIngestionLifecycle(settings)
        execution = await lifecycle.begin(job_id)
        document = _parsed(command.asset_version_id)
        publisher = RagArtifactPublisher(settings)
        published = await publisher.publish(
            job_id, ArtifactRole.PARSED, serialize_parsed_document(document)
        )
        assert published is not None
        reference, _content = published
        assert isinstance(reference.tracking, ArtifactPublication)
        publication = reference.tracking
        for invalid_claim in (
            replace(publication.claim, attempt_id=uuid4()),
            replace(publication.claim, binding=replace(_BINDING, binding_id=uuid4())),
        ):
            with pytest.raises(RagIngestionError):
                await lifecycle.complete_parsing(
                    job_id,
                    document,
                    replace(
                        reference,
                        tracking=replace(publication, claim=invalid_claim),
                    ),
                )
        with pytest.raises(RagIngestionError, match="artifact_tracking_required"):
            await lifecycle.complete_parsing(job_id, document, replace(reference, tracking=None))
        original_execution = lifecycle._execution

        def fail_after_mutations(rows):
            raise RuntimeError("synthetic caller rollback")

        monkeypatch.setattr(lifecycle, "_execution", fail_after_mutations)
        with pytest.raises(RuntimeError, match="synthetic caller rollback"):
            await lifecycle.complete_parsing(job_id, document, reference)
        assert (tmp_path / reference.key).is_file()
        async with sessions() as session:
            slot = await session.scalar(
                select(RagArtifactSlotRecord)
                .join(RagArtifactBundleRecord)
                .where(
                    RagArtifactBundleRecord.job_id == job_id,
                    RagArtifactSlotRecord.role == "parsed",
                )
            )
            assert slot is not None and slot.state == "reserved"
            assert slot.published_sha256 is None
            assert (
                await session.scalar(
                    select(RagArtifactAttemptRecord.state).where(
                        RagArtifactAttemptRecord.slot_id == slot.id
                    )
                )
                == "open"
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(StructuralElementRecord)
                    .where(StructuralElementRecord.projection_id == execution.projection_id)
                )
                == 0
            )
        with pytest.raises(RagIngestionError, match="artifact_attempt_busy"):
            await publisher.publish(
                job_id, ArtifactRole.PARSED, serialize_parsed_document(document)
            )
        monkeypatch.setattr(lifecycle, "_execution", original_execution)
        completed = await lifecycle.complete_parsing(job_id, document, reference)
        assert completed.parsed_artifact is not None
        replay = await publisher.publish(
            job_id,
            ArtifactRole.PARSED,
            serialize_parsed_document(_parsed(command.asset_version_id)),
        )
        assert replay is not None
        assert await publisher.read(
            job_id, ArtifactRole.PARSED, replay[0]
        ) == serialize_parsed_document(document)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_missing_binding_preserves_configuration_reads_and_untracked_legacy_replay(
    migrated_database: IsolatedPublishingDatabase,
    tmp_path: Path,
) -> None:
    settings = _settings(migrated_database, tmp_path, binding=False)
    admission = prepare_artifact_admission(settings)
    assert admission.binding is None
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        command = await _command(sessions)
        async with sessions.begin() as session:
            user = User.create_owner(
                display_name="Synthetic owner", email="read@example.test", password_hash="synthetic"
            )
            service = get_rag_configuration_service(session, settings, user)
            configurations = await service.list(user.id)
            assert configurations and all(item.is_system for item in configurations)
            legacy = await session.scalar(
                select(RagIngestionJobRecord).where(
                    RagIngestionJobRecord.asset_version_id == command.asset_version_id,
                )
            )
            assert legacy is not None
            legacy_command = replace(command, indexing_profile_id=legacy.indexing_profile_id)
            assert (
                await RagIngestionService(
                    SqlAlchemyRagIngestionCommandRepository(
                        session,
                        artifact_admission=admission,
                    )
                ).ensure_indexed(legacy_command)
                == legacy.job_id
            )
            legacy_id = legacy.job_id
        publisher = RagArtifactPublisher(settings)
        assert await publisher.publish(legacy_id, ArtifactRole.PARSED, b"{}") is None
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(RagArtifactBundleRecord.id).where(
                        RagArtifactBundleRecord.job_id == legacy_id,
                    )
                )
                is None
            )
        assert list(tmp_path.iterdir()) == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_missing_marker_blocks_new_registration_and_tracked_publication_without_fallback(
    migrated_database: IsolatedPublishingDatabase,
    tmp_path: Path,
) -> None:
    settings = _settings(migrated_database, tmp_path)
    unavailable = prepare_artifact_admission(settings)
    assert unavailable.binding is None
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        command = await _command(sessions)
        with pytest.raises(RagIngestionError, match="artifact_binding_missing"):
            async with sessions.begin() as session:
                await RagIngestionService(
                    SqlAlchemyRagIngestionCommandRepository(
                        session,
                        artifact_admission=unavailable,
                    )
                ).ensure_indexed(command)
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(RagProjectionRecord.id).where(
                        RagProjectionRecord.indexing_profile_id == command.indexing_profile_id,
                    )
                )
                is None
            )
        _marker(tmp_path)
        admission = prepare_artifact_admission(settings)
        async with sessions.begin() as session:
            job_id = await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(
                    session,
                    artifact_admission=admission,
                )
            ).ensure_indexed(command)
        await SqlAlchemyRagIngestionLifecycle(settings).begin(job_id)
        (tmp_path / ".ai-workshop-store.json").unlink()
        with pytest.raises(RagIngestionError, match="artifact_binding_missing"):
            await RagArtifactPublisher(settings).publish(job_id, ArtifactRole.PARSED, b"{}")
        assert list(tmp_path.iterdir()) == []
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(RagArtifactAttemptRecord)
                    .join(
                        RagArtifactSlotRecord,
                    )
                    .join(RagArtifactBundleRecord)
                    .where(RagArtifactBundleRecord.job_id == job_id)
                )
                == 0
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_role",
    [
        None,
        ArtifactRole.CHUNKS,
        ArtifactRole.EMBEDDINGS,
        "failed_after_embedding_publication",
        "completed_embedding_replay",
        "competing_delivery_exhausted",
    ],
)
async def test_workflow_tracks_all_three_roles_without_locks_during_publication(
    migrated_database: IsolatedPublishingDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_role: ArtifactRole | str | None,
) -> None:
    settings = _settings(migrated_database, tmp_path)
    _marker(tmp_path)
    admission = prepare_artifact_admission(settings)
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        command = await _command(sessions)
        async with sessions.begin() as session:
            job_id = await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(
                    session,
                    artifact_admission=admission,
                )
            ).ensure_indexed(command)
        original_publish = TrackedLocalArtifactStore.publish
        roles = []

        async def checked_publish(store, claim, content):
            async with sessions.begin() as observer:
                # NOWAIT makes a held writer lock a deterministic failure.
                for model, identity in (
                    (RagIngestionJobRecord, claim.job_id),
                    (JobRecord, claim.job_id),
                    (RagProjectionRecord, claim.projection_id),
                    (AssetVersionRecord, command.asset_version_id),
                    (RagArtifactBundleRecord, claim.bundle_id),
                    (RagArtifactSlotRecord, claim.slot_id),
                    (RagArtifactAttemptRecord, claim.attempt_id),
                ):
                    column = model.job_id if model is RagIngestionJobRecord else model.id
                    assert (
                        await observer.scalar(
                            select(model).where(column == identity).with_for_update(nowait=True)
                        )
                        is not None
                    )
                attempt = await observer.get(RagArtifactAttemptRecord, claim.attempt_id)
                slot = await observer.get(RagArtifactSlotRecord, claim.slot_id)
                assert attempt.state == "open" and slot.state == "reserved"
            if failure_role == "competing_delivery_exhausted" and claim.role == ArtifactRole.PARSED:

                class CompetingWorkflow:
                    async def run(self, persisted_job):
                        await SqlAlchemyRagIngestionLifecycle(settings).begin(persisted_job)
                        return await RagArtifactPublisher(settings).publish(
                            persisted_job, claim.role, content
                        )

                    async def fail(self, persisted_job, **kwargs):
                        await SqlAlchemyRagIngestionLifecycle(settings).fail(
                            persisted_job, **kwargs
                        )

                app = create_celery(
                    settings.model_copy(update={"environment": "test"}),
                    rag_workflow_factory=lambda _: CompetingWorkflow(),
                )
                task = app.tasks[RAG_INGESTION_TASK]
                delivery_error = None
                try:
                    await asyncio.to_thread(
                        task.apply,
                        args=(str(job_id),),
                        retries=task.max_retries,
                        throw=True,
                    )
                except RuntimeError as exc:
                    delivery_error = exc
                async with sessions() as observer:
                    assert (
                        await observer.scalar(
                            select(JobRecord.status).where(JobRecord.id == job_id)
                        )
                        == "running"
                    )
                    assert (
                        await observer.scalar(
                            select(RagProjectionRecord.status).where(
                                RagProjectionRecord.id == claim.projection_id
                            )
                        )
                        == "parsing"
                    )
                assert delivery_error is None
            roles.append(claim.role)
            result = await original_publish(store, claim, content)
            if (
                failure_role == "failed_after_embedding_publication"
                and claim.role == ArtifactRole.EMBEDDINGS
            ):
                await SqlAlchemyRagIngestionLifecycle(settings).fail(
                    job_id,
                    error_code="synthetic_failure",
                    error_message="Synthetic failure.",
                )
            return result

        monkeypatch.setattr(TrackedLocalArtifactStore, "publish", checked_publish)
        document = _parsed(command.asset_version_id)

        class Parser:
            async def materialize_and_parse(self, *args, **kwargs):
                return document

        class Chunker:
            async def chunk(self, parsed, *, projection_id, **kwargs):
                chunk_id = uuid4()
                evidence = EvidenceUnit(
                    uuid4(),
                    chunk_id,
                    0,
                    parsed.elements[0].text,
                    parsed.elements[0].location,
                    projection_id,
                )
                return ChunkingResult(
                    (
                        RetrievalChunk(
                            chunk_id, projection_id, 0, parsed.elements[0].text, (), (evidence,)
                        ),
                    ),
                    (evidence,),
                )

        class NoExternalIndex:
            async def index(self, **kwargs):
                return None

            async def verify(self, **kwargs):
                return ReadinessVerification(1, 1, 1, 1, True)

        store = LocalObjectStore(tmp_path)
        embedding_stage = ProductionEmbeddingStage(
            settings,
            store,
            embedding_factory=lambda *_: RecordingEmbedding([[1.0, 0.0, 0.0]]),
        )

        class ExactCompletedReplay:
            async def embed(self, **kwargs):
                first_count = await embedding_stage.embed(**kwargs)
                original = embedding_stage.artifact_publisher.publish

                async def advance_after_verified_read(job, role, content):
                    result = await original(job, role, content)
                    await SqlAlchemyRagIngestionLifecycle(settings).complete_embedding(
                        job,
                        embedding_count=first_count,
                    )
                    return result

                monkeypatch.setattr(
                    embedding_stage.artifact_publisher, "publish", advance_after_verified_read
                )
                return await embedding_stage.embed(**kwargs)

        workflow = RagIngestionWorkflow(
            SqlAlchemyRagIngestionLifecycle(settings),
            store,
            Parser(),
            Chunker(),
            ExactCompletedReplay()
            if failure_role == "completed_embedding_replay"
            else embedding_stage,
            NoExternalIndex(),
            NoExternalIndex(),
            artifact_publisher=RagArtifactPublisher(settings),
        )
        if failure_role == "failed_after_embedding_publication":
            with pytest.raises(RagIngestionError):
                await workflow.run(job_id)
            async with sessions() as session:
                bundle = await session.scalar(
                    select(RagArtifactBundleRecord).where(
                        RagArtifactBundleRecord.job_id == job_id,
                    )
                )
                slot = await session.scalar(
                    select(RagArtifactSlotRecord).where(
                        RagArtifactSlotRecord.bundle_id == bundle.id,
                        RagArtifactSlotRecord.role == "embeddings",
                    )
                )
                assert slot.state == "reserved" and slot.published_sha256 is None
                assert (
                    await session.scalar(
                        select(RagArtifactAttemptRecord.state).where(
                            RagArtifactAttemptRecord.slot_id == slot.id,
                        )
                    )
                    == "open"
                )
                assert bundle.revision == 6
                assert (
                    await session.scalar(
                        select(AssetSourceRelationRecord.resource_revision).where(
                            AssetSourceRelationRecord.resource_id == bundle.id,
                        )
                    )
                    == 6
                )
                ingestion = await session.get(RagIngestionJobRecord, job_id)
                assert ingestion.embedding_object_key is None and ingestion.embedding_sha256 is None
                assert ingestion.embedding_count is None
                assert (
                    await session.scalar(select(JobRecord.status).where(JobRecord.id == job_id))
                    == "failed"
                )
                assert (
                    await session.scalar(
                        select(RagProjectionRecord.status).where(
                            RagProjectionRecord.id == ingestion.projection_id,
                        )
                    )
                    == "failed"
                )
                assert (tmp_path / slot.canonical_key).is_file()
            return
        if isinstance(failure_role, ArtifactRole):
            finalizer = task_module.finalize_artifact

            async def finalize_then_fail(session, job, projection, role, reference):
                await finalizer(session, job, projection, role, reference)
                if role == failure_role:
                    raise RuntimeError("synthetic finalization rollback")

            monkeypatch.setattr(task_module, "finalize_artifact", finalize_then_fail)
            monkeypatch.setattr(stage_module, "finalize_artifact", finalize_then_fail)
            with pytest.raises(RuntimeError, match="synthetic finalization rollback"):
                await workflow.run(job_id)
            async with sessions() as session:
                bundle = await session.scalar(
                    select(RagArtifactBundleRecord).where(
                        RagArtifactBundleRecord.job_id == job_id,
                    )
                )
                expected_revision = 4 if failure_role == ArtifactRole.CHUNKS else 6
                assert bundle.revision == expected_revision
                assert (
                    await session.scalar(
                        select(AssetSourceRelationRecord.resource_revision).where(
                            AssetSourceRelationRecord.resource_id == bundle.id,
                        )
                    )
                    == expected_revision
                )
                slot = await session.scalar(
                    select(RagArtifactSlotRecord).where(
                        RagArtifactSlotRecord.bundle_id == bundle.id,
                        RagArtifactSlotRecord.role == failure_role.value,
                    )
                )
                assert slot.state == "reserved" and slot.published_sha256 is None
                assert (
                    await session.scalar(
                        select(RagArtifactAttemptRecord.state).where(
                            RagArtifactAttemptRecord.slot_id == slot.id,
                        )
                    )
                    == "open"
                )
                ingestion = await session.get(RagIngestionJobRecord, job_id)
                if failure_role == ArtifactRole.CHUNKS:
                    assert ingestion.chunk_object_key is None and ingestion.chunk_count is None
                    assert (
                        await session.scalar(
                            select(func.count())
                            .select_from(RetrievalChunkRecord)
                            .where(
                                RetrievalChunkRecord.projection_id == ingestion.projection_id,
                            )
                        )
                        == 0
                    )
                else:
                    assert (
                        ingestion.embedding_object_key is None and ingestion.embedding_count is None
                    )
                content = (tmp_path / slot.canonical_key).read_bytes()
            with pytest.raises(RagIngestionError, match="artifact_attempt_busy"):
                await RagArtifactPublisher(settings).publish(job_id, failure_role, content)
            return
        projection_id = await workflow.run(job_id)
        assert roles == [ArtifactRole.PARSED, ArtifactRole.CHUNKS, ArtifactRole.EMBEDDINGS]
        assert await workflow.run(job_id) == projection_id
        assert len(roles) == 3
        async with sessions() as session:
            bundle = await session.scalar(
                select(RagArtifactBundleRecord).where(RagArtifactBundleRecord.job_id == job_id)
            )
            assert bundle.revision == 7
            assert (
                await session.scalar(
                    select(AssetSourceRelationRecord.resource_revision).where(
                        AssetSourceRelationRecord.resource_id == bundle.id
                    )
                )
                == 7
            )
            slots = list(
                await session.scalars(
                    select(RagArtifactSlotRecord).where(
                        RagArtifactSlotRecord.bundle_id == bundle.id
                    )
                )
            )
            assert len(slots) == 3 and all(slot.state == "verified" for slot in slots)
            attempts = list(
                await session.scalars(
                    select(RagArtifactAttemptRecord)
                    .join(RagArtifactSlotRecord)
                    .where(RagArtifactSlotRecord.bundle_id == bundle.id)
                )
            )
            assert len(attempts) == 3 and all(attempt.state == "closed" for attempt in attempts)
            ingestion = await session.get(RagIngestionJobRecord, job_id)
            assert ingestion.embedding_count == 1
            assert all((tmp_path / slot.canonical_key).is_file() for slot in slots)
            assert not any(tmp_path.rglob("*.tmp"))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "finished,absent", [(True, True), (True, False), (False, True), (False, False)]
)
async def test_only_confirmed_writer_end_and_temp_absence_close_failure(
    migrated_database: IsolatedPublishingDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    finished: bool,
    absent: bool,
) -> None:
    settings = _settings(migrated_database, tmp_path)
    _marker(tmp_path)
    admission = prepare_artifact_admission(settings)
    engine = create_async_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        command = await _command(sessions)
        async with sessions.begin() as session:
            job_id = await RagIngestionService(
                SqlAlchemyRagIngestionCommandRepository(session, artifact_admission=admission)
            ).ensure_indexed(command)
        await SqlAlchemyRagIngestionLifecycle(settings).begin(job_id)

        async def failed_publish(*args):
            raise ArtifactStoreError(
                "artifact_io_failed", writer_finished=finished, temporary_absent=absent
            )

        monkeypatch.setattr(TrackedLocalArtifactStore, "publish", failed_publish)
        with pytest.raises(RagIngestionError, match="artifact_io_failed"):
            await RagArtifactPublisher(settings).publish(job_id, ArtifactRole.PARSED, b"{}")
        async with sessions() as session:
            attempt = await session.scalar(
                select(RagArtifactAttemptRecord)
                .join(RagArtifactSlotRecord)
                .join(RagArtifactBundleRecord)
                .where(RagArtifactBundleRecord.job_id == job_id)
            )
            assert attempt.state == ("closed" if finished and absent else "open")
            assert attempt.result_code == ("artifact_io_failed" if finished and absent else None)
    finally:
        await engine.dispose()
