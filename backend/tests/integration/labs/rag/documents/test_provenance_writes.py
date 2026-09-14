from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_workshop.labs.rag.documents.domain import (
    EvidenceUnit,
    ParsedDocument,
    ProjectionStatus,
    RagProjection,
    RetrievalChunk,
    SourceLocation,
    StructuralElement,
)
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
    StructuralElementRecord,
)
from ai_workshop.labs.rag.documents.repository import SqlAlchemyRagDocumentRepository
from ai_workshop.labs.rag.ingestion.models import (
    RagIngestionDispatchRecord,
    RagIngestionJobRecord,
)
from ai_workshop.labs.rag.ingestion.recovery import (
    SqlAlchemyInactiveRagIngestionReconciler,
)
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import (
    ResourceIdentity,
    SourceIdentity,
    SourceRelation,
)
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.provenance_repository import ProvenanceRepository
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.jobs.domain import JobStatus, JobType
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@contextmanager
def _isolated_database_at(revision: str) -> Iterator[IsolatedPublishingDatabase]:
    monkeypatch = pytest.MonkeyPatch()
    try:
        with isolated_publishing_database(monkeypatch) as database:
            command.upgrade(database.config, revision)
            yield database
    finally:
        monkeypatch.undo()


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[IsolatedPublishingDatabase]:
    with _isolated_database_at("head") as database:
        yield database


@dataclass(frozen=True, slots=True)
class ProjectionSeed:
    owner_id: UUID
    source: SourceIdentity
    indexing_profile_id: UUID


async def _seed_projection_source(session: AsyncSession, *, label: str) -> ProjectionSeed:
    owner_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    asset_version_id = uuid4()
    indexing_profile_id = uuid4()
    email = f"rag-provenance-{owner_id}@example.test"
    session.add(
        UserRecord(
            id=owner_id,
            display_name=f"Synthetic RAG provenance owner {label}",
            email=email,
            normalized_email=email,
            password_hash="synthetic-password-hash",
            role="owner",
            is_active=True,
        )
    )
    await session.flush()
    session.add(
        WorkspaceRecord(
            id=workspace_id,
            name=f"Synthetic RAG provenance workspace {label}",
            kind="personal",
            created_by=owner_id,
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
                name=f"synthetic-{label}.txt",
                active_version_id=None,
            ),
            ProfileRecord(
                id=indexing_profile_id,
                kind="indexing",
                name=f"synthetic-indexing-{indexing_profile_id}",
                version=1,
                config={"chunker": {"name": "synthetic"}},
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
            object_key=f"synthetic/rag-provenance/{asset_version_id}.txt",
            sha256="a" * 64,
            media_type="text/plain",
            size=24,
            status="stored",
        )
    )
    await session.flush()
    return ProjectionSeed(
        owner_id=owner_id,
        source=SourceIdentity(workspace_id, document_id, asset_version_id),
        indexing_profile_id=indexing_profile_id,
    )


def _parsed_document(seed: ProjectionSeed, *, text: str) -> ParsedDocument:
    element_id = uuid4()
    return ParsedDocument(
        asset_version_id=seed.source.asset_version_id,
        parser_name="synthetic-parser",
        parser_version="1",
        elements=(
            StructuralElement(
                id=element_id,
                ordinal=0,
                kind="paragraph",
                text=text,
                section_path=("Synthetic",),
                location=SourceLocation(element_id, 1, 0, len(text), None),
                parser_name="synthetic-parser",
                parser_version="1",
                confidence=1.0,
            ),
        ),
    )


def _resource(projection_id: UUID, revision: int) -> ResourceIdentity:
    return ResourceIdentity(
        participant="rag_document_sql",
        kind="projection_bundle",
        resource_id=projection_id,
        revision=revision,
    )


