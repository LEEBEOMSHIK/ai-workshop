"""Explicit data review requests; these contracts never confer execution authority."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SupportedEvidenceProvider = Literal["development_codex_exec"]
RequestStatus = Literal["pending", "approved", "rejected"]


class EvidenceApprovalRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    revision_id: UUID
    provider: SupportedEvidenceProvider
    expected_approval_generation: int = Field(ge=0, strict=True)


class EvidenceApprovalRequestDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_state_revision: int = Field(ge=0, strict=True)
    decision: Literal["approve", "reject"]
    expected_approval_generation: int = Field(ge=0, strict=True)
    classification: Literal["public", "synthetic"] | None = None
    content_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def explicit_approval(self) -> Self:
        if self.decision == "approve":
            if self.classification is None or self.content_sha256 is None:
                raise ValueError("Approval requires an explicit classification and exact digest.")
        elif self.classification is not None or self.content_sha256 is not None:
            raise ValueError("Rejection must not contain approval fields.")
        return self


class EvidenceApprovalRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    revision_id: UUID
    provider: SupportedEvidenceProvider
    status: RequestStatus
    state_revision: int
    created_at: datetime
    resolved_at: datetime | None


class EvidenceApprovalRequestAdminResponse(EvidenceApprovalRequestResponse):
    document_id: UUID
    workspace_id: UUID
    document_name: str
    workspace_name: str
    revision_number: int
    requester_display_name: str


class EvidenceApprovalContext(BaseModel):
    revision_id: UUID
    provider: SupportedEvidenceProvider
    approval_status: Literal["unapproved", "approved", "revoked"]
    approval_generation: int


class EvidenceApprovalRequestPage(BaseModel):
    items: list[EvidenceApprovalRequestResponse]
    next_cursor: str | None
    context: EvidenceApprovalContext | None


class EvidenceApprovalRequestAdminPage(BaseModel):
    items: list[EvidenceApprovalRequestAdminResponse]
    next_cursor: str | None
