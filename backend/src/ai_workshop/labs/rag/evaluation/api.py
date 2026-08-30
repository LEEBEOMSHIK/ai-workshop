from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.evaluation.schemas import (
    EvaluationPolicyCreate,
    EvaluationPolicyResponse,
    EvaluationRunCreate,
    EvaluationRunResponse,
)
from ai_workshop.labs.rag.evaluation.service import EvaluationApplicationService
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import get_session

router = APIRouter(prefix="/api/v1/rag", tags=["rag-evaluation"])


def get_evaluation_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EvaluationApplicationService:
    from ai_workshop.labs.rag.evaluation.repository import (
        SqlAlchemyEvaluationApplicationRepository,
    )

    return EvaluationApplicationService(
        SqlAlchemyEvaluationApplicationRepository(session), commit=session.commit
    )


@router.post(
    "/evaluation-policies",
    response_model=EvaluationPolicyResponse,
    status_code=201,
)
async def create_evaluation_policy(
    request: EvaluationPolicyCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[EvaluationApplicationService, Depends(get_evaluation_service)],
) -> EvaluationPolicyResponse:
    return EvaluationPolicyResponse.from_domain(
        await service.create_policy(actor_id=user.id, **request.model_dump())
    )


@router.post(
    "/evaluation-runs",
    response_model=EvaluationRunResponse,
    status_code=202,
)
async def start_evaluation_run(
    request: EvaluationRunCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[EvaluationApplicationService, Depends(get_evaluation_service)],
) -> EvaluationRunResponse:
    values = request.model_dump()
    values["configuration_version_ids"] = tuple(request.configuration_version_ids)
    return EvaluationRunResponse.from_domain(
        await service.start_run(actor_id=user.id, **values)
    )


@router.get("/evaluation-runs", response_model=list[EvaluationRunResponse])
async def list_evaluation_runs(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[EvaluationApplicationService, Depends(get_evaluation_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[EvaluationRunResponse]:
    return [
        EvaluationRunResponse.from_domain(item)
        for item in await service.list(user.id, limit)
    ]


@router.get("/evaluation-runs/{run_id}", response_model=EvaluationRunResponse)
async def evaluation_run_detail(
    run_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[EvaluationApplicationService, Depends(get_evaluation_service)],
) -> EvaluationRunResponse:
    return EvaluationRunResponse.from_domain(await service.detail(run_id, user.id))
