from typing import Annotated

from fastapi import APIRouter, Depends

from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.workspaces.schemas import WorkspaceCreate, WorkspaceResponse
from ai_workshop.platform.workspaces.service import WorkspaceService, get_workspace_service

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> list[WorkspaceResponse]:
    return [WorkspaceResponse.from_domain(item) for item in await service.list_for(user)]


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    request: WorkspaceCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    item = await service.create(
        name=request.name, kind=request.kind, creator=user, expires_at=request.expires_at
    )
    return WorkspaceResponse.from_domain(item)
