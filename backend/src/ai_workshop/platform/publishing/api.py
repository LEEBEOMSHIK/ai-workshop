from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from ai_workshop.config import Settings, get_settings
from ai_workshop.platform.identity.api import require_owner
from ai_workshop.platform.publishing.schemas import (
    PersonaList,
    PublicationRequest,
    StudyAdminList,
    StudyAdminView,
    StudyCreateRequest,
    StudyPreview,
    StudyUpdateRequest,
)
from ai_workshop.platform.publishing.service import PublishingService
from ai_workshop.publishing_composition import get_publishing_service
from ai_workshop.shared.errors import AppError

router = APIRouter(
    prefix="/api/v1/admin/publishing",
    tags=["publishing-admin"],
    dependencies=[Depends(require_owner)],
)


def require_publishing_mutation(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if request.headers.get("origin") not in settings.publishing_allowed_admin_origins:
        raise AppError(
            "publishing_request_forbidden",
            "The publishing request is forbidden.",
            403,
        )
    if request.headers.get("x-publishing-request") != "1":
        raise AppError(
            "publishing_request_forbidden",
            "The publishing request is forbidden.",
            403,
        )
    media_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0]
    if media_type.strip().lower() != "application/json":
        raise AppError(
            "publishing_json_required",
            "Publishing mutations require JSON.",
            415,
        )


@router.get("/personas", response_model=PersonaList)
async def list_personas(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PersonaList:
    return PersonaList(items=settings.publishing_approved_public_personas)


@router.get("/studies", response_model=StudyAdminList)
async def list_studies(
    service: Annotated[PublishingService, Depends(get_publishing_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> StudyAdminList:
    states = await service.list(
        offset=offset,
        limit=limit if limit is not None else service.default_page_limit,
    )
    return StudyAdminList(items=tuple(StudyAdminView.from_state(item) for item in states))


@router.post(
    "/studies",
    response_model=StudyAdminView,
    status_code=201,
    dependencies=[Depends(require_publishing_mutation)],
)
async def create_study(
    request: StudyCreateRequest,
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> StudyAdminView:
    return StudyAdminView.from_state(await service.create(request.content))


@router.get("/studies/{slug}", response_model=StudyAdminView)
async def study_detail(
    slug: str,
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> StudyAdminView:
    return StudyAdminView.from_state(await service.detail(slug))


@router.put(
    "/studies/{slug}",
    response_model=StudyAdminView,
    dependencies=[Depends(require_publishing_mutation)],
)
async def update_study(
    slug: str,
    request: StudyUpdateRequest,
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> StudyAdminView:
    return StudyAdminView.from_state(
        await service.update(
            slug,
            expected_revision=request.expected_revision,
            content=request.content,
        )
    )


@router.get("/studies/{slug}/preview", response_model=StudyPreview)
async def preview_study(
    slug: str,
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> StudyPreview:
    state = await service.detail(slug)
    return StudyPreview(snapshot=state.snapshot, digest=state.digest)


@router.post(
    "/studies/{slug}/publish",
    response_model=StudyAdminView,
    dependencies=[Depends(require_publishing_mutation)],
)
async def publish_study(
    slug: str,
    request: PublicationRequest,
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> StudyAdminView:
    return StudyAdminView.from_state(
        await service.publish(
            slug,
            expected_revision=request.expected_revision,
            expected_digest=request.expected_digest,
            request_id=request.request_id,
        )
    )


@router.post(
    "/studies/{slug}/withdraw",
    response_model=StudyAdminView,
    dependencies=[Depends(require_publishing_mutation)],
)
async def withdraw_study(
    slug: str,
    request: PublicationRequest,
    service: Annotated[PublishingService, Depends(get_publishing_service)],
) -> StudyAdminView:
    return StudyAdminView.from_state(
        await service.withdraw(
            slug,
            expected_revision=request.expected_revision,
            expected_digest=request.expected_digest,
            request_id=request.request_id,
        )
    )
