from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from ai_workshop.platform.assets.intake_service import (
    HttpUploadIntakeService,
    get_upload_intake_service,
)
from ai_workshop.platform.assets.library_api import router as library_router
from ai_workshop.platform.assets.movement import AssetMovementService, get_asset_movement_service
from ai_workshop.platform.assets.originals_api import router as originals_router
from ai_workshop.platform.assets.schemas import (
    AssetMoveRequest,
    AssetVersionResponse,
    DocumentMoveResponse,
    DocumentResponse,
    FolderCreate,
    FolderMoveResponse,
    FolderResponse,
)
from ai_workshop.platform.assets.service import (
    AssetService,
    get_asset_service,
)
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.worker import CeleryJobDispatcher, get_job_dispatcher

router = APIRouter(prefix="/api/v1", tags=["assets"])
router.include_router(library_router)
router.include_router(originals_router)


def _upload_schema(*, folder: bool) -> dict[str, object]:
    properties = {"file": {"type": "string", "format": "binary"}}
    if folder:
        properties["folder_id"] = {"type": "string", "format": "uuid"}
    return {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {"type": "object", "required": ["file"], "properties": properties}
                }
            },
        }
    }


@router.post("/workspaces/{workspace_id}/documents/{document_id}/move")
async def move_document(
    workspace_id: UUID,
    document_id: UUID,
    request: AssetMoveRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AssetMovementService, Depends(get_asset_movement_service)],
) -> DocumentMoveResponse:
    document, changed = await service.move_document(
        user=user,
        workspace_id=workspace_id,
        document_id=document_id,
        destination_folder_id=request.destination_folder_id,
        expected_revision=request.expected_revision,
    )
    return DocumentMoveResponse(
        id=document.id,
        workspace_id=document.workspace_id,
        name=document.name,
        folder_id=document.folder_id,
        metadata_revision=document.metadata_revision,
        changed=changed,
    )


@router.post("/workspaces/{workspace_id}/folders/{folder_id}/move")
async def move_folder(
    workspace_id: UUID,
    folder_id: UUID,
    request: AssetMoveRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AssetMovementService, Depends(get_asset_movement_service)],
) -> FolderMoveResponse:
    folder, changed = await service.move_folder(
        user=user,
        workspace_id=workspace_id,
        folder_id=folder_id,
        destination_folder_id=request.destination_folder_id,
        expected_revision=request.expected_revision,
    )
    return FolderMoveResponse(
        id=folder.id,
        workspace_id=folder.workspace_id,
        name=folder.name,
        parent_id=folder.parent_id,
        metadata_revision=folder.metadata_revision,
        changed=changed,
    )


@router.get(
    "/documents/{document_id}/versions",
    response_model=list[AssetVersionResponse],
)
async def list_document_versions(
    document_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> list[AssetVersionResponse]:
    versions = await service.list_versions(user=user, document_id=document_id)
    return [AssetVersionResponse.from_domain(version) for version in versions]


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
    openapi_extra=_upload_schema(folder=True),
)
async def upload_document(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    intakes: Annotated[HttpUploadIntakeService, Depends(get_upload_intake_service)],
    dispatcher: Annotated[CeleryJobDispatcher, Depends(get_job_dispatcher)],
    background_tasks: BackgroundTasks,
    request: Request,
) -> DocumentResponse:
    result = await intakes.upload(
        user=user,
        workspace_id=workspace_id,
        stream=request.stream(),
        content_type=request.headers.get("content-type", ""),
    )
    if result.job_created:
        background_tasks.add_task(dispatcher.verify_asset, result.job.id)
    return DocumentResponse.from_domain(result.document, job_id=result.job.id)


@router.post(
    "/documents/{document_id}/versions",
    response_model=DocumentResponse,
    status_code=201,
    openapi_extra=_upload_schema(folder=False),
)
async def upload_document_version(
    document_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    intakes: Annotated[HttpUploadIntakeService, Depends(get_upload_intake_service)],
    dispatcher: Annotated[CeleryJobDispatcher, Depends(get_job_dispatcher)],
    background_tasks: BackgroundTasks,
    request: Request,
) -> DocumentResponse:
    result = await intakes.upload(
        user=user,
        document_id=document_id,
        stream=request.stream(),
        content_type=request.headers.get("content-type", ""),
    )
    if result.job_created:
        background_tasks.add_task(dispatcher.verify_asset, result.job.id)
    return DocumentResponse.from_domain(result.document, job_id=result.job.id)
