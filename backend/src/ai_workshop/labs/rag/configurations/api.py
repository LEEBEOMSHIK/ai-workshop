from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.configurations.schemas import (
    SavedRagConfigurationCreate,
    SavedRagConfigurationResponse,
)
from ai_workshop.labs.rag.configurations.service import RagConfigurationService
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import get_session

router = APIRouter(prefix="/api/v1/rag/configurations", tags=["rag-configurations"])


def get_rag_configuration_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RagConfigurationService:
    from ai_workshop.labs.rag.configurations.repository import (
        SqlAlchemyRagConfigurationRepository,
    )
    from ai_workshop.labs.rag.ingestion.repository import (
        SqlAlchemyRagIngestionCommandRepository,
    )
    from ai_workshop.labs.rag.ingestion.service import RagIngestionService

    return RagConfigurationService(
        SqlAlchemyRagConfigurationRepository(session),
        RagIngestionService(SqlAlchemyRagIngestionCommandRepository(session)),
        commit=session.commit,
    )


@router.get("", response_model=list[SavedRagConfigurationResponse])
async def list_configurations(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RagConfigurationService, Depends(get_rag_configuration_service)],
) -> list[SavedRagConfigurationResponse]:
    return [
        SavedRagConfigurationResponse.from_domain(item)
        for item in await service.list(user.id)
    ]


@router.post("", response_model=SavedRagConfigurationResponse, status_code=201)
async def create_configuration(
    request: SavedRagConfigurationCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RagConfigurationService, Depends(get_rag_configuration_service)],
) -> SavedRagConfigurationResponse:
    policy = request.answer_policy
    result = await service.create(
        owner_id=user.id,
        name=request.name,
        indexing_profile_id=request.indexing_profile_id,
        retrieval_profile_id=request.retrieval_profile_id,
        generation_profile_id=request.generation_profile_id,
        min_semantic_score=policy.min_semantic_score,
        min_keyword_coverage=policy.min_keyword_coverage,
        require_complete_provenance=policy.require_complete_provenance,
        conflict_mode=policy.conflict_mode,
        workspace_ids=tuple(request.workspace_ids),
    )
    return SavedRagConfigurationResponse.from_domain(result.configuration)


@router.get("/{configuration_id}", response_model=SavedRagConfigurationResponse)
async def configuration_detail(
    configuration_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RagConfigurationService, Depends(get_rag_configuration_service)],
) -> SavedRagConfigurationResponse:
    return SavedRagConfigurationResponse.from_domain(
        await service.detail(configuration_id, user.id)
    )


@router.post("/{configuration_id}/default", response_model=SavedRagConfigurationResponse)
async def promote_configuration_default(
    configuration_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RagConfigurationService, Depends(get_rag_configuration_service)],
) -> SavedRagConfigurationResponse:
    return SavedRagConfigurationResponse.from_domain(
        await service.promote_default(configuration_id, user.id)
    )
