from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.jobs.ownership import JobOwnershipError, validate_identity
from ai_workshop.platform.jobs.repository import _to_domain


def candidate():
    return Job.create(
        user_id=uuid4(),
        workspace_id=uuid4(),
        asset_version_id=uuid4(),
        type=JobType.VERIFY_ASSET,
        idempotency_key="synthetic",
    )


def test_new_revision_is_one_but_domain_transitions_do_not_increment():
    job = candidate()
    assert job.revision == 1
    job.start(stage="running")
    job.succeed(stage="ready")
    assert job.revision == 1


def test_unsaved_legacy_record_hydrates_null_revision():
    job = candidate()
    record = JobRecord(
        id=job.id,
        user_id=job.user_id,
        workspace_id=job.workspace_id,
        asset_version_id=job.asset_version_id,
        type=job.type,
        idempotency_key=job.idempotency_key,
        status=job.status,
        stage=job.stage,
        attempt=job.attempt,
    )
    assert _to_domain(record).revision is None
    validate_identity(record, replace(job, revision=None))
    for field in ["user_id", "workspace_id", "asset_version_id"]:
        with pytest.raises(JobOwnershipError, match="job_identity_mismatch"):
            validate_identity(record, replace(job, **{field: uuid4()}))


def test_unknown_error_details_are_not_exposed():
    with pytest.raises(ValueError, match="unsupported job ownership error"):
        JobOwnershipError("private/path")
