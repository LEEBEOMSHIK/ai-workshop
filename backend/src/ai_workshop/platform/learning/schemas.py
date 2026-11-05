from __future__ import annotations

import json
from datetime import date, datetime
from functools import lru_cache
from importlib.resources import files
from typing import TYPE_CHECKING, Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ai_workshop.platform.learning.domain import ExperimentStatus, RecordKind

if TYPE_CHECKING:
    from ai_workshop.platform.learning.references import ReferenceView
    from ai_workshop.platform.learning.repository import LearningSummary
    from ai_workshop.platform.learning.service import LearningListView, LearningRecordView


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReferenceKey(_StrictFrozenModel):
    kind: str
    target: str
    version: str | None = None

    @field_validator("kind", "target")
    @classmethod
    def require_non_blank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reference identity fields must not be blank")
        return value


FiniteMetricValue = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class ExperimentMetric(_StrictFrozenModel):
    name: str
    value: FiniteMetricValue
    unit: str | None = None

    @field_validator("name")
    @classmethod
    def require_non_blank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("metric name must not be blank")
        return value


class TroubleshootingFields(_StrictFrozenModel):
    symptom: str | None = None
    reproduction: str | None = None
    facts: tuple[str, ...] = ()
    hypotheses: tuple[str, ...] = ()
    confirmed_cause: str | None = None
    change: str | None = None
    verification: str | None = None
    unresolved: tuple[str, ...] = ()


