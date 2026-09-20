from __future__ import annotations

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.domains.library_api import router as library_router
from ai_workshop.labs.rag.domains.repository import (
    SqlAlchemyDomainConfigurationProvider,
    SqlAlchemyDomainRepository,
    SqlAlchemyDomainSearchConfigurationResolver,
)
from ai_workshop.labs.rag.domains.schemas import (
    AdminDomainResponse,
    DomainConnectionCreatedResponse,
    DomainConnectionCreateRequest,
    DomainConnectionVersionResponse,
    DomainCreateRequest,
    DomainResponse,
    DomainSearchRequest,
    DomainSearchResponse,
    DomainUpdateRequest,
)
from ai_workshop.labs.rag.domains.service import DomainService
from ai_workshop.labs.rag.generation.codex_admin_api import require_codex_mutation
from ai_workshop.labs.rag.generation.codex_http_lifecycle import run_until_disconnect
from ai_workshop.labs.rag.generation.integrity import ConversationScopeBinding
from ai_workshop.labs.rag.search.api import get_search_service
from ai_workshop.labs.rag.search.configuration_port import ResolvedSearchConfiguration
from ai_workshop.labs.rag.search.schemas import SearchRequest
from ai_workshop.labs.rag.search.service import SearchApplicationService
from ai_workshop.platform.identity.api import get_current_user, require_owner
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.shared.db import get_session

router = APIRouter(prefix="/api/v1/rag/domains", tags=["rag-domains"])
admin_router = APIRouter(
    prefix="/api/v1/admin/rag/domains",
    tags=["rag-domain-administration"],
)
router.include_router(library_router)


def get_domain_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(get_current_user)],
) -> DomainService:
    return DomainService(
        SqlAlchemyDomainRepository(session),
        SqlAlchemyDomainConfigurationProvider(session, settings, actor_id=user.id),
    )


class DomainSearchExecutorPort(Protocol):
    async def execute(
        self,
        *,
        slug: str,
        actor_id: UUID,
        request: DomainSearchRequest,
    ) -> DomainSearchResponse: ...


class DomainSearchConfigurationResolverPort(Protocol):
    async def resolve_domain_version(
        self,
        configuration_version_id: UUID,
        actor_id: UUID,
    ) -> ResolvedSearchConfiguration: ...


class DomainSearchExecutor:
    def __init__(
        self,
        domains: DomainService,
        configurations: DomainSearchConfigurationResolverPort,
        search: SearchApplicationService,
    ) -> None:
        self.domains = domains
        self.configurations = configurations
        self.search = search

    async def execute(
        self,
        *,
        slug: str,
        actor_id: UUID,
        request: DomainSearchRequest,
    ) -> DomainSearchResponse:
        context = await self.domains.resolve_search(
            slug=slug,
            actor_id=actor_id,
            connection_version_id=request.connection_version_id,
            workspace_ids=tuple(request.workspace_ids),
            folder_ids=tuple(request.folder_ids),
            document_ids=(
                tuple(request.document_ids) if request.document_ids is not None else None
            ),
        )
        configuration = await self.configurations.resolve_domain_version(
            context.configuration_version_id,
            actor_id,
        )
        search_request_data: dict[str, object] = {
            "query": request.query,
            "configuration_id": context.configuration_id,
            "workspace_ids": list(context.workspace_ids),
            "folder_ids": list(context.folder_ids),
            "top_k": request.top_k,
            "include_diagnostics": request.include_diagnostics,
            "experimental": configuration.experimental,
            "history": request.history,
            "codex_input_approval": request.codex_input_approval,
        }
        if context.document_ids is not None:
            search_request_data["document_ids"] = list(context.document_ids)
        result = await self.search.search_resolved(
            actor_id=actor_id,
            request=SearchRequest.model_validate(search_request_data),
            configuration=configuration,
            conversation_scope=ConversationScopeBinding(
                domain_id=context.domain_id,
                connection_version_id=context.connection_version_id,
                workspace_ids=context.workspace_ids,
                folder_ids=context.folder_ids,
            ),
        )
        return DomainSearchResponse.from_result(result, context)


