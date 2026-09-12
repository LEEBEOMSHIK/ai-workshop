from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ai_workshop.platform.assets.library import LibraryService, get_library_service
from ai_workshop.platform.assets.schemas import (
    AssetVersionPageResponse,
    AssetVersionResponse,
    DocumentResponse,
    LibraryPageResponse,
)
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User

router = APIRouter(prefix="/workspaces/{workspace_id}/library", tags=["assets"])


@router.get("", response_model=LibraryPageResponse)
async def browse_library(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LibraryService, Depends(get_library_service)],
    folder_id: UUID | None = None,
    folder_cursor: Annotated[str | None, Query(max_length=4096)] = None,
    document_cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> LibraryPageResponse:
    page = await service.browse(
        user=user,
        workspace_id=workspace_id,
        folder_id=folder_id,
        folder_cursor=folder_cursor,
        document_cursor=document_cursor,
        limit=limit,
    )
    return LibraryPageResponse.from_domain(page)


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_library_document(
    workspace_id: UUID,
    document_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LibraryService, Depends(get_library_service)],
) -> DocumentResponse:
    document = await service.document(
        user=user,
        workspace_id=workspace_id,
        document_id=document_id,
    )
    return DocumentResponse.from_domain(document)


@router.get("/documents/{document_id}/versions", response_model=AssetVersionPageResponse)
async def list_library_document_versions(
    workspace_id: UUID,
    document_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LibraryService, Depends(get_library_service)],
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> AssetVersionPageResponse:
    page = await service.versions(
        user=user,
        workspace_id=workspace_id,
        document_id=document_id,
        cursor=cursor,
        limit=limit,
    )
    return AssetVersionPageResponse(
        items=[AssetVersionResponse.from_domain(version) for version in page.items],
        next_cursor=page.next_cursor,
    )
