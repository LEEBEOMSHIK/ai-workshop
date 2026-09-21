from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.conversations.access import ConversationAccess
from ai_workshop.labs.rag.conversations.repository import SqlAlchemyConversationRepository
from ai_workshop.labs.rag.conversations.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationRename,
    ConversationSummary,
    ConversationTurnCreate,
)
from ai_workshop.labs.rag.conversations.service import ConversationService
from ai_workshop.labs.rag.domains.api import (
    DomainSearchExecutorPort,
    get_domain_search_executor,
    get_domain_service,
)
from ai_workshop.labs.rag.domains.service import DomainService
from ai_workshop.labs.rag.generation.codex_admin_api import require_codex_mutation
from ai_workshop.labs.rag.generation.codex_http_lifecycle import run_until_disconnect
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import create_engine, create_session_factory


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/rag/domains/{slug}/conversations",
    tags=["rag-conversations"],
    dependencies=[Depends(no_store)],
)


async def get_conversation_service(
    settings: Annotated[Settings, Depends(get_settings)],
    domains: Annotated[DomainService, Depends(get_domain_service)],
    executor: Annotated[DomainSearchExecutorPort, Depends(get_domain_search_executor)],
) -> AsyncIterator[ConversationService]:
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        yield ConversationService(
            SqlAlchemyConversationRepository(sessions),
            ConversationAccess(sessions),
            domains,
            executor,
        )
    finally:
        await engine.dispose()


Actor = Annotated[User, Depends(get_current_user)]
Service = Annotated[ConversationService, Depends(get_conversation_service)]


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(slug: str, user: Actor, service: Service) -> list[ConversationSummary]:
    return await service.list_for_actor(slug, user.id)


@router.post("", response_model=ConversationDetail, status_code=201)
async def create_conversation(
    slug: str, request: ConversationCreate, user: Actor, service: Service
) -> ConversationDetail:
    return await service.create(slug, user.id, request.title)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    slug: str, conversation_id: UUID, user: Actor, service: Service
) -> ConversationDetail:
    return await service.detail(slug, user.id, conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationDetail)
async def rename_conversation(
    slug: str, conversation_id: UUID, request: ConversationRename, user: Actor, service: Service
) -> ConversationDetail:
    return await service.rename(
        slug, user.id, conversation_id, request.title, request.expected_revision
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    slug: str,
    conversation_id: UUID,
    user: Actor,
    service: Service,
    expected_revision: Annotated[int, Query(ge=1)],
) -> Response:
    await service.delete(slug, user.id, conversation_id, expected_revision)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/{conversation_id}/turns", response_model=ConversationDetail)
async def submit_turn(
    slug: str,
    conversation_id: UUID,
    request: ConversationTurnCreate,
    transport: Request,
    user: Actor,
    service: Service,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConversationDetail:
    if request.codex_input_approval is not None:
        require_codex_mutation(transport, settings)
    return await run_until_disconnect(
        transport, service.submit(slug, user.id, conversation_id, request)
    )


@router.post("/{conversation_id}/turns/{request_id}/cancel", response_model=ConversationDetail)
async def cancel_turn(
    slug: str, conversation_id: UUID, request_id: UUID, user: Actor, service: Service
) -> ConversationDetail:
    return await service.cancel(slug, user.id, conversation_id, request_id)
