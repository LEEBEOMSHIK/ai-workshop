from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import get_settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits, AuthoringService
from ai_workshop.labs.rag.evaluation.authoring_repository import SqlAlchemyAuthoringRepository
from ai_workshop.labs.rag.evaluation.authoring_schemas import (
    AuthoringDocumentsRequest,
    AuthoringDocumentsResponse,
    AuthoringPreview,
    AuthoringRunRequest,
    AuthoringScope,
)
from ai_workshop.labs.rag.evaluation.repository import SqlAlchemyEvaluationApplicationRepository
from ai_workshop.labs.rag.evaluation.schemas import EvaluationRunResponse
from ai_workshop.labs.rag.evaluation.service import EvaluationApplicationService
from ai_workshop.labs.rag.retrieval.elasticsearch import ElasticsearchFrozenIndexInspector
from ai_workshop.platform.identity.api import require_owner
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import get_session

router = APIRouter(prefix="/api/v1/rag/evaluation-authoring", tags=["rag-evaluation"])


async def get_authoring_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[AuthoringService]:
    settings = get_settings()
    limits = AuthoringLimits(
        max_documents=settings.evaluation_authoring_max_documents,
        max_evidence_units=settings.evaluation_authoring_max_evidence_units,
        max_response_bytes=settings.evaluation_authoring_max_response_bytes,
        max_cases=settings.evaluation_authoring_max_cases,
    )
    elasticsearch = create_elasticsearch(settings)
    try:
        inspector = ElasticsearchFrozenIndexInspector(elasticsearch)
        yield AuthoringService(
            SqlAlchemyAuthoringRepository(session, inspector=inspector, limits=limits),
            EvaluationApplicationService(
                SqlAlchemyEvaluationApplicationRepository(session, index_inspector=inspector),
                commit=session.commit,
            ),
            limits=limits,
            rollback=session.rollback,
        )
    finally:
        await elasticsearch.close()


@router.post("/documents", response_model=AuthoringDocumentsResponse)
async def authoring_documents(
    request: AuthoringDocumentsRequest,
    response: Response,
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[AuthoringService, Depends(get_authoring_service)],
) -> AuthoringDocumentsResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.documents(user.id, request)


@router.post("/preview", response_model=AuthoringPreview)
async def authoring_preview(
    request: AuthoringScope,
    response: Response,
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[AuthoringService, Depends(get_authoring_service)],
) -> AuthoringPreview:
    response.headers["Cache-Control"] = "no-store"
    return await service.preview(user.id, request)


@router.post("/runs", response_model=EvaluationRunResponse, status_code=202)
async def authoring_run(
    request: AuthoringRunRequest,
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[AuthoringService, Depends(get_authoring_service)],
) -> EvaluationRunResponse:
    return EvaluationRunResponse.from_domain(await service.run(user.id, request))
