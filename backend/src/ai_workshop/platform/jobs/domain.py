from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobType(StrEnum):
    VERIFY_ASSET = "verify_asset"


class InvalidJobTransition(ValueError):
    pass


@dataclass(slots=True)
class Job:
    id: UUID
    user_id: UUID
    workspace_id: UUID
    asset_version_id: UUID
    type: JobType
    idempotency_key: str
    status: JobStatus = JobStatus.QUEUED
    stage: str = "queued"
    attempt: int = 0
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        user_id: UUID,
        workspace_id: UUID,
        asset_version_id: UUID,
        type: JobType,
        idempotency_key: str,
    ) -> "Job":
        return cls(
            id=uuid4(),
            user_id=user_id,
            workspace_id=workspace_id,
            asset_version_id=asset_version_id,
            type=type,
            idempotency_key=idempotency_key,
        )

    def start(self, *, stage: str, at: datetime | None = None) -> None:
        self._require_status(JobStatus.QUEUED)
        self.status = JobStatus.RUNNING
        self.stage = stage
        self.attempt += 1
        self.started_at = at or datetime.now(UTC)

    def succeed(self, *, stage: str, at: datetime | None = None) -> None:
        self._require_status(JobStatus.RUNNING)
        self.status = JobStatus.SUCCEEDED
        self.stage = stage
        self.finished_at = at or datetime.now(UTC)

    def fail(
        self,
        *,
        error_code: str,
        error_message: str,
        at: datetime | None = None,
    ) -> None:
        self._require_status(JobStatus.RUNNING)
        self.status = JobStatus.FAILED
        self.stage = "failed"
        self.error_code = error_code
        self.error_message = error_message
        self.finished_at = at or datetime.now(UTC)

    def _require_status(self, expected: JobStatus) -> None:
        if self.status is not expected:
            raise InvalidJobTransition(f"Cannot transition job from {self.status}.")
