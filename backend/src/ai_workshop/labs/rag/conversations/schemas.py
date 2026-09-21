from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_workshop.labs.rag.domains.schemas import DomainSearchResponse
from ai_workshop.labs.rag.generation.codex_admin_api import CodexInputApprovalRequest
from ai_workshop.labs.rag.retrieval.selection import reject_explicit_empty_document_ids


class RequestScope(BaseModel):
    connection_version_id: UUID
    workspace_ids: list[UUID] = Field(min_length=1)
    folder_ids: list[UUID] = Field(default_factory=list)
    document_ids: list[UUID] | None = None


class ConversationTurnCreate(RequestScope):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_revision: int = Field(ge=1)
    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=10, ge=1, le=50)
    include_diagnostics: bool = True
    codex_input_approval: CodexInputApprovalRequest | None = None
    _reject_empty = field_validator("document_ids", mode="before")(
        reject_explicit_empty_document_ids
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


class ConversationDetail(ConversationSummary):
    turns: list[ConversationTurnResponse]
