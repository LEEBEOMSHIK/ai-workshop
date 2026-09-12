from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.domains.library import DomainLibraryService
from ai_workshop.labs.rag.domains.repository import (
    SqlAlchemyDomainConfigurationProvider,
    SqlAlchemyDomainRepository,
)
from ai_workshop.labs.rag.domains.schemas import DomainLibraryResponse
from ai_workshop.labs.rag.domains.service import DomainService
from ai_workshop.platform.assets.library import get_library_service
from ai_workshop.platform.assets.schemas import DocumentResponse, LibraryPageResponse
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import get_session

router = APIRouter(prefix="/{slug}/library")


def get_domain_library_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DomainLibraryService:
    domains = DomainService(
        SqlAlchemyDomainRepository(session),
        SqlAlchemyDomainConfigurationProvider(session, settings),
    )
    return DomainLibraryService(
        domains,
        get_library_service(session, settings),
        selection_limit=settings.rag_selected_documents_max_count,
    )


@router.get("", response_model=DomainLibraryResponse)
async def get_domain_library(
    slug: str,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DomainLibraryService, Depends(get_domain_library_service)],
) -> DomainLibraryResponse:
    context = await service.resolve(slug=slug, actor_id=user.id)
    return DomainLibraryResponse.from_domain(
        context,
        selection_limit=service.selection_limit,
    )


@router.get(
    "/workspaces/{workspace_id}",
    response_model=LibraryPageResponse,
)
async def browse_domain_library(
    slug: str,
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DomainLibraryService, Depends(get_domain_library_service)],
    folder_id: UUID | None = None,
    folder_cursor: Annotated[str | None, Query(max_length=4096)] = None,
    document_cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> LibraryPageResponse:
    page = await service.browse(
        slug=slug,
        user=user,
        workspace_id=workspace_id,
        folder_id=folder_id,
        folder_cursor=folder_cursor,
        document_cursor=document_cursor,
        limit=limit,
    )
    return LibraryPageResponse.from_domain(page)


@router.get(
    "/workspaces/{workspace_id}/documents/{document_id}",
    response_model=DocumentResponse,
)
async def get_domain_library_document(
    slug: str,
    workspace_id: UUID,
    document_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DomainLibraryService, Depends(get_domain_library_service)],
) -> DocumentResponse:
    document = await service.document(
        slug=slug,
        user=user,
        workspace_id=workspace_id,
        document_id=document_id,
    )
    return DocumentResponse.from_domain(document)
