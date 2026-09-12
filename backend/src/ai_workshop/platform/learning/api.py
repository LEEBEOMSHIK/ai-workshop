from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from ai_workshop.learning_composition import get_learning_service
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.learning.domain import RecordKind
from ai_workshop.platform.learning.repository import LearningListFilters
from ai_workshop.platform.learning.schemas import (
    LearningDraft,
    LearningListResponse,
    LearningRecordResponse,
    LearningRevisionRequest,
    LearningTopicResponse,
    LearningUpdateRequest,
    load_learning_topics,
)
from ai_workshop.platform.learning.service import LearningService

router = APIRouter(prefix="/api/v1/learning", tags=["learning"])


@router.get("/topics", response_model=tuple[LearningTopicResponse, ...])
async def list_learning_topics(
    _user: Annotated[User, Depends(get_current_user)],
) -> tuple[LearningTopicResponse, ...]:
    return tuple(
        LearningTopicResponse(key=topic.key, label=topic.label)
        for topic in load_learning_topics()
    )


@router.post("/records", response_model=LearningRecordResponse, status_code=201)
async def create_learning_record(
    request: LearningDraft,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LearningService, Depends(get_learning_service)],
) -> LearningRecordResponse:
    return LearningRecordResponse.from_view(await service.create(user.id, request))


@router.get("/records", response_model=LearningListResponse)
async def list_learning_records(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LearningService, Depends(get_learning_service)],
    topic_key: str | None = None,
    kind: RecordKind | None = None,
    archived: bool | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> LearningListResponse:
    return LearningListResponse.from_view(
        await service.list_for(
            user.id,
            LearningListFilters(topic_key=topic_key, kind=kind, archived=archived),
            cursor,
            limit if limit is not None else service.default_page_limit,
        )
    )


@router.get("/records/{record_id}", response_model=LearningRecordResponse)
async def learning_record_detail(
    record_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LearningService, Depends(get_learning_service)],
) -> LearningRecordResponse:
    return LearningRecordResponse.from_view(await service.detail(user.id, record_id))


@router.get(
    "/records/{record_id}/revisions/{revision}",
    response_model=LearningRecordResponse,
)
async def learning_record_revision(
    record_id: UUID,
    revision: int,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LearningService, Depends(get_learning_service)],
) -> LearningRecordResponse:
    return LearningRecordResponse.from_view(
        await service.detail(user.id, record_id, revision=revision)
    )


@router.put("/records/{record_id}", response_model=LearningRecordResponse)
async def update_learning_record(
    record_id: UUID,
    request: LearningUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LearningService, Depends(get_learning_service)],
) -> LearningRecordResponse:
    return LearningRecordResponse.from_view(
        await service.update(
            user.id,
            record_id,
            request.expected_revision,
            request.draft,
        )
    )


@router.post("/records/{record_id}/archive", response_model=LearningRecordResponse)
async def archive_learning_record(
    record_id: UUID,
    request: LearningRevisionRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LearningService, Depends(get_learning_service)],
) -> LearningRecordResponse:
    return LearningRecordResponse.from_view(
        await service.archive(user.id, record_id, request.expected_revision)
    )


@router.post("/records/{record_id}/restore", response_model=LearningRecordResponse)
async def restore_learning_record(
    record_id: UUID,
    request: LearningRevisionRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[LearningService, Depends(get_learning_service)],
) -> LearningRecordResponse:
    return LearningRecordResponse.from_view(
        await service.restore(user.id, record_id, request.expected_revision)
    )
