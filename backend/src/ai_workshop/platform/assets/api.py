from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile

from ai_workshop.platform.assets.schemas import (
    DocumentResponse,
    FolderCreate,
    FolderResponse,
)
from ai_workshop.platform.assets.service import AssetService, get_asset_service
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User

router = APIRouter(prefix="/api/v1", tags=["assets"])


@router.get("/workspaces/{workspace_id}/folders", response_model=list[FolderResponse])
async def list_folders(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> list[FolderResponse]:
    folders = await service.list_folders(user=user, workspace_id=workspace_id)
    return [FolderResponse.from_domain(folder) for folder in folders]


@router.post("/workspaces/{workspace_id}/folders", response_model=FolderResponse, status_code=201)
async def create_folder(
    workspace_id: UUID,
    request: FolderCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> FolderResponse:
    folder = await service.create_folder(
        user=user,
        workspace_id=workspace_id,
        parent_id=request.parent_id,
        name=request.name,
    )
    return FolderResponse.from_domain(folder)


@router.get("/workspaces/{workspace_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> list[DocumentResponse]:
    documents = await service.list_documents(user=user, workspace_id=workspace_id)
    return [DocumentResponse.from_domain(document) for document in documents]


@router.post(
    "/workspaces/{workspace_id}/documents",
    response_model=DocumentResponse,
    status_code=201,
)
async def upload_document(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AssetService, Depends(get_asset_service)],
    file: Annotated[UploadFile, File()],
    folder_id: Annotated[UUID | None, Form()] = None,
) -> DocumentResponse:
    async def content() -> AsyncIterator[bytes]:
        while chunk := await file.read(1024 * 1024):
            yield chunk

    try:
        document = await service.upload(
            user=user,
            workspace_id=workspace_id,
            folder_id=folder_id,
            filename=file.filename or "unnamed",
            media_type=file.content_type or "application/octet-stream",
            content=content(),
        )
    finally:
        await file.close()
    return DocumentResponse.from_domain(document)


@router.post(
    "/documents/{document_id}/versions",
    response_model=DocumentResponse,
    status_code=201,
)
async def upload_document_version(
    document_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AssetService, Depends(get_asset_service)],
    file: Annotated[UploadFile, File()],
) -> DocumentResponse:
    async def content() -> AsyncIterator[bytes]:
        while chunk := await file.read(1024 * 1024):
            yield chunk

    try:
        document = await service.upload_version(
            user=user,
            document_id=document_id,
            filename=file.filename or "unnamed",
            media_type=file.content_type or "application/octet-stream",
            content=content(),
        )
    finally:
        await file.close()
    return DocumentResponse.from_domain(document)
