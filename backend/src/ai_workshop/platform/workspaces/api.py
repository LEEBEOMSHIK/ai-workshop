from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.workspaces.domain import WorkspaceGrants
from ai_workshop.platform.workspaces.member_repository import SqlAlchemyWorkspaceMemberRepository
from ai_workshop.platform.workspaces.schemas import (
    WorkspaceCapabilitiesResponse,
    WorkspaceCreate,
    WorkspaceMemberPage,
    WorkspaceMemberPut,
    WorkspaceMemberResponse,
    WorkspaceResponse,
)
from ai_workshop.platform.workspaces.service import (
    WorkspaceService,
    get_workspace_member_repository,
    get_workspace_service,
)

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


@router.get("/{workspace_id}/capabilities", response_model=WorkspaceCapabilitiesResponse)
async def workspace_capabilities(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        SqlAlchemyWorkspaceMemberRepository, Depends(get_workspace_member_repository)
    ],
) -> WorkspaceCapabilitiesResponse:
    return WorkspaceCapabilitiesResponse.model_validate(
        await repository.capabilities(user.id, workspace_id)
    )


@router.get("/{workspace_id}/members", response_model=WorkspaceMemberPage)
async def workspace_members(
    workspace_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        SqlAlchemyWorkspaceMemberRepository, Depends(get_workspace_member_repository)
    ],
    after: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> WorkspaceMemberPage:
    members, next_after = await repository.list_members(
        user.id, workspace_id, after=after, limit=limit
    )
    return WorkspaceMemberPage(
        items=[WorkspaceMemberResponse.model_validate(item) for item in members],
        next_after=next_after,
    )


@router.put("/{workspace_id}/members/{user_id}", response_model=WorkspaceMemberResponse)
async def put_workspace_member(
    workspace_id: UUID,
    user_id: UUID,
    request: WorkspaceMemberPut,
    user: Annotated[User, Depends(get_current_user)],
    repository: Annotated[
        SqlAlchemyWorkspaceMemberRepository, Depends(get_workspace_member_repository)
    ],
) -> WorkspaceMemberResponse:
    member = await repository.put_member(
        user.id,
        workspace_id,
        user_id,
        grants=WorkspaceGrants(request.read, request.write, request.delete),
        expected_revision=request.expected_revision,
    )
    return WorkspaceMemberResponse.model_validate(member)
