from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.platform.assets.models import AssetVersionRecord
from ai_workshop.platform.jobs.domain import JobStatus, JobType
from ai_workshop.platform.jobs.models import JobRecord


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AssetVerificationDispatchClaim:
    job_id: UUID
    attempt: int


@dataclass(frozen=True, slots=True)
class AssetVerificationDispatchResult:
    claimed: int
    sent: int
    failed: int


class AssetVerificationDispatchRepositoryPort(Protocol):
    async def claim_recoverable(
        self,
        *,
        now: datetime,
        stale_before: datetime,
        limit: int,
        job_id: UUID | None = None,
    ) -> Sequence[AssetVerificationDispatchClaim]: ...

    async def mark_send_failed(
        self,
        claim: AssetVerificationDispatchClaim,
        *,
        error: str,
    ) -> None: ...


class AssetVerificationJobSenderPort(Protocol):
    def send(self, job_id: UUID) -> None: ...


class AssetVerificationDispatchReconciler:
    def __init__(
        self,
        repository: AssetVerificationDispatchRepositoryPort,
        sender: AssetVerificationJobSenderPort,
        *,
        stale_after: timedelta = timedelta(minutes=2),
        batch_size: int = 100,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.repository = repository
        self.sender = sender
        self.stale_after = stale_after
        self.batch_size = batch_size
        self.clock = clock

    async def run_once(
        self,
        *,
        now: datetime | None = None,
        job_id: UUID | None = None,
    ) -> AssetVerificationDispatchResult:
        dispatch_time = now or self.clock()
        claims = await self.repository.claim_recoverable(
            now=dispatch_time,
            stale_before=dispatch_time - self.stale_after,
            limit=1 if job_id is not None else self.batch_size,
            job_id=job_id,
        )
        sent = 0
        failed = 0
        for claim in claims:
            try:
                self.sender.send(claim.job_id)
            except Exception as exc:
                failed += 1
                await self.repository.mark_send_failed(claim, error=str(exc))
            else:
                sent += 1
        return AssetVerificationDispatchResult(len(claims), sent, failed)


class SqlAlchemyAssetVerificationDispatchRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def claim_recoverable(
        self,
        *,
        now: datetime,
        stale_before: datetime,
        limit: int,
        job_id: UUID | None = None,
    ) -> tuple[AssetVerificationDispatchClaim, ...]:
        async with self.sessions.begin() as session:
            statement = (
                select(JobRecord)
                .join(
                    AssetVersionRecord,
                    AssetVersionRecord.id == JobRecord.asset_version_id,
                )
                .where(
                    JobRecord.type == JobType.VERIFY_ASSET,
                    or_(
                        JobRecord.status == JobStatus.QUEUED,
                        and_(
                            JobRecord.status == JobStatus.RUNNING,
                            JobRecord.started_at <= stale_before,
                        ),
                        and_(
                            JobRecord.status == JobStatus.SUCCEEDED,
                            JobRecord.stage == "stored",
                            AssetVersionRecord.status == "stored",
                        ),
                    ),
                )
                .order_by(JobRecord.created_at, JobRecord.id)
                .limit(limit)
                .with_for_update(of=JobRecord, skip_locked=True)
            )
            if job_id is not None:
                statement = statement.where(JobRecord.id == job_id)
            records = (await session.scalars(statement)).all()
            claims: list[AssetVerificationDispatchClaim] = []
            for record in records:
                record.status = JobStatus.RUNNING
                record.stage = "dispatching_verification"
                record.attempt += 1
                record.error_code = None
                record.error_message = None
                record.started_at = now
                record.finished_at = None
                claims.append(AssetVerificationDispatchClaim(record.id, record.attempt))
            await session.flush()
        return tuple(claims)

    async def mark_send_failed(
        self,
        claim: AssetVerificationDispatchClaim,
        *,
        error: str,
    ) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(JobRecord)
                .where(
                    JobRecord.id == claim.job_id,
                    JobRecord.status == JobStatus.RUNNING,
                    JobRecord.stage == "dispatching_verification",
                    JobRecord.attempt == claim.attempt,
                )
                .values(
                    status=JobStatus.QUEUED,
                    stage="verification_dispatch_retry",
                    error_code="verification_dispatch_failed",
                    error_message=error[:500],
                    started_at=None,
                    finished_at=None,
                )
            )
