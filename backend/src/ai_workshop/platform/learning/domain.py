from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from ai_workshop.shared.errors import AppError

if TYPE_CHECKING:
    from ai_workshop.platform.learning.schemas import LearningDraft


class RecordKind(StrEnum):
    NOTE = "note"
    EXPERIMENT = "experiment"


class ExperimentStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class LearningRecord:
    id: UUID
    owner_id: UUID
    draft: LearningDraft
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None

    @classmethod
    def create(cls, *, owner_id: UUID, draft: LearningDraft) -> LearningRecord:
        now = datetime.now(UTC)
        return cls(
            id=uuid4(),
            owner_id=owner_id,
            draft=draft,
            revision=1,
            created_at=now,
            updated_at=now,
        )

    def revise(self, draft: LearningDraft, *, expected_revision: int) -> LearningRecord:
        self._require_revision(expected_revision)
        if self.archived_at is not None:
            raise AppError(
                "learning_record_archived",
                "Archived learning records must be restored before editing.",
                409,
            )
        return replace(
            self,
            draft=draft,
            revision=self.revision + 1,
            updated_at=datetime.now(UTC),
        )

    def archive(self, *, expected_revision: int) -> LearningRecord:
        self._require_revision(expected_revision)
        if self.archived_at is not None:
            raise AppError(
                "learning_record_already_archived",
                "The learning record is already archived.",
                409,
            )
        now = datetime.now(UTC)
        return replace(
            self,
            revision=self.revision + 1,
            updated_at=now,
            archived_at=now,
        )

    def restore(self, *, expected_revision: int) -> LearningRecord:
        self._require_revision(expected_revision)
        if self.archived_at is None:
            raise AppError(
                "learning_record_not_archived",
                "Only archived learning records can be restored.",
                409,
            )
        return replace(
            self,
            revision=self.revision + 1,
            updated_at=datetime.now(UTC),
            archived_at=None,
        )

    def _require_revision(self, expected_revision: int) -> None:
        if expected_revision != self.revision:
            raise AppError(
                "learning_revision_conflict",
                "The learning record has changed.",
                409,
            )
