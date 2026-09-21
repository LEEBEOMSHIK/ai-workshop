"""Owner-only Codex metadata and explicit, consented connection verification."""

from collections.abc import AsyncIterator, Awaitable
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ai_workshop.config import Settings, get_settings
from ai_workshop.platform.identity.api import require_owner
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.errors import AppError

from .codex_authorization import EvidenceClassification
from .codex_composition import CodexServices, codex_registry, codex_services
from .codex_runner_registry import CodexRunnerReferenceError
from .codex_verification import CodexVerificationStatus
from .prompts import load_prompt

router = APIRouter(prefix="/api/v1/admin/rag", tags=["rag-codex"])


class CodexInputApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: Literal["public", "synthetic"]
    consented: StrictBool
    disclosure_version: str = Field(min_length=1, max_length=120)


class CodexVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consented: StrictBool
    disclosure_version: str = Field(min_length=1, max_length=120)


class CodexEvidenceApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: Literal["public", "synthetic"]
    content_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    expected_generation: int = Field(ge=0, strict=True)
    request_id: UUID


class CodexEvidenceRevocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_generation: int = Field(ge=0, strict=True)
    request_id: UUID


class CodexVerificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ready: bool
    safe_error_code: str | None
    requested_provider_model_id: str
    observed_provider_model_id: str | None
    model_identity_status: Literal["unknown", "verified", "mismatch"]
    checked_at: datetime | None


class CodexEvidenceHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    action: Literal["approve", "revoke"]
    generation: int
    actor_id: UUID | None
    occurred_at: datetime
    classification: Literal["public", "synthetic"]


class CodexEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    revision_id: UUID
    document_id: UUID
    workspace_id: UUID
    document_name: str
    revision_number: int
    content_sha256: str
    approval_classification: Literal["public", "synthetic"] | None
    approved_at: datetime | None
    revoked: bool
    approval_generation: int
    provider: Literal["development_codex_exec"]
    approval_history: list[CodexEvidenceHistoryResponse]


class CodexPromptOption(BaseModel):
    answer_ref: str
    context_ref: str
    response_schema_version: int
    control_ref: str
    control_text: str
    answer_text: str
    context_text: str
    context_evidence: dict[str, int] | None = None


class CodexRunnerLimitsResponse(BaseModel):
    timeout_seconds: float
    max_output_tokens: int
    max_concurrent: int


class CodexRunnerResponse(BaseModel):
    runner_ref: str
    cli_version: str
    local_preflight_passed: bool
    safe_error_code: str | None
    limits: CodexRunnerLimitsResponse
    prompt_options: list[CodexPromptOption]


