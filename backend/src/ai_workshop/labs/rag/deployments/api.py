from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from ai_workshop.labs.rag.deployments.schemas import (
    DeploymentAdminResponse,
    DeploymentOptionResponse,
    DeploymentVersionCreate,
)
from ai_workshop.labs.rag.deployments.service import (
    DeploymentRegistryService,
    get_deployment_registry_service,
)
from ai_workshop.platform.identity.api import get_current_user, require_owner
from ai_workshop.platform.identity.domain import User

router = APIRouter(tags=["rag-deployments"])


@router.post(
    "/api/v1/admin/rag/deployments",
    response_model=DeploymentAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_deployment(
    request: DeploymentVersionCreate,
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[DeploymentRegistryService, Depends(get_deployment_registry_service)],
) -> DeploymentAdminResponse:
    entry = await service.create_identity(request, actor_id=user.id)
    return DeploymentAdminResponse.from_entry(
        entry,
        secret_configured=service.secret_configured(entry),
    )


@router.post(
    "/api/v1/admin/rag/deployments/{deployment_id}/versions",
    response_model=DeploymentAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_deployment_version(
    deployment_id: UUID,
    request: DeploymentVersionCreate,
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[DeploymentRegistryService, Depends(get_deployment_registry_service)],
) -> DeploymentAdminResponse:
    entry = await service.create_version(deployment_id, request, actor_id=user.id)
    return DeploymentAdminResponse.from_entry(
        entry,
        secret_configured=service.secret_configured(entry),
    )


@router.get(
    "/api/v1/admin/rag/deployments",
    response_model=list[DeploymentAdminResponse],
)
async def list_admin_deployments(
    _user: Annotated[User, Depends(require_owner)],
    service: Annotated[DeploymentRegistryService, Depends(get_deployment_registry_service)],
) -> list[DeploymentAdminResponse]:
    return [
        DeploymentAdminResponse.from_entry(
            item,
            secret_configured=service.secret_configured(item),
        )
        for item in await service.list_versions()
    ]


@router.get(
    "/api/v1/rag/deployments/options",
    response_model=list[DeploymentOptionResponse],
)
async def list_deployment_options(
    _user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DeploymentRegistryService, Depends(get_deployment_registry_service)],
) -> list[DeploymentOptionResponse]:
    return [
        DeploymentOptionResponse.from_entry(item)
        for item in await service.list_versions()
    ]