@pytest.mark.asyncio
async def test_new_projection_starts_revision_one_with_exact_source_relation(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_projection_source(session, label="new")
            projection = RagProjection.pending(
                asset_version_id=seed.source.asset_version_id,
                indexing_profile_id=seed.indexing_profile_id,
            )
            await SqlAlchemyRagDocumentRepository(session).add_projection(projection)

            record = await session.get(RagProjectionRecord, projection.id)
            relations = await ProvenanceRepository(session).list_for_source(seed.source)

            assert record is not None
            assert record.content_revision == 1
            assert relations == (
                SourceRelation(
                    source=seed.source,
                    resource=ResourceIdentity(
                        participant="rag_document_sql",
                        kind="projection_bundle",
                        resource_id=projection.id,
                        revision=1,
                    ),
                    relation_kind="derived_artifact",
                ),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_content_and_status_writes_advance_current_revision_but_same_status_does_not(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_projection_source(session, label="writes")
            projection = RagProjection.pending(
                asset_version_id=seed.source.asset_version_id,
                indexing_profile_id=seed.indexing_profile_id,
            )
            repository = SqlAlchemyRagDocumentRepository(session)
            await repository.add_projection(projection)
            document = _parsed_document(seed, text="first content")
            await repository.save_parsed_document(projection.id, document)
            chunk_id = uuid4()
            await repository.replace_chunks(
                projection.id,
                (
                    RetrievalChunk(
                        id=chunk_id,
                        projection_id=projection.id,
                        ordinal=0,
                        text="first content",
                        section_path=("Synthetic",),
                        evidence_units=(
                            EvidenceUnit(
                                id=uuid4(),
                                chunk_id=chunk_id,
                                ordinal=0,
                                text="first content",
                                location=document.elements[0].location,
                                projection_id=projection.id,
                            ),
                        ),
                    ),
                ),
            )
            parsing = await repository.mark_status(projection.id, ProjectionStatus.PARSING)
            duplicate = await repository.mark_status(projection.id, ProjectionStatus.PARSING)

            record = await session.get(RagProjectionRecord, projection.id)
            relations = await ProvenanceRepository(session).list_for_source(seed.source)

            assert parsing.status is ProjectionStatus.PARSING
            assert duplicate.status is ProjectionStatus.PARSING
            assert record is not None and record.content_revision == 4
            assert [relation.resource.revision for relation in relations] == [4]
            assert (
                await session.scalar(
                    select(RetrievalChunkRecord.id).where(
                        RetrievalChunkRecord.projection_id == projection.id
                    )
                )
                == chunk_id
            )
            assert (
                await session.scalar(
                    select(EvidenceUnitRecord.projection_id).where(
                        EvidenceUnitRecord.retrieval_chunk_id == chunk_id
                    )
                )
                == projection.id
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_null_projection_writes_without_backfill_or_relation(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_projection_source(session, label="legacy")
            projection = RagProjection.pending(
                asset_version_id=seed.source.asset_version_id,
                indexing_profile_id=seed.indexing_profile_id,
            )
            repository = SqlAlchemyRagDocumentRepository(session)
            await repository.add_projection(projection)
            await session.execute(
                update(RagProjectionRecord)
                .where(RagProjectionRecord.id == projection.id)
                .values(content_revision=None)
            )
            await session.execute(
                delete(AssetSourceRelationRecord).where(
                    AssetSourceRelationRecord.resource_id == projection.id
                )
            )
            await session.flush()

            await repository.save_parsed_document(
                projection.id, _parsed_document(seed, text="legacy content")
            )
            await repository.mark_status(projection.id, ProjectionStatus.PARSING)

            record = await session.get(RagProjectionRecord, projection.id)
            relations = await ProvenanceRepository(session).list_for_source(seed.source)
            assert record is not None and record.content_revision is None
            assert relations == ()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_replace_current_rejects_shape_revision_and_persisted_relation_conflicts(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            first = await _seed_projection_source(session, label="conflict-first")
            second = await _seed_projection_source(session, label="conflict-second")
            projection = RagProjection.pending(
                asset_version_id=first.source.asset_version_id,
                indexing_profile_id=first.indexing_profile_id,
            )
            await SqlAlchemyRagDocumentRepository(session).add_projection(projection)
            repository = ProvenanceRepository(session)
            expected = SourceRelation(first.source, _resource(projection.id, 1), "derived_artifact")
            replacement = SourceRelation(
                first.source, _resource(projection.id, 2), "derived_artifact"
            )

            invalid_replacements = (
                SourceRelation(second.source, _resource(projection.id, 2), "derived_artifact"),
                SourceRelation(first.source, _resource(projection.id, 3), "derived_artifact"),
                SourceRelation(
                    first.source,
                    ResourceIdentity("other_participant", "projection_bundle", projection.id, 2),
                    "derived_artifact",
                ),
                SourceRelation(
                    first.source,
                    ResourceIdentity("rag_document_sql", "other_kind", projection.id, 2),
                    "derived_artifact",
                ),
                SourceRelation(first.source, _resource(projection.id, 2), "source_copy"),
            )
            for invalid in invalid_replacements:
                with pytest.raises(RuntimeError, match="provenance_current_conflict"):
                    await repository.replace_current(expected, invalid)

            await session.execute(
                delete(AssetSourceRelationRecord).where(
                    AssetSourceRelationRecord.resource_id == projection.id
                )
            )
            await session.flush()
            with pytest.raises(RuntimeError, match="provenance_current_conflict"):
                await repository.replace_current(expected, replacement)

            await repository.register(
                SourceRelation(second.source, _resource(projection.id, 1), "derived_artifact")
            )
            with pytest.raises(RuntimeError, match="provenance_current_conflict"):
                await repository.replace_current(expected, replacement)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_new_projection_and_relation_roll_back_together(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_projection_source(session, label="new-rollback")
        projection = RagProjection.pending(
            asset_version_id=seed.source.asset_version_id,
            indexing_profile_id=seed.indexing_profile_id,
        )
        async with sessions() as session:
            await SqlAlchemyRagDocumentRepository(session).add_projection(projection)
            await session.rollback()

        async with sessions() as session:
            assert await session.get(RagProjectionRecord, projection.id) is None
            assert await ProvenanceRepository(session).list_for_source(seed.source) == ()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_mutation_rolls_back_content_revision_and_relations(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    projection_id: UUID
    first: ProjectionSeed
    second: ProjectionSeed
    try:
        async with sessions.begin() as session:
            first = await _seed_projection_source(session, label="rollback-first")
            second = await _seed_projection_source(session, label="rollback-second")
            projection = RagProjection.pending(
                asset_version_id=first.source.asset_version_id,
                indexing_profile_id=first.indexing_profile_id,
            )
            projection_id = projection.id
            repository = SqlAlchemyRagDocumentRepository(session)
            await repository.add_projection(projection)
            await repository.save_parsed_document(
                projection.id, _parsed_document(first, text="committed content")
            )
            await ProvenanceRepository(session).register(
                SourceRelation(second.source, _resource(projection.id, 2), "derived_artifact")
            )

        async with sessions() as session:
            with pytest.raises(RuntimeError, match="provenance_current_conflict"):
                async with session.begin():
                    await SqlAlchemyRagDocumentRepository(session).save_parsed_document(
                        projection_id,
                        _parsed_document(first, text="must roll back"),
                    )

        async with sessions() as session:
            record = await session.get(RagProjectionRecord, projection_id)
            texts = tuple(
                await session.scalars(
                    select(StructuralElementRecord.text).where(
                        StructuralElementRecord.projection_id == projection_id
                    )
                )
            )
            relation_sources = set(
                await session.execute(
                    select(
                        AssetSourceRelationRecord.workspace_id,
                        AssetSourceRelationRecord.document_id,
                        AssetSourceRelationRecord.asset_version_id,
                    ).where(
                        AssetSourceRelationRecord.participant == "rag_document_sql",
                        AssetSourceRelationRecord.kind == "projection_bundle",
                        AssetSourceRelationRecord.resource_id == projection_id,
                        AssetSourceRelationRecord.resource_revision == 2,
                    )
                )
            )
            assert record is not None and record.content_revision == 2
            assert texts == ("committed content",)
            assert relation_sources == {
                (
                    first.source.workspace_id,
                    first.source.document_id,
                    first.source.asset_version_id,
                ),
                (
                    second.source.workspace_id,
                    second.source.document_id,
                    second.source.asset_version_id,
                ),
            }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_committed_content_writes_use_consecutive_revisions_and_refresh_stale_maps(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_projection_source(session, label="concurrent")
            projection = RagProjection.pending(
                asset_version_id=seed.source.asset_version_id,
                indexing_profile_id=seed.indexing_profile_id,
            )
            await SqlAlchemyRagDocumentRepository(session).add_projection(projection)

        stale_session = sessions()
        try:
            stale = await stale_session.get(RagProjectionRecord, projection.id)
            assert stale is not None and stale.content_revision == 1
            stale_relation = await stale_session.scalar(
                select(AssetSourceRelationRecord).where(
                    AssetSourceRelationRecord.resource_id == projection.id
                )
            )
            assert stale_relation is not None and stale_relation.resource_revision == 1

            async def write(text: str) -> None:
                async with sessions.begin() as session:
                    await SqlAlchemyRagDocumentRepository(session).save_parsed_document(
                        projection.id, _parsed_document(seed, text=text)
                    )

            await asyncio.gather(write("concurrent one"), write("concurrent two"))
            await SqlAlchemyRagDocumentRepository(stale_session).mark_status(
                projection.id, ProjectionStatus.PARSING
            )
            await stale_session.commit()

            assert stale.content_revision == 4
            assert stale_relation.resource_revision == 4
        finally:
            await stale_session.close()

        async with sessions() as session:
            record = await session.get(RagProjectionRecord, projection.id)
            relations = await ProvenanceRepository(session).list_for_source(seed.source)
            assert record is not None and record.content_revision == 4
            assert [relation.resource.revision for relation in relations] == [4]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_invalid_evidence_does_not_change_stored_bundle_before_rollback(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_projection_source(session, label="invalid-evidence")
            projection = RagProjection.pending(
                asset_version_id=seed.source.asset_version_id,
                indexing_profile_id=seed.indexing_profile_id,
            )
            repository = SqlAlchemyRagDocumentRepository(session)
            await repository.add_projection(projection)
            document = _parsed_document(seed, text="Preserved synthetic content")
            await repository.save_parsed_document(projection.id, document)
            chunk_id = uuid4()
            evidence = EvidenceUnit(
                id=uuid4(), chunk_id=chunk_id, ordinal=0,
                text="Preserved synthetic content", location=document.elements[0].location,
                projection_id=projection.id,
            )
            chunk = RetrievalChunk(
                id=chunk_id, projection_id=projection.id, ordinal=0,
                text="Preserved synthetic content", section_path=("Synthetic",),
                evidence_units=(evidence,),
            )
            await repository.replace_chunks(projection.id, (chunk,))

            # Corrupt an already validated value to exercise the repository's
            # defensive check without bypassing the real persistence path.
            object.__setattr__(evidence, "chunk_id", uuid4())
            with pytest.raises(ValueError, match="containing retrieval chunk"):
                await repository.replace_chunks(projection.id, (chunk,))

            # No rollback/refresh rescue before inspection: invalid input must
            # not leave pending destructive writes in the caller transaction.
            assert await session.scalar(
                select(EvidenceUnitRecord.id).where(
                    EvidenceUnitRecord.retrieval_chunk_id == chunk_id
                )
            ) == evidence.id
            assert await session.scalar(
                select(RetrievalChunkRecord.text).where(RetrievalChunkRecord.id == chunk_id)
            ) == "Preserved synthetic content"
            assert await session.scalar(
                select(RagProjectionRecord.content_revision).where(
                    RagProjectionRecord.id == projection.id
                )
            ) == 3
            relations = await ProvenanceRepository(session).list_for_source(seed.source)
            assert [relation.resource.revision for relation in relations] == [3]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_inactive_ingestion_recovery_advances_failed_status_revision_once(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    job_id = uuid4()
    try:
        async with sessions.begin() as session:
            seed = await _seed_projection_source(session, label="recovery")
            projection = RagProjection.pending(
                asset_version_id=seed.source.asset_version_id,
                indexing_profile_id=seed.indexing_profile_id,
            )
            await SqlAlchemyRagDocumentRepository(session).add_projection(projection)
            session.add(
                JobRecord(
                    id=job_id,
                    user_id=seed.owner_id,
                    workspace_id=seed.source.workspace_id,
                    asset_version_id=seed.source.asset_version_id,
                    type=JobType.RAG_INGESTION,
                    idempotency_key=f"synthetic-recovery-{job_id}",
                    status=JobStatus.QUEUED,
                    stage="queued",
                    attempt=0,
                    error_code=None,
                    error_message=None,
                    started_at=None,
                    finished_at=None,
                )
            )
            await session.flush()
            session.add(
                RagIngestionJobRecord(
                    job_id=job_id,
                    projection_id=projection.id,
                    asset_version_id=seed.source.asset_version_id,
                    indexing_profile_id=seed.indexing_profile_id,
                    requested_by=seed.owner_id,
                    parsed_object_key=None,
                    parsed_sha256=None,
                    chunk_object_key=None,
                    chunk_sha256=None,
                    embedding_object_key=None,
                    embedding_sha256=None,
                    index_build_id=None,
                    parsed_element_count=None,
                    chunk_count=None,
                    embedding_count=None,
                    indexed_document_count=None,
                    index_alias_verified=False,
                )
            )
            await session.flush()
            session.add(
                RagIngestionDispatchRecord(
                    job_id=job_id,
                    status="pending",
                    available_at=datetime.now(UTC),
                    claimed_at=None,
                    claim_token=None,
                    attempt_count=0,
                    last_error=None,
                    sent_at=None,
                    cancelled_at=None,
                )
            )

        first = await SqlAlchemyInactiveRagIngestionReconciler(sessions).run_once(limit=10)
        second = await SqlAlchemyInactiveRagIngestionReconciler(sessions).run_once(limit=10)
        assert first.terminalized == 1
        assert second.terminalized == 0

        async with sessions() as session:
            record = await session.get(RagProjectionRecord, projection.id)
            relations = await ProvenanceRepository(session).list_for_source(seed.source)
            assert record is not None
            assert record.status == ProjectionStatus.FAILED
            assert record.content_revision == 2
            assert [relation.resource.revision for relation in relations] == [2]
    finally:
        await engine.dispose()