def require_codex_mutation(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    if (
        request.headers.get("origin") not in settings.codex_allowed_admin_origins
        or request.headers.get("x-codex-request") != "1"
    ):
        raise AppError("codex_origin_forbidden", "Codex mutation origin is not allowed.", 403)
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise AppError("codex_json_required", "Codex mutations require application/json.", 415)


async def get_codex_services(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[CodexServices]:
    try:
        async with codex_services(settings) as services:
            yield services
    except AppError:
        raise
    except Exception:
        pass
    else:
        return
    raise AppError("codex_verification_unavailable", "Codex verification is unavailable.", 503)


async def _verification_response(
    result: Awaitable[CodexVerificationStatus],
) -> CodexVerificationResponse:
    try:
        return CodexVerificationResponse.model_validate(await result)
    except AppError:
        raise
    except Exception:
        pass
    raise AppError("codex_verification_unavailable", "Codex verification is unavailable.", 503)


@router.get("/codex-runners", response_model=list[CodexRunnerResponse])
async def list_codex_runners(
    _user: Annotated[User, Depends(require_owner)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[CodexRunnerResponse]:
    if settings.environment not in {"local", "test"}:
        raise AppError(
            "codex_environment_forbidden", "Codex requires development environment.", 403
        )
    registry = codex_registry(settings)
    prompts = [
        CodexPromptOption(
            answer_ref="rag-codex-answer-v3",
            context_ref="rag-codex-contextualize-v1",
            response_schema_version=2,
            control_ref="rag-codex-control-v1",
            control_text=load_prompt("rag-codex-control-v1"),
            answer_text=load_prompt("rag-codex-answer-v3"),
            context_text=load_prompt("rag-codex-contextualize-v1"),
        ),
        CodexPromptOption(
            answer_ref="rag-codex-answer-v4",
            context_ref="rag-codex-contextualize-v1",
            response_schema_version=2,
            control_ref="rag-codex-control-v1",
            control_text=load_prompt("rag-codex-control-v1"),
            answer_text=load_prompt("rag-codex-answer-v4"),
            context_text=load_prompt("rag-codex-contextualize-v1"),
            context_evidence={
                "version": 1,
                "max_groups": 8,
                "max_units": 32,
                "max_characters": 12000,
            },
        ),
    ]
    result = []
    for name, runner in sorted(settings.codex_runner_refs.items()):
        code = None
        try:
            registry.resolve(name)
        except CodexRunnerReferenceError as error:
            code = error.code
        result.append(
            CodexRunnerResponse(
                runner_ref=name,
                cli_version=runner.expected_cli_version,
                local_preflight_passed=code is None,
                safe_error_code=code,
                limits=CodexRunnerLimitsResponse(
                    timeout_seconds=runner.limits.timeout_seconds,
                    max_output_tokens=runner.limits.max_output_tokens,
                    max_concurrent=runner.limits.max_concurrent_requests,
                ),
                prompt_options=prompts,
            )
        )
    return result


@router.get(
    "/configuration-versions/{version_id}/codex-status", response_model=CodexVerificationResponse
)
async def codex_status(
    version_id: UUID,
    user: Annotated[User, Depends(require_owner)],
    services: Annotated[CodexServices, Depends(get_codex_services)],
) -> CodexVerificationResponse:
    return await _verification_response(
        services.verification.status(actor_id=user.id, configuration_version_id=version_id)
    )


@router.post(
    "/configuration-versions/{version_id}/codex-verify",
    response_model=CodexVerificationResponse,
    dependencies=[Depends(require_codex_mutation)],
)
async def verify_codex(
    version_id: UUID,
    request: CodexVerificationRequest,
    user: Annotated[User, Depends(require_owner)],
    services: Annotated[CodexServices, Depends(get_codex_services)],
) -> CodexVerificationResponse:
    return await _verification_response(
        services.verification.verify(
            actor_id=user.id,
            configuration_version_id=version_id,
            consented=request.consented,
            disclosure_version=request.disclosure_version,
        )
    )


@router.get("/codex-evidence", response_model=list[CodexEvidenceResponse])
async def list_codex_evidence(
    workspace_id: UUID,
    user: Annotated[User, Depends(require_owner)],
    services: Annotated[CodexServices, Depends(get_codex_services)],
) -> list[CodexEvidenceResponse]:
    return [
        CodexEvidenceResponse.model_validate(item)
        for item in await services.evidence.list_evidence(
            actor_id=user.id, workspace_id=workspace_id
        )
    ]


@router.post(
    "/codex-evidence/{revision_id}/approval",
    status_code=204,
    dependencies=[Depends(require_codex_mutation)],
)
async def approve_codex_evidence(
    revision_id: UUID,
    request: CodexEvidenceApprovalRequest,
    user: Annotated[User, Depends(require_owner)],
    services: Annotated[CodexServices, Depends(get_codex_services)],
) -> Response:
    await services.evidence.approve(
        actor_id=user.id,
        revision_id=revision_id,
        content_sha256=request.content_sha256,
        classification=EvidenceClassification(request.classification),
        expected_generation=request.expected_generation,
        request_id=request.request_id,
    )
    return Response(status_code=204)


@router.delete(
    "/codex-evidence/{revision_id}/approval",
    status_code=204,
    dependencies=[Depends(require_codex_mutation)],
)
async def revoke_codex_evidence(
    revision_id: UUID,
    request: CodexEvidenceRevocationRequest,
    user: Annotated[User, Depends(require_owner)],
    services: Annotated[CodexServices, Depends(get_codex_services)],
) -> Response:
    await services.evidence.revoke(
        actor_id=user.id,
        revision_id=revision_id,
        expected_generation=request.expected_generation,
        request_id=request.request_id,
    )
    return Response(status_code=204)
