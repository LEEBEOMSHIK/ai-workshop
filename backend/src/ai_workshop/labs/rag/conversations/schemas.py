from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_workshop.labs.rag.domains.schemas import DomainSearchResponse
from ai_workshop.labs.rag.generation.codex_admin_api import CodexInputApprovalRequest
from ai_workshop.labs.rag.retrieval.selection import reject_explicit_empty_document_ids


class RequestScope(BaseModel):
    connection_version_id: UUID
    workspace_ids: list[UUID] = Field(min_length=1)
    folder_ids: list[UUID] = Field(default_factory=list)
    document_ids: list[UUID] | None = None


class ConversationQuestion(RequestScope):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=10, ge=1, le=50)
    include_diagnostics: bool = True
    codex_input_approval: CodexInputApprovalRequest | None = None
    _reject_empty = field_validator("document_ids", mode="before")(
        reject_explicit_empty_document_ids
    )

    @field_validator("query")
    @classmethod
    def require_nonblank_question(cls, value: str) -> str:
        if len(value.strip()) < 2:
            raise ValueError("A meaningful question is required.")
        return value


class ConversationTurnCreate(ConversationQuestion):
    expected_revision: int = Field(ge=1)


class ConversationStart(ConversationQuestion):
    draft_id: UUID | None = None
    draft_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_draft_pair(self) -> Self:
        if (self.draft_id is None) != (self.draft_revision is None):
            raise ValueError("draft_id and draft_revision must be supplied together.")
        return self

    def turn_request(self) -> ConversationTurnCreate:
        return ConversationTurnCreate(
            **self.model_dump(exclude={"draft_id", "draft_revision"}, exclude_none=True),
            expected_revision=1,
        )


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=180)


class ConversationRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=180)
    expected_revision: int = Field(ge=1)


class ConversationSummary(BaseModel):
    id: UUID
    title: str
    revision: int
    created_at: datetime
    updated_at: datetime
    title_origin: Literal["auto", "manual", "legacy"] = "legacy"
    title_source_turn_id: UUID | None = None
    title_derivation: Literal["extracted", "preserved", "fallback"] | None = None
    title_policy_version: str | None = None
    title_error_code: str | None = None
    legacy_state: str = "active"
    attachment_draft_id: UUID | None = None


class ConversationTurnResponse(BaseModel):
    id: UUID
    request_id: UUID
    sequence: int
    status: Literal["running", "completed", "failed", "cancelled", "interrupted"]
    query: str
    response: DomainSearchResponse | None
    request_scope: RequestScope | None
    segment: int
    error_code: str | None
    redacted: bool
    created_at: datetime
    updated_at: datetime
    execution_terminated: bool
    execution_id: UUID | None = None
    observation_complete: bool | None = None


class ConversationDetail(ConversationSummary):
    turns: list[ConversationTurnResponse]
