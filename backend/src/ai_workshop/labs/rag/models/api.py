from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from ai_workshop.labs.rag.models.domain import ProfileKind
from ai_workshop.labs.rag.models.schemas import (
    ModelCreate,
    ModelResponse,
    ProfileCreate,
    ProfileResponse,
    ProfileYamlRequest,
)
from ai_workshop.labs.rag.models.service import (
    RagModelRegistryService,
    get_rag_model_registry_service,
)
from ai_workshop.platform.identity.api import get_current_user, require_owner
from ai_workshop.platform.identity.domain import User

router = APIRouter(prefix="/api/v1/rag", tags=["rag-models"])


@router.get("/models", response_model=list[ModelResponse])
async def list_models(
    _user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RagModelRegistryService, Depends(get_rag_model_registry_service)],
) -> list[ModelResponse]:
    return [ModelResponse.from_domain(item) for item in await service.list_models()]


@router.post(
    "/models",
    response_model=ModelResponse,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
async def register_model(
    request: ModelCreate,
    _user: Annotated[User, Depends(require_owner)],
    service: Annotated[RagModelRegistryService, Depends(get_rag_model_registry_service)],
) -> ModelResponse:
    model = await service.register_model(
        kind=request.kind,
        name=request.name,
        version=request.version,
        config=request.config,
    )
    return ModelResponse.from_domain(model)


@router.get("/profiles/{kind}", response_model=list[ProfileResponse])
async def list_profiles(
    kind: ProfileKind,
    _user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RagModelRegistryService, Depends(get_rag_model_registry_service)],
) -> list[ProfileResponse]:
    return [
        ProfileResponse.from_domain(item)
        for item in await service.list_profiles(kind)
    ]


@router.post(
    "/profiles/{kind}/yaml",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
async def register_profile_yaml(
    kind: ProfileKind,
    request: ProfileYamlRequest,
    _user: Annotated[User, Depends(require_owner)],
    service: Annotated[RagModelRegistryService, Depends(get_rag_model_registry_service)],
) -> ProfileResponse:
    profile = await service.register_profile_yaml(kind=kind, content=request.content)
    return ProfileResponse.from_domain(profile)


@router.post(
    "/profiles/{kind}",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
async def register_profile(
    kind: ProfileKind,
    request: ProfileCreate,
    _user: Annotated[User, Depends(require_owner)],
    service: Annotated[RagModelRegistryService, Depends(get_rag_model_registry_service)],
) -> ProfileResponse:
    profile = await service.register_profile(
        kind=kind,
        name=request.name,
        version=request.version,
        config=request.config,
        bindings=tuple(item.to_domain() for item in request.bindings),
        deployment_version_id=request.deployment_version_id,
        evaluation_state=request.evaluation_state,
    )
    return ProfileResponse.from_domain(profile)


@router.post(
    "/profiles/{profile_id}/default",
    response_model=ProfileResponse,
    deprecated=True,
)
async def promote_default(
    profile_id: UUID,
    _user: Annotated[User, Depends(require_owner)],
    service: Annotated[RagModelRegistryService, Depends(get_rag_model_registry_service)],
) -> ProfileResponse:
    return ProfileResponse.from_domain(await service.promote_default(profile_id))
