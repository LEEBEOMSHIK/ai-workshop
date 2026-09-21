import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.conversations.attachment_lifecycle import list_deleted_cleanup
from ai_workshop.labs.rag.conversations.attachment_service import (
    AttachmentOptionsResponse,
    ConversationAttachmentResponse,
    ConversationAttachmentService,
    ConversationUploadJournal,
)
from ai_workshop.labs.rag.conversations.repository import SqlAlchemyConversationRepository
from ai_workshop.platform.assets.api import _upload_schema
from ai_workshop.platform.assets.intake_service import (
    HttpUploadIntakeService,
    get_upload_intake_service,
)
from ai_workshop.platform.assets.schemas import DocumentResponse
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import create_engine, create_session_factory
from ai_workshop.worker import CeleryJobDispatcher, get_job_dispatcher

_logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/rag/domains/{slug}/conversations/{conversation_id}",
    tags=["rag-conversation-attachments"],
)
cleanup_router = APIRouter(
    prefix="/api/v1/rag/domains/{slug}", tags=["rag-conversation-attachments"]
)


async def attachment_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[ConversationAttachmentService]:
    engine = create_engine(settings)
    try:
        yield ConversationAttachmentService(create_session_factory(engine), settings)
    finally:
        await engine.dispose()


@cleanup_router.get("/conversation-attachment-cleanup")
async def attachment_cleanup(
    slug: str,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ConversationAttachmentService, Depends(attachment_service)],
) -> list[dict[str, object]]:
    response.headers["Cache-Control"] = "no-store"
    domain_id = await SqlAlchemyConversationRepository(service.sessions).domain_id(slug)
    return await list_deleted_cleanup(service.sessions, user.id, domain_id)


@router.get("/attachment-options", response_model=AttachmentOptionsResponse)
async def options(
    slug: str,
    conversation_id: UUID,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ConversationAttachmentService, Depends(attachment_service)],
) -> AttachmentOptionsResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.options(slug, conversation_id, user.id)


@router.get("/attachments", response_model=list[ConversationAttachmentResponse])
async def attachments(
    slug: str,
    conversation_id: UUID,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ConversationAttachmentService, Depends(attachment_service)],
) -> list[ConversationAttachmentResponse]:
    response.headers["Cache-Control"] = "no-store"
    return await service.list(slug, conversation_id, user)


@router.post(
    "/attachments",
    response_model=ConversationAttachmentResponse,
    status_code=201,
    openapi_extra=_upload_schema(folder=False),
)
async def upload_attachment(
    slug: str,
    conversation_id: UUID,
    workspace_id: UUID,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ConversationAttachmentService, Depends(attachment_service)],
    intakes: Annotated[HttpUploadIntakeService, Depends(get_upload_intake_service)],
    dispatcher: Annotated[CeleryJobDispatcher, Depends(get_job_dispatcher)],
) -> ConversationAttachmentResponse:
    response.headers["Cache-Control"] = "no-store"
    attachment_id = await service.reserve(slug, conversation_id, user.id, workspace_id)
    journal = ConversationUploadJournal(
        service,
        slug=slug,
        conversation_id=conversation_id,
        actor_id=user.id,
        attachment_id=attachment_id,
    )
    scoped = HttpUploadIntakeService(journal, intakes.store, intakes.coordinator)
    try:
        result = await scoped.upload(
            user=user,
            stream=request.stream(),
            content_type=request.headers.get("content-type", ""),
            workspace_id=workspace_id,
        )
    except BaseException:
        try:
            await service.fail(attachment_id)
            await service.confirm_upload_termination(attachment_id)
        except BaseException:
            _logger.warning("conversation_attachment_termination_unconfirmed")
        raise
    await service.confirm_upload_termination(attachment_id)
    if result.job_created:
        background_tasks.add_task(dispatcher.verify_asset, result.job.id)
    return ConversationAttachmentResponse(
        id=attachment_id,
        document=DocumentResponse.from_domain(result.document, job_id=result.job.id),
        status="processing",
    )
