from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ai_workshop.authorization_composition import get_authorization_service
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.authorization_schemas import (
    AccessResponse,
    AuthorityAuditPageResponse,
    AuthorityAuditResponse,
    GrantUpdateRequest,
    RoleUpdateRequest,
    StatusUpdateRequest,
    TechnologyCatalogResponse,
    UserAuthorityPageResponse,
    UserAuthorityResponse,
)
from ai_workshop.platform.identity.authorization_service import AuthorizationService
from ai_workshop.platform.identity.domain import User

router = APIRouter(prefix="/api/v1", tags=["authorization"])


class AuthorizationCacheControlMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        applies = scope["type"] == "http" and (
            path == "/api/v1/auth/access"
            or path == "/api/v1/admin/access"
            or path.startswith("/api/v1/admin/access/")
        )

        async def send_private_no_store(message: Message) -> None:
            if applies and message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "private, no-store"
            await send(message)

        await self.app(scope, receive, send_private_no_store if applies else send)


def _private_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


@router.get("/auth/access", response_model=AccessResponse)
async def get_access(
    response: Response,
    actor: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> AccessResponse:
    _private_no_store(response)
    return AccessResponse.from_domain(await service.get_access(actor.id))


@router.get(
    "/admin/access/technologies",
    response_model=list[TechnologyCatalogResponse],
)
async def list_technologies(
    response: Response,
    actor: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> list[TechnologyCatalogResponse]:
    _private_no_store(response)
    technologies = await service.list_technologies(actor.id)
    return [
        TechnologyCatalogResponse(
            key=item.key,
            label=item.label,
            delegation_enabled=item.delegation_enabled,
        )
        for item in technologies
    ]


@router.get("/admin/access/users", response_model=UserAuthorityPageResponse)
async def list_users(
    response: Response,
    actor: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthorizationService, Depends(get_authorization_service)],
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> UserAuthorityPageResponse:
    _private_no_store(response)
    return UserAuthorityPageResponse.from_domain(
        await service.list_users(actor.id, cursor=cursor, limit=limit)
    )


@router.get("/admin/access/users/{user_id}", response_model=UserAuthorityResponse)
async def get_user(
    user_id: UUID,
    response: Response,
    actor: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> UserAuthorityResponse:
    _private_no_store(response)
    return UserAuthorityResponse.from_domain(await service.get_user(actor.id, user_id))


@router.put(
    "/admin/access/users/{user_id}/technologies/{technology_key}",
    response_model=UserAuthorityResponse,
)
async def update_grant(
    user_id: UUID,
    technology_key: str,
    request: GrantUpdateRequest,
    response: Response,
    actor: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> UserAuthorityResponse:
    _private_no_store(response)
    return UserAuthorityResponse.from_domain(
        await service.set_grant(
            actor.id,
            user_id,
            technology_key,
            frozenset(request.capabilities),
            expected_revision=request.expected_revision,
        )
    )


@router.patch("/admin/access/users/{user_id}/status", response_model=UserAuthorityResponse)
async def update_status(
    user_id: UUID,
    request: StatusUpdateRequest,
    response: Response,
    actor: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> UserAuthorityResponse:
    _private_no_store(response)
    return UserAuthorityResponse.from_domain(
        await service.set_status(
            actor.id,
            user_id,
            request.is_active,
            expected_revision=request.expected_revision,
        )
    )


@router.patch("/admin/access/users/{user_id}/role", response_model=UserAuthorityResponse)
async def update_role(
    user_id: UUID,
    request: RoleUpdateRequest,
    response: Response,
    actor: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> UserAuthorityResponse:
    _private_no_store(response)
    return UserAuthorityResponse.from_domain(
        await service.set_role(
            actor.id,
            user_id,
            request.role,
            expected_revision=request.expected_revision,
        )
    )


@router.get(
    "/admin/access/users/{user_id}/audit",
    response_model=AuthorityAuditPageResponse,
)
async def list_audit(
    user_id: UUID,
    response: Response,
    actor: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthorizationService, Depends(get_authorization_service)],
    cursor: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuthorityAuditPageResponse:
    _private_no_store(response)
    page = await service.list_audit(actor.id, user_id, cursor=cursor, limit=limit)
    return AuthorityAuditPageResponse(
        items=[AuthorityAuditResponse.from_domain(item) for item in page.items],
        next_cursor=page.next_cursor,
    )
