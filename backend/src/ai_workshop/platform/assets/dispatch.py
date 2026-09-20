from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.platform.assets.models import AssetVersionRecord
from ai_workshop.platform.jobs.domain import JobStatus, JobType
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository, _to_domain


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
            jobs = SqlAlchemyJobRepository(session)
            for record in records:
                job = _to_domain(record)
                job.status = JobStatus.RUNNING
                job.stage = "dispatching_verification"
                job.attempt += 1
                job.error_code = None
                job.error_message = None
                job.started_at = now
                job.finished_at = None
                await jobs.update(job)
                claims.append(AssetVerificationDispatchClaim(job.id, job.attempt))
        return tuple(claims)

    async def mark_send_failed(
        self,
        claim: AssetVerificationDispatchClaim,
        *,
        error: str,
    ) -> None:
        async with self.sessions.begin() as session:
            jobs = SqlAlchemyJobRepository(session)
            job = await jobs.find_by_id_for_update(claim.job_id)
            if (
                job is None
                or job.status is not JobStatus.RUNNING
                or job.stage != "dispatching_verification"
                or job.attempt != claim.attempt
            ):
                return
            job.status = JobStatus.QUEUED
            job.stage = "verification_dispatch_retry"
            job.error_code = "verification_dispatch_failed"
            job.error_message = "The verification task could not be dispatched."
            job.started_at = None
            job.finished_at = None
            await jobs.update(job)
