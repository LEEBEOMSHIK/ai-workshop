"""RAG-owned admission, short writer reservations, and caller-owned finalization."""

from dataclasses import dataclass
from hashlib import sha256
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import DisconnectionError, OperationalError, SQLAlchemyError, TimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings
from ai_workshop.infrastructure.object_store.tracked import (
    ArtifactStoreError,
    TrackedLocalArtifactStore,
)
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
    RagArtifactBundleRecord,
    RagArtifactSlotRecord,
)
from ai_workshop.labs.rag.ingestion.artifact_repository import SqlAlchemyRagArtifactRepository
from ai_workshop.labs.rag.ingestion.domain import (
    ArtifactReference,
    RagIngestionBusy,
    RagIngestionError,
)
from ai_workshop.labs.rag.ingestion.locking import lock_ingestion_source
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.platform.jobs.domain import JobStatus
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository
from ai_workshop.shared.db import create_engine, create_session_factory


def _error(code: str) -> RagIngestionError:
    if code == "artifact_attempt_busy":
        return RagIngestionBusy()
    return RagIngestionError(code, code, retryable=False)


def safe_database_error(error: SQLAlchemyError) -> RagIngestionError:
    """Preserve retry classification, never SQL text, parameters, or raw causes."""
    retryable = isinstance(error, (OperationalError, TimeoutError, DisconnectionError))
    code = "database_transient" if retryable else "rag_ingestion_failed"
    return RagIngestionError(code, code, retryable=retryable)


def _configured_store(settings: Settings) -> TrackedLocalArtifactStore:
    if settings.rag_artifact_store_id is None or settings.rag_artifact_store_binding_id is None:
        raise ArtifactTrackingError("artifact_binding_missing")
    return TrackedLocalArtifactStore(
        settings.object_store_root,
        ArtifactBinding(
            settings.rag_artifact_store_id,
            settings.rag_artifact_store_binding_id,
        ),
    )


@dataclass(frozen=True, slots=True)
class ArtifactAdmission:
    binding: ArtifactBinding | None = None
    error_code: str = "artifact_binding_missing"

    def require(self) -> ArtifactBinding:
        if self.binding is None:
            raise _error(self.error_code)
        return self.binding


def prepare_artifact_admission(settings: Settings) -> ArtifactAdmission:
    """Capture marker readiness before ingestion locks without breaking legacy/read DI."""
    try:
        store = _configured_store(settings)
        store.verify_binding()
        return ArtifactAdmission(store.binding)
    except ArtifactTrackingError as exc:
        return ArtifactAdmission(error_code=exc.code)


async def _bundle(session: AsyncSession, job_id: UUID) -> RagArtifactBundleRecord | None:
    return cast(
        RagArtifactBundleRecord | None,
        await session.scalar(
            select(RagArtifactBundleRecord).where(
                RagArtifactBundleRecord.job_id == job_id,
            )
        ),
    )


async def _verified(
    session: AsyncSession,
    job_id: UUID,
    role: ArtifactRole,
    binding: ArtifactBinding,
) -> VerifiedArtifact:
    slot = await session.scalar(
        select(RagArtifactSlotRecord)
        .join(RagArtifactBundleRecord)
        .where(
            RagArtifactBundleRecord.job_id == job_id,
            RagArtifactSlotRecord.role == role.value,
        )
    )
    if (
        slot is None
        or slot.state != "verified"
        or slot.published_size is None
        or slot.published_sha256 is None
    ):
        raise ArtifactTrackingError("artifact_verified_missing")
    result = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
        job_id,
        role,
        binding,
        size=slot.published_size,
        sha256=slot.published_sha256,
    )
    if not isinstance(result, VerifiedArtifact):
        raise ArtifactTrackingError("artifact_verified_missing")
    return result


async def finalize_artifact(
    session: AsyncSession,
    job_id: UUID,
    projection_id: UUID,
    role: ArtifactRole,
    reference: ArtifactReference,
) -> None:
    """Only DB work; call after existing lifecycle/source and SQL projection mutations."""
    try:
        bundle = await _bundle(session, job_id)
        tracking = reference.tracking
        if bundle is None:
            if tracking is not None:
                raise ArtifactTrackingError("artifact_bundle_missing")
            return
        if tracking is None:
            raise ArtifactTrackingError("artifact_tracking_required")
        identity = tracking.claim if isinstance(tracking, ArtifactPublication) else tracking
        if (
            identity.job_id != job_id
            or identity.projection_id != projection_id
            or identity.bundle_id != bundle.id
            or identity.role != role
            or identity.canonical_key != reference.key
            or tracking.sha256 != reference.sha256
        ):
            raise ArtifactTrackingError("artifact_publication_mismatch")
        if isinstance(tracking, ArtifactPublication):
            await SqlAlchemyRagArtifactRepository(session).finalize(tracking)
        else:
            current = await _verified(session, job_id, role, tracking.binding)
            if current != tracking:
                raise ArtifactTrackingError("artifact_publication_mismatch")
    except ArtifactTrackingError as exc:
        raise _error(exc.code) from None
    except SQLAlchemyError as exc:
        raise safe_database_error(exc) from None


