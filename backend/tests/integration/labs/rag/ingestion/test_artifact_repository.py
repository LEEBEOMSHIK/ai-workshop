from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.labs.rag.ingestion.artifact_contracts import (
    ArtifactBinding,
    ArtifactClaim,
    ArtifactPublication,
    ArtifactRole,
    ArtifactTrackingError,
    VerifiedArtifact,
)
from ai_workshop.labs.rag.ingestion.artifact_models import (
    RagArtifactAttemptRecord,
    RagArtifactBundleRecord,
    RagArtifactSlotRecord,
)
from ai_workshop.labs.rag.ingestion.artifact_repository import (
    SqlAlchemyRagArtifactRepository,
)
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
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

_DIGEST = sha256(b"{}").hexdigest()
_BINDING = ArtifactBinding("rag_artifacts", UUID("10000000-0000-0000-0000-000000000001"))


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


@pytest.fixture(autouse=True)
def ensure_legacy_document_processing_profile(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    """Shadow the directory autouse fixture until the UUID database exists."""
    assert migrated_database.name.startswith("ai_workshop_publishing_")


@dataclass(frozen=True, slots=True)
class Seed:
    owner_id: UUID
    source: SourceIdentity
    projection_id: UUID
    job_id: UUID


async def _seed_official_ingestion(session: AsyncSession, *, label: str) -> Seed:
    owner_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    asset_version_id = uuid4()
    indexing_profile_id = uuid4()
    projection_id = uuid4()
    job_id = uuid4()
    email = f"artifact-{owner_id}@example.test"
    session.add(
        UserRecord(
            id=owner_id,
            display_name=f"Synthetic artifact owner {label}",
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
            name=f"Synthetic artifact workspace {label}",
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
            object_key=f"synthetic/artifact/{asset_version_id}.txt",
            sha256="a" * 64,
            media_type="text/plain",
            size=2,
            status="stored",
        )
    )
    await session.flush()
    session.add(
        RagProjectionRecord(
            id=projection_id,
            asset_version_id=asset_version_id,
            indexing_profile_id=indexing_profile_id,
            status=ProjectionStatus.PENDING,
            content_revision=None,
        )
    )
    await session.flush()
    session.add(
        JobRecord(
            id=job_id,
            user_id=owner_id,
            workspace_id=workspace_id,
            asset_version_id=asset_version_id,
            type=JobType.RAG_INGESTION,
            idempotency_key=f"synthetic-artifact-{job_id}",
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
            projection_id=projection_id,
            asset_version_id=asset_version_id,
            indexing_profile_id=indexing_profile_id,
            requested_by=owner_id,
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
    return Seed(
        owner_id,
        SourceIdentity(workspace_id, document_id, asset_version_id),
        projection_id,
        job_id,
    )


def _artifact_relation(seed: Seed, bundle_id: UUID, revision: int) -> SourceRelation:
    return SourceRelation(
        seed.source,
        ResourceIdentity("rag_ingestion_artifacts", "artifact_bundle", bundle_id, revision),
        "derived_artifact",
    )


@pytest.mark.asyncio
async def test_register_reserve_finalize_and_replay_keep_one_current_relation(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="lifecycle")
            sql_relation = SourceRelation(
                seed.source,
                ResourceIdentity("rag_document_sql", "projection_bundle", seed.projection_id, 1),
                "derived_artifact",
            )
            await ProvenanceRepository(session).register(sql_relation)
            bundle_id = await SqlAlchemyRagArtifactRepository(session).register_bundle(
                seed.job_id, _BINDING
            )

            slots = tuple(
                await session.scalars(
                    select(RagArtifactSlotRecord)
                    .where(RagArtifactSlotRecord.bundle_id == bundle_id)
                    .order_by(RagArtifactSlotRecord.role)
                )
            )
            assert [(slot.role, slot.canonical_key, slot.state) for slot in slots] == [
                ("chunks", f"rag/chunks/{seed.projection_id}.json", "reserved"),
                ("embeddings", f"rag/embeddings/{seed.projection_id}.json", "reserved"),
                ("parsed", f"rag/parsed/{seed.projection_id}.json", "reserved"),
            ]
            assert await ProvenanceRepository(session).list_for_source(seed.source) == (
                sql_relation,
                _artifact_relation(seed, bundle_id, 1),
            )

        async with sessions.begin() as session:
            claim = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                seed.job_id, ArtifactRole.PARSED, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(claim, ArtifactClaim)
            assert claim.bundle_id == bundle_id
            assert claim.temporary_key == (
                f"rag/parsed/.{seed.projection_id}.json.{claim.attempt_id.hex}.tmp"
            )
            with pytest.raises(ArtifactTrackingError) as exc_info:
                await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                    seed.job_id, ArtifactRole.PARSED, _BINDING, size=2, sha256=_DIGEST
                )
            assert exc_info.value.code == "artifact_attempt_busy"

        async with sessions.begin() as session:
            repository = SqlAlchemyRagArtifactRepository(session)
            verified = await repository.finalize(
                ArtifactPublication(claim=claim, size=2, sha256=_DIGEST)
            )
            duplicate = await repository.finalize(
                ArtifactPublication(claim=claim, size=2, sha256=_DIGEST)
            )
            replay = await repository.reserve_attempt(
                seed.job_id, ArtifactRole.PARSED, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(verified, VerifiedArtifact)
            assert duplicate == verified
            assert replay == verified

        async with sessions() as session:
            bundle = await session.get(RagArtifactBundleRecord, bundle_id)
            attempt = await session.get(RagArtifactAttemptRecord, claim.attempt_id)
            relations = tuple(
                await session.scalars(
                    select(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.participant == "rag_ingestion_artifacts",
                        AssetSourceRelationRecord.kind == "artifact_bundle",
                        AssetSourceRelationRecord.resource_id == bundle_id,
                    )
                )
            )
            assert bundle is not None and bundle.revision == 3
            assert attempt is not None
            assert (attempt.state, attempt.result_code, attempt.closed_at is not None) == (
                "closed",
                "verified",
                True,
            )
            assert len(relations) == 1 and relations[0].resource_revision == 3
            assert await ProvenanceRepository(session).list_for_resource(
                seed.source.workspace_id,
                ResourceIdentity(
                    "rag_document_sql", "projection_bundle", seed.projection_id, 1
                ),
            ) == (sql_relation,)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_close_allows_fresh_attempt_but_old_open_attempt_is_never_taken_over(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="failed")
            repository = SqlAlchemyRagArtifactRepository(session)
            bundle_id = await repository.register_bundle(seed.job_id, _BINDING)
        async with sessions.begin() as session:
            claim = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                seed.job_id, ArtifactRole.CHUNKS, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(claim, ArtifactClaim)
        async with sessions.begin() as session:
            await session.execute(
                update(RagArtifactAttemptRecord)
                .where(RagArtifactAttemptRecord.id == claim.attempt_id)
                .values(created_at=datetime.now(UTC) - timedelta(days=30))
            )
        async with sessions.begin() as session:
            repository = SqlAlchemyRagArtifactRepository(session)
            with pytest.raises(ArtifactTrackingError) as exc_info:
                await repository.reserve_attempt(
                    seed.job_id, ArtifactRole.CHUNKS, _BINDING, size=2, sha256=_DIGEST
                )
            assert exc_info.value.code == "artifact_attempt_busy"
        async with sessions.begin() as session:
            repository = SqlAlchemyRagArtifactRepository(session)
            await repository.close_failed_attempt(claim, code="writer_finished")
            await repository.close_failed_attempt(claim, code="writer_finished")
        async with sessions.begin() as session:
            fresh = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                seed.job_id, ArtifactRole.CHUNKS, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(fresh, ArtifactClaim)
            assert fresh.attempt_id != claim.attempt_id
            assert fresh.temporary_key != claim.temporary_key
        async with sessions() as session:
            bundle = await session.get(RagArtifactBundleRecord, bundle_id)
            attempts = tuple(
                await session.scalars(
                    select(RagArtifactAttemptRecord)
                    .where(RagArtifactAttemptRecord.slot_id == claim.slot_id)
                    .order_by(RagArtifactAttemptRecord.created_at)
                )
            )
            assert bundle is not None and bundle.revision == 4
            assert [(attempt.id, attempt.state) for attempt in attempts] == [
                (claim.attempt_id, "closed"),
                (fresh.attempt_id, "open"),
            ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_invalid_binding_source_token_payload_and_current_relation_do_not_mutate(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="invalid")
            other = await _seed_official_ingestion(session, label="other-source")
            repository = SqlAlchemyRagArtifactRepository(session)
            bundle_id = await repository.register_bundle(seed.job_id, _BINDING)
        invalid_binding = ArtifactBinding("rag_artifacts", uuid4())
        async with sessions.begin() as session:
            repository = SqlAlchemyRagArtifactRepository(session)
            for size, digest, expected_code in (
                (-1, _DIGEST, "artifact_size_invalid"),
                (2, "A" * 64, "artifact_sha256_invalid"),
            ):
                with pytest.raises(ArtifactTrackingError) as exc_info:
                    await repository.reserve_attempt(
                        seed.job_id,
                        ArtifactRole.PARSED,
                        _BINDING,
                        size=size,
                        sha256=digest,
                    )
                assert exc_info.value.code == expected_code
            with pytest.raises(ArtifactTrackingError) as exc_info:
                await repository.reserve_attempt(
                    seed.job_id,
                    ArtifactRole.PARSED,
                    invalid_binding,
                    size=2,
                    sha256=_DIGEST,
                )
            assert exc_info.value.code == "artifact_binding_mismatch"
        async with sessions.begin() as session:
            claim = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                seed.job_id, ArtifactRole.PARSED, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(claim, ArtifactClaim)
        invalid_claims = (
            (
                replace(claim, attempt_id=uuid4()),
                "artifact_attempt_invalid",
            ),
            (
                replace(claim, job_id=other.job_id),
                "artifact_claim_source_mismatch",
            ),
        )
        for invalid_claim, expected_code in invalid_claims:
            async with sessions.begin() as session:
                with pytest.raises(ArtifactTrackingError) as exc_info:
                    await SqlAlchemyRagArtifactRepository(session).finalize(
                        ArtifactPublication(claim=invalid_claim, size=2, sha256=_DIGEST)
                    )
                assert exc_info.value.code == expected_code
        async with sessions.begin() as session:
            with pytest.raises(ArtifactTrackingError) as exc_info:
                await SqlAlchemyRagArtifactRepository(session).finalize(
                    ArtifactPublication(claim=claim, size=3, sha256=sha256(b"bad").hexdigest())
                )
            assert exc_info.value.code == "artifact_publication_mismatch"
        async with sessions.begin() as session:
            bundle = await session.get(RagArtifactBundleRecord, bundle_id)
            assert bundle is not None and bundle.revision == 2
            session.add(
                AssetSourceRelationRecord(
                    workspace_id=other.source.workspace_id,
                    document_id=other.source.document_id,
                    asset_version_id=other.source.asset_version_id,
                    participant="rag_ingestion_artifacts",
                    kind="artifact_bundle",
                    resource_id=bundle_id,
                    resource_revision=2,
                    relation_kind="derived_artifact",
                )
            )
        async with sessions.begin() as session:
            with pytest.raises(ArtifactTrackingError) as exc_info:
                await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                    seed.job_id,
                    ArtifactRole.EMBEDDINGS,
                    _BINDING,
                    size=2,
                    sha256=_DIGEST,
                )
            assert exc_info.value.code == "artifact_current_relation_conflict"
            with pytest.raises(ArtifactTrackingError) as register_exc:
                await SqlAlchemyRagArtifactRepository(session).register_bundle(
                    seed.job_id, _BINDING
                )
            assert register_exc.value.code == "artifact_current_relation_conflict"
        async with sessions() as session:
            bundle = await session.get(RagArtifactBundleRecord, bundle_id)
            attempt = await session.get(RagArtifactAttemptRecord, claim.attempt_id)
            assert bundle is not None and bundle.revision == 2
            assert attempt is not None and attempt.state == "open"
            assert await session.scalar(
                select(RagArtifactAttemptRecord.id)
                .join(RagArtifactSlotRecord)
                .where(
                    RagArtifactSlotRecord.bundle_id == bundle_id,
                    RagArtifactSlotRecord.role == "embeddings",
                )
            ) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_verified_slot_with_an_open_writer_is_rejected_as_inconsistent(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="verified-open")
            repository = SqlAlchemyRagArtifactRepository(session)
            await repository.register_bundle(seed.job_id, _BINDING)
        async with sessions.begin() as session:
            claim = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                seed.job_id, ArtifactRole.PARSED, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(claim, ArtifactClaim)
        async with sessions.begin() as session:
            await session.execute(
                update(RagArtifactSlotRecord)
                .where(RagArtifactSlotRecord.id == claim.slot_id)
                .values(
                    state="verified",
                    published_size=2,
                    published_sha256=_DIGEST,
                )
            )
        async with sessions.begin() as session:
            with pytest.raises(ArtifactTrackingError) as exc_info:
                await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                    seed.job_id,
                    ArtifactRole.PARSED,
                    _BINDING,
                    size=2,
                    sha256=_DIGEST,
                )
            assert exc_info.value.code == "artifact_slot_state_conflict"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reservation_rolls_back_atomically(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="rollback")
            bundle_id = await SqlAlchemyRagArtifactRepository(session).register_bundle(
                seed.job_id, _BINDING
            )
        async with sessions() as session:
            claim = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                seed.job_id, ArtifactRole.EMBEDDINGS, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(claim, ArtifactClaim)
            await session.rollback()
        async with sessions() as session:
            bundle = await session.get(RagArtifactBundleRecord, bundle_id)
            relations = await ProvenanceRepository(session).list_for_source(seed.source)
            assert bundle is not None and bundle.revision == 1
            assert relations == (_artifact_relation(seed, bundle_id, 1),)
            assert await session.scalar(
                select(RagArtifactAttemptRecord.id).where(
                    RagArtifactAttemptRecord.slot_id == claim.slot_id
                )
            ) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_reservation_and_stale_session_use_consecutive_revisions(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="concurrent")
            bundle_id = await SqlAlchemyRagArtifactRepository(session).register_bundle(
                seed.job_id, _BINDING
            )
        stale_session = sessions()
        try:
            stale_bundle = await stale_session.get(RagArtifactBundleRecord, bundle_id)
            stale_relation = await stale_session.scalar(
                select(AssetSourceRelationRecord).where(
                    AssetSourceRelationRecord.resource_id == bundle_id
                )
            )
            assert stale_bundle is not None and stale_bundle.revision == 1
            assert stale_relation is not None and stale_relation.resource_revision == 1

            async def reserve_chunks() -> ArtifactClaim | VerifiedArtifact:
                async with sessions.begin() as session:
                    return await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                        seed.job_id,
                        ArtifactRole.CHUNKS,
                        _BINDING,
                        size=2,
                        sha256=_DIGEST,
                    )

            results = await asyncio.gather(
                reserve_chunks(), reserve_chunks(), return_exceptions=True
            )
            assert sum(isinstance(item, ArtifactClaim) for item in results) == 1
            errors = [item for item in results if isinstance(item, ArtifactTrackingError)]
            assert [error.code for error in errors] == ["artifact_attempt_busy"]

            embedding_claim = await SqlAlchemyRagArtifactRepository(
                stale_session
            ).reserve_attempt(
                seed.job_id,
                ArtifactRole.EMBEDDINGS,
                _BINDING,
                size=2,
                sha256=_DIGEST,
            )
            assert isinstance(embedding_claim, ArtifactClaim)
            await stale_session.commit()
            assert stale_bundle.revision == 3
            assert stale_relation.resource_revision == 3
        finally:
            await stale_session.close()
        async with sessions() as session:
            assert await session.scalar(
                select(RagArtifactBundleRecord.revision).where(
                    RagArtifactBundleRecord.id == bundle_id
                )
            ) == 3
            assert await session.scalar(
                select(AssetSourceRelationRecord.resource_revision).where(
                    AssetSourceRelationRecord.resource_id == bundle_id
                )
            ) == 3
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_bundle_revision_advances_once_per_root_transaction_across_repositories(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="transaction-coalescing")
            bundle_id = await SqlAlchemyRagArtifactRepository(session).register_bundle(
                seed.job_id, _BINDING
            )

        reused_session = sessions()
        try:
            async with reused_session.begin():
                parsed = await SqlAlchemyRagArtifactRepository(
                    reused_session
                ).reserve_attempt(
                    seed.job_id,
                    ArtifactRole.PARSED,
                    _BINDING,
                    size=2,
                    sha256=_DIGEST,
                )
                chunks = await SqlAlchemyRagArtifactRepository(
                    reused_session
                ).reserve_attempt(
                    seed.job_id,
                    ArtifactRole.CHUNKS,
                    _BINDING,
                    size=2,
                    sha256=_DIGEST,
                )
                assert isinstance(parsed, ArtifactClaim)
                assert isinstance(chunks, ArtifactClaim)
                assert await reused_session.scalar(
                    select(RagArtifactBundleRecord.revision).where(
                        RagArtifactBundleRecord.id == bundle_id
                    )
                ) == 2
                assert await reused_session.scalar(
                    select(AssetSourceRelationRecord.resource_revision).where(
                        AssetSourceRelationRecord.resource_id == bundle_id
                    )
                ) == 2

            async with reused_session.begin():
                embeddings = await SqlAlchemyRagArtifactRepository(
                    reused_session
                ).reserve_attempt(
                    seed.job_id,
                    ArtifactRole.EMBEDDINGS,
                    _BINDING,
                    size=2,
                    sha256=_DIGEST,
                )
                assert isinstance(embeddings, ArtifactClaim)
        finally:
            await reused_session.close()

        async with sessions() as session:
            assert await session.scalar(
                select(RagArtifactBundleRecord.revision).where(
                    RagArtifactBundleRecord.id == bundle_id
                )
            ) == 3
            assert await session.scalar(
                select(AssetSourceRelationRecord.resource_revision).where(
                    AssetSourceRelationRecord.resource_id == bundle_id
                )
            ) == 3
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_revision_coalescing_recovers_after_root_and_savepoint_rollbacks(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="coalescing-rollback")
            bundle_id = await SqlAlchemyRagArtifactRepository(session).register_bundle(
                seed.job_id, _BINDING
            )

        reused_session = sessions()
        try:
            root = await reused_session.begin()
            await SqlAlchemyRagArtifactRepository(reused_session).reserve_attempt(
                seed.job_id, ArtifactRole.PARSED, _BINDING, size=2, sha256=_DIGEST
            )
            await SqlAlchemyRagArtifactRepository(reused_session).reserve_attempt(
                seed.job_id, ArtifactRole.CHUNKS, _BINDING, size=2, sha256=_DIGEST
            )
            assert await reused_session.scalar(
                select(RagArtifactBundleRecord.revision).where(
                    RagArtifactBundleRecord.id == bundle_id
                )
            ) == 2
            await root.rollback()

            root = await reused_session.begin()
            savepoint = await reused_session.begin_nested()
            await SqlAlchemyRagArtifactRepository(reused_session).reserve_attempt(
                seed.job_id, ArtifactRole.PARSED, _BINDING, size=2, sha256=_DIGEST
            )
            await SqlAlchemyRagArtifactRepository(reused_session).reserve_attempt(
                seed.job_id, ArtifactRole.CHUNKS, _BINDING, size=2, sha256=_DIGEST
            )
            assert await reused_session.scalar(
                select(RagArtifactBundleRecord.revision).where(
                    RagArtifactBundleRecord.id == bundle_id
                )
            ) == 2
            await savepoint.rollback()

            surviving = await SqlAlchemyRagArtifactRepository(
                reused_session
            ).reserve_attempt(
                seed.job_id,
                ArtifactRole.EMBEDDINGS,
                _BINDING,
                size=2,
                sha256=_DIGEST,
            )
            assert isinstance(surviving, ArtifactClaim)
            await root.commit()
        finally:
            await reused_session.close()

        async with sessions() as session:
            assert await session.scalar(
                select(RagArtifactBundleRecord.revision).where(
                    RagArtifactBundleRecord.id == bundle_id
                )
            ) == 2
            attempts = tuple(
                await session.scalars(
                    select(RagArtifactAttemptRecord)
                    .join(RagArtifactSlotRecord)
                    .where(RagArtifactSlotRecord.bundle_id == bundle_id)
                )
            )
            assert [attempt.id for attempt in attempts] == [surviving.attempt_id]
            assert await session.scalar(
                select(AssetSourceRelationRecord.resource_revision).where(
                    AssetSourceRelationRecord.resource_id == bundle_id
                )
            ) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("release_inner", [False, True])
async def test_savepoint_rollback_does_not_coalesce_an_intervening_writer_revision(
    migrated_database: IsolatedPublishingDatabase, release_inner: bool,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="savepoint-interleaving")
            bundle_id = await SqlAlchemyRagArtifactRepository(session).register_bundle(
                seed.job_id, _BINDING
            )
        async with sessions.begin() as first:
            outer = await first.begin_nested()
            inner = await first.begin_nested() if release_inner else None
            rolled_back = await SqlAlchemyRagArtifactRepository(first).reserve_attempt(
                seed.job_id, ArtifactRole.PARSED, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(rolled_back, ArtifactClaim)
            if inner is not None:
                await inner.commit()
            await outer.rollback()

            async with sessions.begin() as second:
                other = await asyncio.wait_for(
                    SqlAlchemyRagArtifactRepository(second).reserve_attempt(
                        seed.job_id, ArtifactRole.CHUNKS, _BINDING, size=2, sha256=_DIGEST
                    ),
                    timeout=5,
                )
                assert isinstance(other, ArtifactClaim)
            surviving = await SqlAlchemyRagArtifactRepository(first).reserve_attempt(
                seed.job_id, ArtifactRole.EMBEDDINGS, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(surviving, ArtifactClaim)

        async with sessions() as session:
            assert await session.scalar(
                select(RagArtifactBundleRecord.revision).where(
                    RagArtifactBundleRecord.id == bundle_id
                )
            ) == 3
            assert await session.scalar(
                select(AssetSourceRelationRecord.resource_revision).where(
                    AssetSourceRelationRecord.resource_id == bundle_id
                )
            ) == 3
            attempts = set(await session.scalars(
                select(RagArtifactAttemptRecord.id).join(RagArtifactSlotRecord).where(
                    RagArtifactSlotRecord.bundle_id == bundle_id
                )
            ))
            assert attempts == {other.attempt_id, surviving.attempt_id}
            assert rolled_back.attempt_id not in attempts
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("release_first", [False, True])
async def test_savepoint_rollback_preserves_prior_surviving_revision_increment(
    migrated_database: IsolatedPublishingDatabase, release_first: bool,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="savepoint-surviving")
            bundle_id = await SqlAlchemyRagArtifactRepository(session).register_bundle(
                seed.job_id, _BINDING
            )
        async with sessions.begin() as session:
            initial = await session.begin_nested() if release_first else None
            surviving = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                seed.job_id, ArtifactRole.PARSED, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(surviving, ArtifactClaim)
            if initial is not None:
                await initial.commit()
            savepoint = await session.begin_nested()
            rolled_back = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                seed.job_id, ArtifactRole.CHUNKS, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(rolled_back, ArtifactClaim)
            await savepoint.rollback()
            later = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                seed.job_id, ArtifactRole.EMBEDDINGS, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(later, ArtifactClaim)

        async with sessions() as session:
            assert await session.scalar(
                select(RagArtifactBundleRecord.revision).where(
                    RagArtifactBundleRecord.id == bundle_id
                )
            ) == 2
            assert await session.scalar(
                select(AssetSourceRelationRecord.resource_revision).where(
                    AssetSourceRelationRecord.resource_id == bundle_id
                )
            ) == 2
            attempts = set(await session.scalars(
                select(RagArtifactAttemptRecord.id).join(RagArtifactSlotRecord).where(
                    RagArtifactSlotRecord.bundle_id == bundle_id
                )
            ))
            assert attempts == {surviving.attempt_id, later.attempt_id}
            assert rolled_back.attempt_id not in attempts
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_finalize_rolls_back_slot_attempt_bundle_and_relation_together(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="finalize-rollback")
            bundle_id = await SqlAlchemyRagArtifactRepository(session).register_bundle(
                seed.job_id, _BINDING
            )
        async with sessions.begin() as session:
            claim = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                seed.job_id, ArtifactRole.PARSED, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(claim, ArtifactClaim)

        async with sessions() as session:
            verified = await SqlAlchemyRagArtifactRepository(session).finalize(
                ArtifactPublication(claim=claim, size=2, sha256=_DIGEST)
            )
            assert verified.size == 2
            await session.rollback()

        async with sessions() as session:
            bundle = await session.get(RagArtifactBundleRecord, bundle_id)
            slot = await session.get(RagArtifactSlotRecord, claim.slot_id)
            attempt = await session.get(RagArtifactAttemptRecord, claim.attempt_id)
            relation_revision = await session.scalar(
                select(AssetSourceRelationRecord.resource_revision).where(
                    AssetSourceRelationRecord.resource_id == bundle_id
                )
            )
            assert bundle is not None and bundle.revision == 2
            assert slot is not None
            assert (slot.state, slot.published_size, slot.published_sha256) == (
                "reserved",
                None,
                None,
            )
            assert attempt is not None
            assert (attempt.state, attempt.result_code, attempt.closed_at) == (
                "open",
                None,
                None,
            )
            assert relation_revision == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_rejects_duplicate_open_attempt_invalid_state_and_wrong_store_owner(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="constraints")
            repository = SqlAlchemyRagArtifactRepository(session)
            await repository.register_bundle(seed.job_id, _BINDING)
        async with sessions.begin() as session:
            claim = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                seed.job_id, ArtifactRole.PARSED, _BINDING, size=2, sha256=_DIGEST
            )
            assert isinstance(claim, ArtifactClaim)
        async with sessions() as session:
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(
                        RagArtifactAttemptRecord(
                            id=uuid4(),
                            slot_id=claim.slot_id,
                            store_id=_BINDING.store_id,
                            store_binding_id=_BINDING.binding_id,
                            temporary_key=f"rag/parsed/.duplicate.{uuid4().hex}.tmp",
                            proposed_size=2,
                            proposed_sha256=_DIGEST,
                            state="open",
                            result_code=None,
                            closed_at=None,
                        )
                    )
                    await session.flush()
            for published_size, published_sha256 in ((None, _DIGEST), (2, None)):
                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        await session.execute(
                            update(RagArtifactSlotRecord)
                            .where(RagArtifactSlotRecord.id == claim.slot_id)
                            .values(
                                state="verified",
                                published_size=published_size,
                                published_sha256=published_sha256,
                            )
                        )
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(
                        RagArtifactAttemptRecord(
                            id=uuid4(),
                            slot_id=claim.slot_id,
                            store_id="wrong_store",
                            store_binding_id=uuid4(),
                            temporary_key=f"rag/parsed/.wrong-owner.{uuid4().hex}.tmp",
                            proposed_size=2,
                            proposed_sha256=_DIGEST,
                            state="closed",
                            result_code="writer_finished",
                            closed_at=datetime.now(UTC),
                        )
                    )
                    await session.flush()
    finally:
        await engine.dispose()
