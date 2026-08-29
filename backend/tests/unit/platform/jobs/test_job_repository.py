from uuid import uuid4

from ai_workshop.platform.jobs.domain import JobStatus, JobType
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.jobs.repository import _to_domain


def test_database_strings_are_normalized_to_job_enums() -> None:
    record = JobRecord(
        id=uuid4(),
        user_id=uuid4(),
        workspace_id=uuid4(),
        asset_version_id=uuid4(),
        type="verify_asset",
        idempotency_key="asset-version:test",
        status="queued",
        stage="queued",
        attempt=0,
        error_code=None,
        error_message=None,
        started_at=None,
        finished_at=None,
    )

    job = _to_domain(record)

    assert job.type is JobType.VERIFY_ASSET
    assert job.status is JobStatus.QUEUED
