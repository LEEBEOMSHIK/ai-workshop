from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.configurations.schemas import (
    SavedRagConfigurationCreate,
    SavedRagConfigurationResponse,
)
from ai_workshop.labs.rag.configurations.service import RagConfigurationService
from ai_workshop.platform.identity.api import get_current_user, require_owner
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import get_session

router = APIRouter(prefix="/api/v1/rag/configurations", tags=["rag-configurations"])


def get_rag_configuration_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RagConfigurationService:
    from ai_workshop.labs.rag.configurations.repository import (
        SqlAlchemyRagConfigurationRepository,
    )
    from ai_workshop.labs.rag.generation.readiness import (
        SqlAlchemyGenerationReadiness,
    )
    from ai_workshop.labs.rag.ingestion.repository import (
        SqlAlchemyRagIngestionCommandRepository,
    )
    from ai_workshop.labs.rag.ingestion.service import RagIngestionService

    return RagConfigurationService(
        SqlAlchemyRagConfigurationRepository(session),
        RagIngestionService(SqlAlchemyRagIngestionCommandRepository(session)),
        generation_readiness=SqlAlchemyGenerationReadiness(session, settings),
        environment=settings.environment,
    )


@router.get("", response_model=list[SavedRagConfigurationResponse])
async def list_configurations(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RagConfigurationService, Depends(get_rag_configuration_service)],
) -> list[SavedRagConfigurationResponse]:
    configurations = await service.list(user.id)
    readiness = await service.readiness(tuple(configurations))
    return [
        SavedRagConfigurationResponse.from_domain(
            item,
            search_ready=readiness[item.version_id].search_ready,
            answer_ready=readiness[item.version_id].answer_ready,
            service_ready=readiness[item.version_id].service_ready,
            search_reasons=readiness[item.version_id].search_reasons,
            answer_reasons=readiness[item.version_id].answer_reasons,
            generation_execution_preview=(
                readiness[item.version_id].generation_execution_preview
            ),
        )
        for item in configurations
    ]


@router.post("", response_model=SavedRagConfigurationResponse, status_code=201)
async def create_configuration(
    request: SavedRagConfigurationCreate,
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[RagConfigurationService, Depends(get_rag_configuration_service)],
) -> SavedRagConfigurationResponse:
    policy = request.answer_policy
    result = await service.create(
        owner_id=user.id,
        name=request.name,
        indexing_profile_id=request.indexing_profile_id,
        retrieval_profile_id=request.retrieval_profile_id,
        generation_profile_id=request.generation_profile_id,
        answer_mode=policy.mode,
        min_semantic_score=policy.min_semantic_score,
        min_keyword_coverage=policy.min_keyword_coverage,
        require_complete_provenance=policy.require_complete_provenance,
        conflict_mode=policy.conflict_mode,
        workspace_ids=tuple(request.workspace_ids),
        external_transfer_approval=(
            request.external_transfer_approval.to_domain()
            if request.external_transfer_approval is not None
            else None
        ),
    )
    readiness = await service.readiness((result.configuration,))
    current = readiness[result.configuration.version_id]
    return SavedRagConfigurationResponse.from_domain(
        result.configuration,
        search_ready=current.search_ready,
        answer_ready=current.answer_ready,
        service_ready=current.service_ready,
        search_reasons=current.search_reasons,
        answer_reasons=current.answer_reasons,
        generation_execution_preview=current.generation_execution_preview,
    )


@router.get("/{configuration_id}", response_model=SavedRagConfigurationResponse)
async def configuration_detail(
    configuration_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RagConfigurationService, Depends(get_rag_configuration_service)],
) -> SavedRagConfigurationResponse:
    configuration = await service.detail(configuration_id, user.id)
    readiness = await service.readiness((configuration,))
    current = readiness[configuration.version_id]
    return SavedRagConfigurationResponse.from_domain(
        configuration,
        search_ready=current.search_ready,
        answer_ready=current.answer_ready,
        service_ready=current.service_ready,
        search_reasons=current.search_reasons,
        answer_reasons=current.answer_reasons,
        generation_execution_preview=current.generation_execution_preview,
    )


@router.post("/{configuration_id}/default", response_model=SavedRagConfigurationResponse)
async def promote_configuration_default(
    configuration_id: UUID,
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[RagConfigurationService, Depends(get_rag_configuration_service)],
) -> SavedRagConfigurationResponse:
    configuration = await service.promote_default(configuration_id, user.id)
    readiness = await service.readiness((configuration,))
    current = readiness[configuration.version_id]
    return SavedRagConfigurationResponse.from_domain(
        configuration,
        search_ready=current.search_ready,
        answer_ready=current.answer_ready,
        service_ready=current.service_ready,
        search_reasons=current.search_reasons,
        answer_reasons=current.answer_reasons,
        generation_execution_preview=current.generation_execution_preview,
    )
