from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from ai_workshop.platform.jobs.domain import Job, JobStatus, JobType


class JobResponse(BaseModel):
    id: UUID
    type: JobType
    status: JobStatus
    stage: str
    attempt: int
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_domain(cls, job: Job) -> "JobResponse":
        return cls(
            id=job.id,
            type=job.type,
            status=job.status,
            stage=job.stage,
            attempt=job.attempt,
            error_code=job.error_code,
            error_message=job.error_message,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
