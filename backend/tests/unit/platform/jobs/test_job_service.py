from uuid import UUID, uuid4

import pytest

from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.platform.jobs.repository import JobRepository
from ai_workshop.platform.jobs.service import JobService


class MemoryJobRepository(JobRepository):
    def __init__(self) -> None:
        self.jobs: list[Job] = []

    async def find_by_idempotency(
        self,
        user_id: UUID,
        type: JobType,
        idempotency_key: str,
    ) -> Job | None:
        return next(
            (
                job
                for job in self.jobs
                if job.user_id == user_id
                and job.type is type
                and job.idempotency_key == idempotency_key
            ),
            None,
        )

    async def add(self, job: Job) -> Job:
        self.jobs.append(job)
        return job

    async def find_for_user(self, user_id: UUID, job_id: UUID) -> Job | None:
        return next(
            (job for job in self.jobs if job.id == job_id and job.user_id == user_id),
            None,
        )

    async def find_by_id(self, job_id: UUID) -> Job | None:
        return next((job for job in self.jobs if job.id == job_id), None)

    async def update(self, job: Job) -> Job:
        return job


@pytest.mark.asyncio
async def test_verification_job_is_idempotent_for_user_and_asset_version() -> None:
    repository = MemoryJobRepository()
    service = JobService(repository)
    user_id = uuid4()
    workspace_id = uuid4()
    asset_version_id = uuid4()

    first = await service.create_asset_verification(
        user_id=user_id,
        workspace_id=workspace_id,
        asset_version_id=asset_version_id,
    )
    duplicate = await service.create_asset_verification(
        user_id=user_id,
        workspace_id=workspace_id,
        asset_version_id=asset_version_id,
    )

    assert first.created is True
    assert duplicate.created is False
    assert duplicate.job.id == first.job.id
    assert len(repository.jobs) == 1
