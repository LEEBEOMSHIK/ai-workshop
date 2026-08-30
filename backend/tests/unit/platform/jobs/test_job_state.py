from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ai_workshop.platform.jobs.domain import (
    InvalidJobTransition,
    Job,
    JobStatus,
    JobType,
)


def queued_job() -> Job:
    return Job.create(
        user_id=uuid4(),
        workspace_id=uuid4(),
        asset_version_id=uuid4(),
        type=JobType.VERIFY_ASSET,
        idempotency_key="verify-asset:version-1",
    )


def test_job_follows_the_allowed_success_path() -> None:
    job = queued_job()
    started_at = datetime(2026, 8, 29, 1, 0, tzinfo=UTC)
    finished_at = datetime(2026, 8, 29, 1, 1, tzinfo=UTC)

    job.start(stage="verifying_object", at=started_at)
    job.succeed(stage="stored", at=finished_at)

    assert job.status is JobStatus.SUCCEEDED
    assert job.stage == "stored"
    assert job.attempt == 1
    assert job.started_at == started_at
    assert job.finished_at == finished_at


def test_terminal_job_cannot_transition_again() -> None:
    job = queued_job()
    job.start(stage="verifying_object")
    job.fail(error_code="checksum_mismatch", error_message="Checksum mismatch")

    with pytest.raises(InvalidJobTransition):
        job.start(stage="verifying_object")


def test_running_rag_job_advances_stage_without_starting_another_attempt() -> None:
    job = Job.create(
        user_id=uuid4(),
        workspace_id=uuid4(),
        asset_version_id=uuid4(),
        type=JobType.RAG_INGESTION,
        idempotency_key="asset:profile:rag_ingestion",
    )

    job.start(stage="parsing")
    job.advance(stage="chunking")

    assert job.status is JobStatus.RUNNING
    assert job.stage == "chunking"
    assert job.attempt == 1