def get_domain_search_configuration_resolver(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DomainSearchConfigurationResolverPort:
    return SqlAlchemyDomainSearchConfigurationResolver(session, settings)


def get_domain_search_executor(
    domains: Annotated[DomainService, Depends(get_domain_service)],
    configurations: Annotated[
        DomainSearchConfigurationResolverPort,
        Depends(get_domain_search_configuration_resolver),
    ],
    search: Annotated[SearchApplicationService, Depends(get_search_service)],
) -> DomainSearchExecutorPort:
    return DomainSearchExecutor(domains, configurations, search)


@router.get("", response_model=list[DomainResponse])
async def list_domains(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DomainService, Depends(get_domain_service)],
) -> list[DomainResponse]:
    if user.role == UserRole.OWNER:
        views = await service.list_for_owner(user.id)
    else:
        views = await service.list_for_actor(user.id)
    return [DomainResponse.from_domain(item) for item in views]


@router.get("/{slug}", response_model=DomainResponse)
async def domain_detail(
    slug: str,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DomainService, Depends(get_domain_service)],
) -> DomainResponse:
    return DomainResponse.from_domain(await service.detail_for_actor(slug, user.id))


@router.post("/{slug}/search", response_model=DomainSearchResponse)
async def domain_search(
    slug: str,
    request: DomainSearchRequest,
    transport: Request,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    executor: Annotated[DomainSearchExecutorPort, Depends(get_domain_search_executor)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DomainSearchResponse:
    if request.include_diagnostics:
        response.headers["Cache-Control"] = "no-store"
    if request.codex_input_approval is not None:
        require_codex_mutation(transport, settings)
    return await run_until_disconnect(
        transport, executor.execute(slug=slug, actor_id=user.id, request=request)
    )


@admin_router.get("", response_model=list[DomainResponse])
async def list_admin_domains(
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[DomainService, Depends(get_domain_service)],
) -> list[DomainResponse]:
    return [DomainResponse.from_domain(item) for item in await service.list_for_owner(user.id)]


@admin_router.post("", response_model=AdminDomainResponse, status_code=201)
async def create_domain(
    request: DomainCreateRequest,
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[DomainService, Depends(get_domain_service)],
) -> AdminDomainResponse:
    return AdminDomainResponse.from_domain(
        await service.create_domain(
            actor_id=user.id,
            slug=request.slug,
            display_name=request.display_name,
            description=request.description,
        )
    )


@admin_router.patch("/{domain_id}", response_model=AdminDomainResponse)
async def update_domain(
    domain_id: UUID,
    request: DomainUpdateRequest,
    _user: Annotated[User, Depends(require_owner)],
    service: Annotated[DomainService, Depends(get_domain_service)],
) -> AdminDomainResponse:
    return AdminDomainResponse.from_domain(
        await service.update_domain(
            domain_id=domain_id,
            display_name=request.display_name,
            description=request.description,
        )
    )


@admin_router.post(
    "/{domain_id}/connections",
    response_model=DomainConnectionCreatedResponse,
    status_code=201,
)
async def create_connection(
    domain_id: UUID,
    request: DomainConnectionCreateRequest,
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[DomainService, Depends(get_domain_service)],
) -> DomainConnectionCreatedResponse:
    return DomainConnectionCreatedResponse.from_domain(
        await service.create_connection(
            domain_id=domain_id,
            actor_id=user.id,
            configuration_version_id=request.configuration_version_id,
            workspace_ids=tuple(request.workspace_ids),
        )
    )


@admin_router.get(
    "/{domain_id}/connections",
    response_model=list[DomainConnectionVersionResponse],
)
async def list_connections(
    domain_id: UUID,
    _user: Annotated[User, Depends(require_owner)],
    service: Annotated[DomainService, Depends(get_domain_service)],
) -> list[DomainConnectionVersionResponse]:
    return [
        DomainConnectionVersionResponse.from_domain(item)
        for item in await service.connections_for_owner(domain_id)
    ]


@admin_router.post(
    "/{domain_id}/connections/{connection_version_id}/activate",
    response_model=AdminDomainResponse,
)
async def activate_connection(
    domain_id: UUID,
    connection_version_id: UUID,
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[DomainService, Depends(get_domain_service)],
) -> AdminDomainResponse:
    return AdminDomainResponse.from_domain(
        await service.activate_connection(
            domain_id=domain_id,
            connection_version_id=connection_version_id,
            actor_id=user.id,
        )
    )


@admin_router.post("/{domain_id}/deactivate", response_model=AdminDomainResponse)
async def deactivate_domain(
    domain_id: UUID,
    _user: Annotated[User, Depends(require_owner)],
    service: Annotated[DomainService, Depends(get_domain_service)],
) -> AdminDomainResponse:
    return AdminDomainResponse.from_domain(await service.deactivate(domain_id=domain_id))
