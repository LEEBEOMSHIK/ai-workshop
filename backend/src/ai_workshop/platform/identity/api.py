from typing import Annotated

from fastapi import APIRouter, Depends, Response, Security
from fastapi.security import APIKeyCookie

from ai_workshop.config import Settings, get_settings
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.identity.schemas import LoginRequest, UserResponse
from ai_workshop.platform.identity.service import AuthService, get_auth_service
from ai_workshop.shared.errors import AppError

SESSION_COOKIE = "ai_workshop_session"
session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    scheme_name="SessionCookie",
    auto_error=False,
)
router = APIRouter(prefix="/api/v1/auth", tags=["identity"])


def set_session_cookie(
    response: Response,
    token: str,
    settings: Settings,
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=30 * 60,
        path="/",
    )


async def get_current_user(
    service: Annotated[AuthService, Depends(get_auth_service)],
    session_token: Annotated[str | None, Security(session_cookie)],
) -> User:
    return await service.current_user(session_token)


async def require_owner(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role is not UserRole.OWNER:
        raise AppError(
            code="owner_required",
            message="Owner access is required.",
            status_code=403,
        )
    return user


@router.post("/login", response_model=UserResponse)
async def login(
    request: LoginRequest,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserResponse:
    user, token = await service.authenticate(str(request.email), request.password)
    set_session_cookie(response, token, settings)
    return UserResponse.from_domain(user)


@router.get("/me", response_model=UserResponse)
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    return UserResponse.from_domain(user)


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
