from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.jobs.schemas import JobResponse
from ai_workshop.platform.jobs.service import JobService, get_job_service

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[JobService, Depends(get_job_service)],
) -> JobResponse:
    job = await service.get_for_user(user_id=user.id, job_id=job_id)
    return JobResponse.from_domain(job)
