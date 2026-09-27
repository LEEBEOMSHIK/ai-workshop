from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.conversations.access import ConversationAccess
from ai_workshop.labs.rag.evaluation.generative_monitoring import GenerativeMonitoringReader
from ai_workshop.labs.rag.executions.read_repository import SqlAlchemyMonitoringRepository
from ai_workshop.labs.rag.executions.schemas import (
    ExecutionDetailResponse,
    ExecutionSearchRequest,
    ExecutionSearchResponse,
)
from ai_workshop.labs.rag.executions.service import ExecutionReadService
from ai_workshop.platform.identity.api import require_owner
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import create_engine, create_session_factory


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/admin/rag/executions", tags=["rag-executions"], dependencies=[Depends(no_store)]
)


async def get_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[ExecutionReadService]:
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        yield ExecutionReadService(
            SqlAlchemyMonitoringRepository(sessions),
            ConversationAccess(sessions),
            GenerativeMonitoringReader(sessions),
        )
    finally:
        await engine.dispose()


Actor = Annotated[User, Depends(require_owner)]
Service = Annotated[ExecutionReadService, Depends(get_service)]


@router.post("/search", response_model=ExecutionSearchResponse)
async def search(
    request: ExecutionSearchRequest, actor: Actor, service: Service
) -> ExecutionSearchResponse:
    return await service.search(actor.id, request)


@router.get("/legacy/{turn_id}", response_model=ExecutionDetailResponse)
async def legacy(turn_id: UUID, actor: Actor, service: Service) -> ExecutionDetailResponse:
    return await service.legacy(actor.id, turn_id)


@router.get("/{execution_id}", response_model=ExecutionDetailResponse)
async def detail(execution_id: UUID, actor: Actor, service: Service) -> ExecutionDetailResponse:
    return await service.detail(actor.id, execution_id)
