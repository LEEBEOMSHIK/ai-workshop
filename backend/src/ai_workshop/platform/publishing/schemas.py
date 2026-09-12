from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_workshop.platform.publishing.domain import PublicationAction
from ai_workshop.platform.publishing.package import PublicPersona, StudyContent, StudySnapshot

if TYPE_CHECKING:
    from ai_workshop.platform.publishing.repository import PublishingStudy


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StudyCreateRequest(_StrictFrozenModel):
    content: StudyContent


class StudyUpdateRequest(_StrictFrozenModel):
    expected_revision: int = Field(strict=True, gt=0)
    content: StudyContent


class PublicationRequest(_StrictFrozenModel):
    expected_revision: int = Field(strict=True, gt=0)
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: str = Field(min_length=1)

    @field_validator("request_id")
    @classmethod
    def require_non_blank_request_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("request id must not be blank")
        return value


class PendingPublicationCommandView(_StrictFrozenModel):
    action: PublicationAction
    expected_revision: int
    expected_digest: str
    request_id: str


class StudyAdminView(_StrictFrozenModel):
    snapshot: StudySnapshot
    digest: str
    sequence: int
    approved_digest: str | None
    desired_action: PublicationAction | None
    applied_sequence: int
    applied_action: PublicationAction | None
    applied_revision: int | None
    delivery_pending: bool
    pending_command: PendingPublicationCommandView | None
    last_request_id: str | None
    delivery_error_code: str | None

    @classmethod
    def from_state(cls, state: PublishingStudy) -> StudyAdminView:
        pending = state.pending_command
        return cls(
            snapshot=state.snapshot,
            digest=state.digest,
            sequence=state.sequence,
            approved_digest=state.draft.approved_digest,
            desired_action=state.desired_action,
            applied_sequence=state.applied_sequence,
            applied_action=state.applied_action,
            applied_revision=state.applied_revision,
            delivery_pending=state.delivery_pending,
            pending_command=(
                PendingPublicationCommandView(
                    action=pending.action,
                    expected_revision=pending.expected_revision,
                    expected_digest=pending.expected_digest,
                    request_id=pending.request_id,
                )
                if pending is not None
                else None
            ),
            last_request_id=state.last_request_id,
            delivery_error_code=state.delivery_error_code,
        )


class StudyAdminList(_StrictFrozenModel):
    items: tuple[StudyAdminView, ...]


class StudyPreview(_StrictFrozenModel):
    snapshot: StudySnapshot
    digest: str


class PersonaList(_StrictFrozenModel):
    items: tuple[PublicPersona, ...]


class PublicStudyList(_StrictFrozenModel):
    items: tuple[StudySnapshot, ...]


class PublicStudyTopicCount(_StrictFrozenModel):
    key: str
    count: int = Field(ge=1)


class PublicStudyCatalog(_StrictFrozenModel):
    items: tuple[StudySnapshot, ...]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: Literal[12] = 12
    total_pages: int = Field(ge=0)
    topics: tuple[PublicStudyTopicCount, ...]
