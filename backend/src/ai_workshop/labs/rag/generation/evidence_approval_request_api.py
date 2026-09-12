"""Document classification review only: approval does not grant Codex execution."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from ai_workshop.config import Settings, get_settings
from ai_workshop.platform.identity.api import get_current_user, require_owner
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import create_engine, create_session_factory
from ai_workshop.shared.errors import AppError

from .codex_admin_api import require_codex_mutation
from .evidence_approval_request_schemas import (
    EvidenceApprovalRequestAdminPage,
    EvidenceApprovalRequestCreate,
    EvidenceApprovalRequestDecision,
    EvidenceApprovalRequestPage,
    EvidenceApprovalRequestResponse,
    SupportedEvidenceProvider,
)
from .evidence_approval_requests import EvidenceApprovalRequests

router = APIRouter(tags=["rag-evidence-requests"])


async def get_evidence_approval_requests(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[EvidenceApprovalRequests]:
    engine = create_engine(settings)
    try:
        yield EvidenceApprovalRequests(create_session_factory(engine), settings)
    except AppError:
        raise
    except Exception:
        raise AppError(
            "evidence_request_unavailable", "Document review requests are unavailable.", 503
        ) from None
    finally:
        await engine.dispose()


@router.post(
    "/api/v1/rag/evidence-approval-requests",
    response_model=EvidenceApprovalRequestResponse,
    description=(
        "Request document classification review. "
        "Does not approve transfer or grant model execution."
    ),
)
async def create_evidence_approval_request(
    body: EvidenceApprovalRequestCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[EvidenceApprovalRequests, Depends(get_evidence_approval_requests)],
    _mutation: Annotated[None, Depends(require_codex_mutation)],
    response: Response,
) -> EvidenceApprovalRequestResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.create(actor_id=user.id, body=body)


@router.get("/api/v1/rag/evidence-approval-requests", response_model=EvidenceApprovalRequestPage)
async def list_evidence_approval_requests(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[EvidenceApprovalRequests, Depends(get_evidence_approval_requests)],
    response: Response,
    revision_id: UUID | None = None,
    provider: SupportedEvidenceProvider = "development_codex_exec",
    cursor: str | None = None,
    limit: int | None = None,
) -> EvidenceApprovalRequestPage:
    response.headers["Cache-Control"] = "no-store"
    page = await service.list(
        actor_id=user.id, revision_id=revision_id, provider=provider, cursor=cursor, limit=limit
    )
    assert isinstance(page, EvidenceApprovalRequestPage)
    return page


@router.get(
    "/api/v1/admin/rag/evidence-approval-requests", response_model=EvidenceApprovalRequestAdminPage
)
async def list_admin_evidence_approval_requests(
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[EvidenceApprovalRequests, Depends(get_evidence_approval_requests)],
    response: Response,
    revision_id: UUID | None = None,
    provider: SupportedEvidenceProvider = "development_codex_exec",
    cursor: str | None = None,
    limit: int | None = None,
) -> EvidenceApprovalRequestAdminPage:
    response.headers["Cache-Control"] = "no-store"
    page = await service.list(
        actor_id=user.id,
        admin=True,
        revision_id=revision_id,
        provider=provider,
        cursor=cursor,
        limit=limit,
    )
    assert isinstance(page, EvidenceApprovalRequestAdminPage)
    return page


@router.post(
    "/api/v1/admin/rag/evidence-approval-requests/{id}/decision",
    response_model=EvidenceApprovalRequestResponse,
    description=(
        "Explicit owner document classification decision; "
        "execution policies and owner-only Codex remain enforced."
    ),
)
async def decide_evidence_approval_request(
    id: UUID,
    body: EvidenceApprovalRequestDecision,
    user: Annotated[User, Depends(require_owner)],
    service: Annotated[EvidenceApprovalRequests, Depends(get_evidence_approval_requests)],
    _mutation: Annotated[None, Depends(require_codex_mutation)],
    response: Response,
) -> EvidenceApprovalRequestResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.decide(actor_id=user.id, id=id, body=body)
