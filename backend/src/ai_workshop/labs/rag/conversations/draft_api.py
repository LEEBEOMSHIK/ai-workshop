from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.conversations.api import no_store
from ai_workshop.labs.rag.conversations.attachment_api import perform_upload
from ai_workshop.labs.rag.conversations.attachment_lifecycle import list_draft_cleanup
from ai_workshop.labs.rag.conversations.attachment_service import (
    AttachmentOptionsResponse,
    ConversationAttachmentResponse,
)
from ai_workshop.labs.rag.conversations.draft_service import (
    AttachmentDraftService,
    DraftCreate,
    DraftResponse,
)
from ai_workshop.platform.assets.api import _upload_schema
from ai_workshop.platform.assets.intake_service import (
    HttpUploadIntakeService,
    get_upload_intake_service,
)
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import create_engine, create_session_factory
from ai_workshop.worker import CeleryJobDispatcher, get_job_dispatcher

router = APIRouter(
    prefix="/api/v1/rag/domains/{slug}",
    tags=["rag-attachment-drafts"],
    dependencies=[Depends(no_store)],
)


async def draft_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[AttachmentDraftService]:
    engine = create_engine(settings)
    try:
        yield AttachmentDraftService(create_session_factory(engine), settings)
    finally:
        await engine.dispose()


Actor = Annotated[User, Depends(get_current_user)]
Service = Annotated[AttachmentDraftService, Depends(draft_service)]


@router.get("/attachment-options", response_model=AttachmentOptionsResponse)
async def domain_options(slug: str, user: Actor, service: Service) -> AttachmentOptionsResponse:
    return await service.domain_options(slug, user.id)


@router.post("/attachment-drafts", response_model=DraftResponse, status_code=201)
async def create(slug: str, request: DraftCreate, user: Actor, service: Service) -> DraftResponse:
    return await service.create_draft(slug, user.id, request.request_id)


@router.get("/attachment-draft-cleanup")
async def cleanup(slug: str, user: Actor, service: Service) -> list[dict[str, object]]:
    async with service.sessions() as session:
        context = await service.context(session, slug, user.id)
    return await list_draft_cleanup(service.sessions, user.id, context.domain.id)


@router.get("/attachment-drafts/{draft_id}", response_model=DraftResponse)
async def detail(slug: str, draft_id: UUID, user: Actor, service: Service) -> DraftResponse:
    return await service.detail_draft(slug, user.id, draft_id)


@router.delete("/attachment-drafts/{draft_id}", response_model=DraftResponse)
async def abandon(
    slug: str,
    draft_id: UUID,
    user: Actor,
    service: Service,
    expected_revision: Annotated[int, Query(ge=1)],
) -> DraftResponse:
    return await service.abandon(slug, user.id, draft_id, expected_revision)


@router.get(
    "/attachment-drafts/{draft_id}/attachment-options", response_model=AttachmentOptionsResponse
)
async def options(
    slug: str, draft_id: UUID, user: Actor, service: Service
) -> AttachmentOptionsResponse:
    return await service.options(slug, draft_id, user.id)


@router.get(
    "/attachment-drafts/{draft_id}/attachments", response_model=list[ConversationAttachmentResponse]
)
async def attachments(
    slug: str, draft_id: UUID, user: Actor, service: Service
) -> list[ConversationAttachmentResponse]:
    return await service.list(slug, draft_id, user)


@router.delete(
    "/attachment-drafts/{draft_id}/attachments/{attachment_id}", response_model=DraftResponse
)
async def exclude(
    slug: str,
    draft_id: UUID,
    attachment_id: UUID,
    user: Actor,
    service: Service,
    expected_revision: Annotated[int, Query(ge=1)],
) -> DraftResponse:
    return await service.exclude(slug, user.id, draft_id, attachment_id, expected_revision)


@router.post(
    "/attachment-drafts/{draft_id}/attachments",
    response_model=ConversationAttachmentResponse,
    status_code=201,
    openapi_extra=_upload_schema(folder=False),
)
async def upload(
    slug: str,
    draft_id: UUID,
    workspace_id: UUID,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    user: Actor,
    service: Service,
    intakes: Annotated[HttpUploadIntakeService, Depends(get_upload_intake_service)],
    dispatcher: Annotated[CeleryJobDispatcher, Depends(get_job_dispatcher)],
    expected_revision: Annotated[int, Query(ge=1)],
) -> ConversationAttachmentResponse:
    id = await service.reserve_draft(slug, draft_id, user.id, workspace_id, expected_revision)
    return await perform_upload(
        slug,
        draft_id,
        workspace_id,
        request,
        background_tasks,
        user,
        service,
        intakes,
        dispatcher,
        id,
        draft_id=draft_id,
    )


@router.post("/conversations/{conversation_id}/restore-draft", response_model=DraftResponse)
async def restore(slug: str, conversation_id: UUID, user: Actor, service: Service) -> DraftResponse:
    return await service.restore_legacy(slug, user.id, conversation_id)
