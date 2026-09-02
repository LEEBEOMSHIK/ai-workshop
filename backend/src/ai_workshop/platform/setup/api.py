from typing import Annotated

from fastapi import APIRouter, Depends, Response

from ai_workshop.config import Settings, get_settings
from ai_workshop.platform.identity.api import set_session_cookie
from ai_workshop.platform.identity.schemas import UserResponse
from ai_workshop.platform.setup.schemas import OwnerSetupRequest, SetupStatusResponse
from ai_workshop.platform.setup.service import SystemSetupService, get_system_setup_service

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


@router.get("/status", response_model=SetupStatusResponse)
async def setup_status(
    service: Annotated[SystemSetupService, Depends(get_system_setup_service)],
) -> SetupStatusResponse:
    return SetupStatusResponse(setup_required=await service.setup_required())


@router.post("/owner", response_model=UserResponse, status_code=201)
async def setup_owner(
    request: OwnerSetupRequest,
    response: Response,
    service: Annotated[SystemSetupService, Depends(get_system_setup_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserResponse:
    owner, token = await service.create_owner(
        display_name=request.display_name,
        email=str(request.email),
        password=request.password,
        password_confirmation=request.password_confirmation,
    )
    set_session_cookie(response, token, settings)
    return UserResponse.from_domain(owner)
