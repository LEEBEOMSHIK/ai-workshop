from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.comparisons.http import ComparisonRoute
from ai_workshop.labs.rag.comparisons.repository import SqlComparisonRepository
from ai_workshop.labs.rag.comparisons.schemas import (
    MAX_IMPORT_BYTES,
    ComparisonDetail,
    ComparisonImport,
    ComparisonList,
)
from ai_workshop.labs.rag.comparisons.service import ComparisonService
from ai_workshop.platform.identity.api import require_owner
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError

router = APIRouter(
    prefix="/api/v1/admin/rag/comparisons",
    tags=["rag-comparisons"],
    route_class=ComparisonRoute,
)
Actor = Annotated[User, Depends(require_owner)]
Session = Annotated[AsyncSession, Depends(get_session)]


def get_service(session: Session) -> ComparisonService:
    repository = SqlComparisonRepository(session)
    return ComparisonService(repository, repository)


Service = Annotated[ComparisonService, Depends(get_service)]


async def require_import(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if (
        request.headers.get("origin") not in settings.publishing_allowed_admin_origins
        or request.headers.get("x-comparison-request") != "1"
    ):
        raise AppError("comparison_request_forbidden", "The comparison request is forbidden.", 403)
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise AppError("comparison_json_required", "Comparison imports require JSON.", 415)
    if len(await request.body()) > MAX_IMPORT_BYTES:
        raise AppError("comparison_too_large", "The comparison file is too large.", 413)


@router.get("", response_model=ComparisonList)
async def list_comparisons(actor: Actor, service: Service) -> ComparisonList:
    return await service.list(actor.id)


@router.get("/{comparison_id}", response_model=ComparisonDetail)
async def detail(comparison_id: UUID, actor: Actor, service: Service) -> ComparisonDetail:
    return await service.detail(actor.id, comparison_id)


@router.post("", response_model=ComparisonDetail, dependencies=[Depends(require_import)])
async def import_comparison(
    report: ComparisonImport,
    actor: Actor,
    service: Service,
    session: Session,
) -> ComparisonDetail:
    result = await service.import_report(actor.id, report)
    await session.commit()
    return result