async def _lock_writer(session: AsyncSession, job_id: UUID) -> RagProjectionRecord:
    ingestion = await session.scalar(
        select(RagIngestionJobRecord)
        .where(
            RagIngestionJobRecord.job_id == job_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if ingestion is None:
        raise ArtifactTrackingError("artifact_source_invalid")
    job = await SqlAlchemyJobRepository(session).find_by_id_for_update(job_id)
    projection = await session.scalar(
        select(RagProjectionRecord)
        .where(
            RagProjectionRecord.id == ingestion.projection_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        job is None
        or projection is None
        or job.status not in {JobStatus.RUNNING, JobStatus.SUCCEEDED}
    ):
        raise ArtifactTrackingError("artifact_source_invalid")
    await lock_ingestion_source(session, ingestion.asset_version_id)
    return projection


class RagArtifactPublisher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def publish(
        self,
        job_id: UUID,
        role: ArtifactRole,
        content: bytes,
    ) -> tuple[ArtifactReference, bytes] | None:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions() as session:
                if await _bundle(session, job_id) is None:
                    return None  # Only an absent registration selects the legacy path.
            store = _configured_store(self.settings)
            store.verify_binding()  # No lifecycle or bundle lock is held during file I/O.
            async with sessions.begin() as session:
                projection = await _lock_writer(session, job_id)
                slot = await session.scalar(
                    select(RagArtifactSlotRecord)
                    .join(RagArtifactBundleRecord)
                    .where(
                        RagArtifactBundleRecord.job_id == job_id,
                        RagArtifactSlotRecord.role == role.value,
                    )
                )
                expected = {
                    ArtifactRole.PARSED: ProjectionStatus.PARSING,
                    ArtifactRole.CHUNKS: ProjectionStatus.CHUNKING,
                    ArtifactRole.EMBEDDINGS: ProjectionStatus.EMBEDDING,
                }[role]
                if slot is None or (slot.state != "verified" and projection.status != expected):
                    raise ArtifactTrackingError("artifact_stage_conflict")
                claim: ArtifactClaim | VerifiedArtifact
                if slot.state == "verified":
                    # A retry may have generated new element UUIDs. The committed
                    # canonical payload remains authoritative, as in the legacy path.
                    claim = await _verified(session, job_id, role, store.binding)
                else:
                    claim = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                        job_id,
                        role,
                        store.binding,
                        size=len(content),
                        sha256=sha256(content).hexdigest(),
                    )
            if isinstance(claim, VerifiedArtifact):
                authoritative = await store.read_verified(claim)
                return ArtifactReference(claim.canonical_key, claim.sha256, claim), authoritative
            try:
                publication, authoritative = await store.publish(claim, content)
            except ArtifactStoreError as exc:
                if exc.writer_finished and exc.temporary_absent:
                    async with sessions.begin() as session:
                        await SqlAlchemyRagArtifactRepository(session).close_failed_attempt(
                            claim, code=exc.code
                        )
                raise
            return ArtifactReference(
                claim.canonical_key, publication.sha256, publication
            ), authoritative
        except ArtifactTrackingError as exc:
            raise _error(exc.code) from None
        except SQLAlchemyError as exc:
            raise safe_database_error(exc) from None
        finally:
            await engine.dispose()

    async def read(
        self,
        job_id: UUID,
        role: ArtifactRole,
        reference: ArtifactReference,
    ) -> bytes | None:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions() as session:
                if await _bundle(session, job_id) is None:
                    if reference.tracking is not None:
                        raise ArtifactTrackingError("artifact_bundle_missing")
                    return None
            store = _configured_store(self.settings)
            async with sessions.begin() as session:
                verified = await _verified(session, job_id, role, store.binding)
                if verified.canonical_key != reference.key or verified.sha256 != reference.sha256:
                    raise ArtifactTrackingError("artifact_publication_mismatch")
            return await store.read_verified(verified)
        except ArtifactTrackingError as exc:
            raise _error(exc.code) from None
        except SQLAlchemyError as exc:
            raise safe_database_error(exc) from None
        finally:
            await engine.dispose()
