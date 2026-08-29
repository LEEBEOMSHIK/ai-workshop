from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.jobs.domain import Job, JobStatus, JobType
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord


class JobRepository(Protocol):
    async def find_by_idempotency(
        self,
        user_id: UUID,
        type: JobType,
        idempotency_key: str,
    ) -> Job | None: ...

    async def add(self, job: Job) -> Job: ...

    async def find_for_user(self, user_id: UUID, job_id: UUID) -> Job | None: ...

    async def find_by_id(self, job_id: UUID) -> Job | None: ...

    async def update(self, job: Job) -> Job: ...


def _to_domain(record: JobRecord) -> Job:
    return Job(
        id=record.id,
        user_id=record.user_id,
        workspace_id=record.workspace_id,
        asset_version_id=record.asset_version_id,
        type=JobType(record.type),
        idempotency_key=record.idempotency_key,
        status=JobStatus(record.status),
        stage=record.stage,
        attempt=record.attempt,
        error_code=record.error_code,
        error_message=record.error_message,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


class SqlAlchemyJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_idempotency(
        self,
        user_id: UUID,
        type: JobType,
        idempotency_key: str,
    ) -> Job | None:
        result = await self.session.execute(
            select(JobRecord).where(
                JobRecord.user_id == user_id,
                JobRecord.type == type,
                JobRecord.idempotency_key == idempotency_key,
            )
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record else None

    async def add(self, job: Job) -> Job:
        record = JobRecord(
            id=job.id,
            user_id=job.user_id,
            workspace_id=job.workspace_id,
            asset_version_id=job.asset_version_id,
            type=job.type,
            idempotency_key=job.idempotency_key,
            status=job.status,
            stage=job.stage,
            attempt=job.attempt,
            error_code=job.error_code,
            error_message=job.error_message,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
        self.session.add(record)
        await self.session.flush()
        return _to_domain(record)

    async def find_for_user(self, user_id: UUID, job_id: UUID) -> Job | None:
        result = await self.session.execute(
            select(JobRecord)
            .join(
                WorkspaceMembershipRecord,
                WorkspaceMembershipRecord.workspace_id == JobRecord.workspace_id,
            )
            .where(
                JobRecord.id == job_id,
                WorkspaceMembershipRecord.user_id == user_id,
            )
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record else None

    async def find_by_id(self, job_id: UUID) -> Job | None:
        record = await self.session.get(JobRecord, job_id)
        return _to_domain(record) if record else None

    async def update(self, job: Job) -> Job:
        record = await self.session.get(JobRecord, job.id)
        if record is None:
            raise LookupError("Job does not exist.")
        record.status = job.status
        record.stage = job.stage
        record.attempt = job.attempt
        record.error_code = job.error_code
        record.error_message = job.error_message
        record.started_at = job.started_at
        record.finished_at = job.finished_at
        await self.session.flush()
        return _to_domain(record)
