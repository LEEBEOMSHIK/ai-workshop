from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.platform.jobs.repository import JobRepository, SqlAlchemyJobRepository
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError


@dataclass(frozen=True, slots=True)
class JobCreation:
    job: Job
    created: bool


class JobService:
    def __init__(self, repository: JobRepository) -> None:
        self.repository = repository

    async def create_asset_verification(
        self,
        *,
        user_id: UUID,
        workspace_id: UUID,
        asset_version_id: UUID,
    ) -> JobCreation:
        job_type = JobType.VERIFY_ASSET
        idempotency_key = f"asset-version:{asset_version_id}"
        existing = await self.repository.find_by_idempotency(
            user_id,
            job_type,
            idempotency_key,
        )
        if existing is not None:
            return JobCreation(existing, created=False)
        job = Job.create(
            user_id=user_id,
            workspace_id=workspace_id,
            asset_version_id=asset_version_id,
            type=job_type,
            idempotency_key=idempotency_key,
        )
        return JobCreation(await self.repository.add(job), created=True)

    async def get_for_user(self, *, user_id: UUID, job_id: UUID) -> Job:
        job = await self.repository.find_for_user(user_id, job_id)
        if job is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return job


def get_job_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JobService:
    return JobService(SqlAlchemyJobRepository(session))
