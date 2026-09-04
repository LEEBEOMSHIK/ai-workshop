from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from ai_workshop.labs.rag.policies.schemas import (
    InstallationDataPolicyCreate,
    InstallationDataPolicyResponse,
    WorkspaceDataPolicyCreate,
    WorkspaceDataPolicyResponse,
)
from ai_workshop.labs.rag.policies.service import (
    DataPolicyService,
    get_data_policy_service,
)
from ai_workshop.platform.identity.api import require_owner
from ai_workshop.platform.identity.domain import User

router = APIRouter(tags=["rag-data-policies"])


@router.get(
    "/api/v1/admin/rag/data-policies/installation",
    response_model=InstallationDataPolicyResponse,
)
async def get_installation_policy(
    _user: Annotated[User, Depends(require_owner)],
    service: Annotated[DataPolicyService, Depends(get_data_policy_service)],
) -> InstallationDataPolicyResponse:
    return InstallationDataPolicyResponse.from_domain(
        await service.current_installation()
    )


@router.post(
    "/api/v1/admin/rag/data-policies/installation/versions",
    response_model=InstallationDataPolicyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_installation_policy_version(
    request: InstallationDataPolicyCreate,
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[DataPolicyService, Depends(get_data_policy_service)],
) -> InstallationDataPolicyResponse:
    return InstallationDataPolicyResponse.from_domain(
        await service.append_installation(request, actor_id=user.id)
    )


@router.get(
    "/api/v1/admin/rag/data-policies/workspaces/{workspace_id}",
    response_model=WorkspaceDataPolicyResponse,
)
async def get_workspace_policy(
    workspace_id: UUID,
    _user: Annotated[User, Depends(require_owner)],
    service: Annotated[DataPolicyService, Depends(get_data_policy_service)],
) -> WorkspaceDataPolicyResponse:
    return WorkspaceDataPolicyResponse.from_domain(
        await service.current_workspace(workspace_id)
    )


@router.post(
    "/api/v1/admin/rag/data-policies/workspaces/{workspace_id}/versions",
    response_model=WorkspaceDataPolicyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_policy_version(
    workspace_id: UUID,
    request: WorkspaceDataPolicyCreate,
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[DataPolicyService, Depends(get_data_policy_service)],
) -> WorkspaceDataPolicyResponse:
    return WorkspaceDataPolicyResponse.from_domain(
        await service.append_workspace(workspace_id, request, actor_id=user.id)
    )
