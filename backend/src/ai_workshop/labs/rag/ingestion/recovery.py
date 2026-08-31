from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.labs.rag.ingestion.locking import lock_ingestion_source
from ai_workshop.labs.rag.ingestion.models import (
    RagIngestionDispatchRecord,
    RagIngestionJobRecord,
)
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.jobs.domain import JobStatus
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository


@dataclass(frozen=True, slots=True)
class InactiveRagIngestionResult:
    claimed: int
    terminalized: int


class SqlAlchemyInactiveRagIngestionReconciler:
    """Converge inactive nonterminal ingestion state in lifecycle lock order."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def run_once(self, *, limit: int = 100) -> InactiveRagIngestionResult:
        async with self.sessions.begin() as session:
            candidates = list(
                await session.scalars(
                    select(RagIngestionJobRecord)
                    .join(JobRecord, JobRecord.id == RagIngestionJobRecord.job_id)
                    .join(
                        RagProjectionRecord,
                        RagProjectionRecord.id == RagIngestionJobRecord.projection_id,
                    )
                    .join(
                        AssetVersionRecord,
                        AssetVersionRecord.id == RagIngestionJobRecord.asset_version_id,
                    )
                    .join(
                        DocumentRecord,
                        DocumentRecord.id == AssetVersionRecord.document_id,
                    )
                    .where(
                        JobRecord.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
                        RagProjectionRecord.status.not_in(
                            (
                                ProjectionStatus.READY,
                                ProjectionStatus.PARTIAL_READY,
                                ProjectionStatus.FAILED,
                            )
                        ),
                        or_(
                            AssetVersionRecord.status != VersionStatus.READY,
                            DocumentRecord.active_version_id.is_(None),
                            DocumentRecord.active_version_id != AssetVersionRecord.id,
                        ),
                    )
                    .order_by(RagIngestionJobRecord.created_at)
                    .limit(limit)
                    .with_for_update(of=RagIngestionJobRecord, skip_locked=True)
                )
            )
            terminalized = 0
            for ingestion in candidates:
                if await self._terminalize(session, ingestion):
                    terminalized += 1
            return InactiveRagIngestionResult(len(candidates), terminalized)

    async def _terminalize(
        self,
        session: AsyncSession,
        ingestion: RagIngestionJobRecord,
    ) -> bool:
        jobs = SqlAlchemyJobRepository(session)
        job = await jobs.find_by_id_for_update(ingestion.job_id)
        projection = await session.scalar(
            select(RagProjectionRecord)
            .where(RagProjectionRecord.id == ingestion.projection_id)
            .with_for_update()
        )
        if job is None or projection is None:
            return False
        source = await lock_ingestion_source(
            session,
            ingestion.asset_version_id,
            require_active=False,
        )
        if (
            VersionStatus(source.asset.status) is VersionStatus.READY
            and source.document.active_version_id == source.asset.id
        ):
            return False
        if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING} or ProjectionStatus(
            projection.status
        ) in {
            ProjectionStatus.READY,
            ProjectionStatus.PARTIAL_READY,
            ProjectionStatus.FAILED,
        }:
            return False
        dispatch = await session.scalar(
            select(RagIngestionDispatchRecord)
            .where(RagIngestionDispatchRecord.job_id == ingestion.job_id)
            .with_for_update()
        )
        if job.status is JobStatus.QUEUED:
            job.start(stage="terminalizing_inactive_source")
        job.fail(
            error_code="index_source_inactive",
            error_message="The RAG ingestion source is no longer the active READY version.",
        )
        await jobs.update(job)
        projection.status = ProjectionStatus.FAILED
        if dispatch is not None and dispatch.status != "cancelled":
            dispatch.status = "cancelled"
            dispatch.claimed_at = None
            dispatch.claim_token = None
            dispatch.sent_at = None
            dispatch.cancelled_at = datetime.now(UTC)
        await session.flush()
        return True