class LearningSequence(_StrictFrozenModel):
    series: str = Field(min_length=1)
    # The storage query uses a PostgreSQL signed integer for ordering.
    step: Annotated[int, Field(strict=True, ge=1, le=2147483647)] | None = None
    performed_on: date | None = None
    start_mode: Literal["base_model", "continued", "unknown"] = "unknown"
    source_label: str | None = None
    source_evidence: str | None = None
    objective: str | None = None
    outcome: str | None = None
    remaining: str | None = None
    outcome_status: Literal["improved", "no_improvement", "mixed", "not_evaluated"] = (
        "not_evaluated"
    )

    @field_validator("source_label", "source_evidence", "objective", "outcome", "remaining")
    @classmethod
    def blank_metadata_is_absent(cls, value: str | None) -> str | None:
        # Preserve supplied text, including line breaks, but do not treat blanks as evidence.
        return value if value is not None and value.strip() else None

    @model_validator(mode="after")
    def require_explicit_source_and_observation(self) -> Self:
        if self.start_mode == "continued" and self.source_label is None:
            raise ValueError("continued training requires a source label")
        if self.outcome_status != "not_evaluated" and self.outcome is None:
            raise ValueError("an evaluated outcome requires an observation")
        return self

    @field_validator("series")
    @classmethod
    def trim_series(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("learning series must not be blank")
        return result


class ExperimentFields(_StrictFrozenModel):
    purpose: str | None = None
    hypothesis: str | None = None
    dataset_snapshot: ReferenceKey | None = None
    configurations: tuple[str, ...] = ()
    environment: str | None = None
    procedure: str | None = None
    observations: str | None = None
    metrics: tuple[ExperimentMetric, ...] = ()
    limitations: str | None = None
    conclusion: str | None = None
    next_steps: tuple[str, ...] = ()
    status: ExperimentStatus = ExperimentStatus.PLANNED
    troubleshooting: TroubleshootingFields | None = None
    learning_sequence: LearningSequence | None = None

    @model_validator(mode="after")
    def planned_sequence_has_no_execution(self) -> Self:
        sequence = self.learning_sequence
        if (
            self.status is ExperimentStatus.PLANNED
            and sequence is not None
            and (sequence.step is not None or sequence.performed_on is not None)
        ):
            raise ValueError("planned experiments cannot claim an execution step or date")
        if (
            self.status is ExperimentStatus.PLANNED
            and sequence is not None
            and sequence.outcome_status != "not_evaluated"
        ):
            raise ValueError("planned experiments cannot claim an evaluated outcome")
        return self


class LearningTopic(_StrictFrozenModel):
    key: str
    label: str
    description: str


class _TopicRegistry(_StrictFrozenModel):
    schema_version: Literal[1]
    topics: tuple[LearningTopic, ...]

    @model_validator(mode="after")
    def require_unique_keys(self) -> Self:
        keys = [topic.key for topic in self.topics]
        if len(keys) != len(set(keys)):
            raise ValueError("learning topic keys must be unique")
        return self


@lru_cache(maxsize=1)
def load_learning_topics() -> tuple[LearningTopic, ...]:
    resource = files("ai_workshop.platform.learning").joinpath("topics.json")
    registry = _TopicRegistry.model_validate(json.loads(resource.read_text(encoding="utf-8")))
    return registry.topics


class LearningDraft(_StrictFrozenModel):
    title: str
    body: str
    kind: RecordKind
    topic_keys: tuple[str, ...] = ()
    domain_labels: tuple[str, ...] = ()
    experiment: ExperimentFields | None = None
    references: tuple[ReferenceKey, ...] = ()

    @field_validator("title", "body")
    @classmethod
    def require_non_blank_content(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value

    @field_validator("topic_keys")
    @classmethod
    def require_registered_topics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        known_keys = {topic.key for topic in load_learning_topics()}
        unknown = sorted(set(values) - known_keys)
        if unknown:
            raise ValueError(f"unknown learning topic: {', '.join(unknown)}")
        return values

    @model_validator(mode="after")
    def require_kind_specific_fields(self) -> Self:
        if self.kind is RecordKind.NOTE and self.experiment is not None:
            raise ValueError("note records cannot carry experiment fields")
        return self


class LearningUpdateRequest(_StrictFrozenModel):
    expected_revision: int
    draft: LearningDraft

    @field_validator("expected_revision")
    @classmethod
    def require_positive_revision(cls, value: int) -> int:
        if value < 1:
            raise ValueError("expected revision must be positive")
        return value


class LearningRevisionRequest(_StrictFrozenModel):
    expected_revision: int

    @field_validator("expected_revision")
    @classmethod
    def require_positive_revision(cls, value: int) -> int:
        if value < 1:
            raise ValueError("expected revision must be positive")
        return value


class ReferenceViewResponse(_StrictFrozenModel):
    status: Literal["available", "unavailable"]
    label: str | None
    href: str | None
    key: ReferenceKey | None

    @classmethod
    def from_view(cls, view: ReferenceView) -> ReferenceViewResponse:
        return cls(
            status=view.status.value,
            label=view.label,
            href=view.href,
            key=view.key,
        )


class LearningRecordResponse(_StrictFrozenModel):
    id: UUID
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    draft: LearningDraft
    reference_views: tuple[ReferenceViewResponse, ...]
    dataset_reference_view: ReferenceViewResponse | None
    unavailable_reference_count: int

    @classmethod
    def from_view(cls, view: LearningRecordView) -> LearningRecordResponse:
        return cls(
            id=view.id,
            revision=view.revision,
            created_at=view.created_at,
            updated_at=view.updated_at,
            archived_at=view.archived_at,
            draft=view.draft,
            reference_views=tuple(
                ReferenceViewResponse.from_view(item) for item in view.reference_views
            ),
            dataset_reference_view=(
                ReferenceViewResponse.from_view(view.dataset_reference_view)
                if view.dataset_reference_view is not None
                else None
            ),
            unavailable_reference_count=view.unavailable_reference_count,
        )


class LearningSummaryResponse(_StrictFrozenModel):
    id: UUID
    title: str
    kind: RecordKind
    topic_keys: tuple[str, ...]
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    experiment_status: ExperimentStatus | None = None
    learning_sequence: LearningSequence | None = None

    @classmethod
    def from_summary(cls, summary: LearningSummary) -> LearningSummaryResponse:
        return cls(
            id=summary.id,
            title=summary.title,
            kind=summary.kind,
            topic_keys=summary.topic_keys,
            revision=summary.revision,
            created_at=summary.created_at,
            updated_at=summary.updated_at,
            archived_at=summary.archived_at,
            experiment_status=summary.experiment_status,
            learning_sequence=summary.learning_sequence,
        )


class LearningListResponse(_StrictFrozenModel):
    items: tuple[LearningSummaryResponse, ...]
    next_cursor: str | None

    @classmethod
    def from_view(cls, view: LearningListView) -> LearningListResponse:
        return cls(
            items=tuple(LearningSummaryResponse.from_summary(item) for item in view.items),
            next_cursor=view.next_cursor,
        )


class LearningTopicResponse(_StrictFrozenModel):
    key: str
    label: str
