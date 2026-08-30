from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.platform.assets.domain import AssetVersion, VersionStatus
from ai_workshop.platform.assets.tasks import (
    AssetTaskError,
    AssetVerificationLifecycle,
    AssetVerificationWorkflow,
    verify_stored_asset,
)
from ai_workshop.platform.jobs.domain import Job, JobStatus, JobType


class MemoryLifecycle(AssetVerificationLifecycle):
    def __init__(self, job: Job, version: AssetVersion) -> None:
        self.job = job
        self.version = version

    async def begin(self, job_id) -> AssetVersion:
        assert job_id == self.job.id
        self.job.start(stage="verifying_object")
        return self.version

    async def succeed(self, job_id) -> None:
        assert job_id == self.job.id
        self.job.succeed(stage="stored")

    async def fail(self, job_id, *, error_code: str, error_message: str) -> None:
        assert job_id == self.job.id
        self.job.fail(error_code=error_code, error_message=error_message)


class CompletedLifecycle(AssetVerificationLifecycle):
    def __init__(self, asset_version_id) -> None:
        self.asset_version_id = asset_version_id

    async def begin(self, job_id):
        return None

    async def verified_asset_version_id(self, job_id):
        return self.asset_version_id

    async def succeed(self, job_id) -> None:
        raise AssertionError("A completed job must not run again.")

    async def fail(self, job_id, *, error_code: str, error_message: str) -> None:
        raise AssertionError("A completed job must not run again.")


async def content() -> AsyncIterator[bytes]:
    yield b"verified report"


@pytest.mark.asyncio
async def test_asset_verification_accepts_the_stored_checksum(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)
    stored = await store.put("workspace/document/report.pdf", content())
    version = AssetVersion(
        id=uuid4(),
        document_id=uuid4(),
        number=1,
        object_key=stored.key,
        sha256=stored.sha256,
        media_type="application/pdf",
        size=stored.size,
        status=VersionStatus.STORED,
    )

    await verify_stored_asset(store, version)


@pytest.mark.asyncio
async def test_asset_verification_marks_checksum_mismatch_as_permanent(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)
    stored = await store.put("workspace/document/report.pdf", content())
    version = AssetVersion(
        id=uuid4(),
        document_id=uuid4(),
        number=1,
        object_key=stored.key,
        sha256="0" * 64,
        media_type="application/pdf",
        size=stored.size,
        status=VersionStatus.STORED,
    )

    with pytest.raises(AssetTaskError) as exc_info:
        await verify_stored_asset(store, version)

    assert exc_info.value.code == "checksum_mismatch"
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_asset_verification_marks_missing_object_as_retryable(tmp_path) -> None:
    version = AssetVersion(
        id=uuid4(),
        document_id=uuid4(),
        number=1,
        object_key="missing/report.pdf",
        sha256="0" * 64,
        media_type="application/pdf",
        size=1,
        status=VersionStatus.STORED,
    )

    with pytest.raises(AssetTaskError) as exc_info:
        await verify_stored_asset(LocalObjectStore(tmp_path), version)

    assert exc_info.value.code == "object_unavailable"
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_asset_workflow_persists_successful_terminal_state(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)
    stored = await store.put("workspace/document/report.pdf", content())
    version = AssetVersion(
        id=uuid4(),
        document_id=uuid4(),
        number=1,
        object_key=stored.key,
        sha256=stored.sha256,
        media_type="application/pdf",
        size=stored.size,
        status=VersionStatus.STORED,
    )
    job = Job.create(
        user_id=uuid4(),
        workspace_id=uuid4(),
        asset_version_id=version.id,
        type=JobType.VERIFY_ASSET,
        idempotency_key=f"asset-version:{version.id}",
    )

    verified_asset_version_id = await AssetVerificationWorkflow(
        MemoryLifecycle(job, version), store
    ).run(job.id)

    assert verified_asset_version_id == version.id
    assert job.status is JobStatus.SUCCEEDED
    assert job.stage == "stored"


@pytest.mark.asyncio
async def test_asset_workflow_persists_stable_failure_code(tmp_path) -> None:
    version = AssetVersion(
        id=uuid4(),
        document_id=uuid4(),
        number=1,
        object_key="missing/report.pdf",
        sha256="0" * 64,
        media_type="application/pdf",
        size=1,
        status=VersionStatus.STORED,
    )
    job = Job.create(
        user_id=uuid4(),
        workspace_id=uuid4(),
        asset_version_id=version.id,
        type=JobType.VERIFY_ASSET,
        idempotency_key=f"asset-version:{version.id}",
    )

    with pytest.raises(AssetTaskError):
        await AssetVerificationWorkflow(
            MemoryLifecycle(job, version), LocalObjectStore(tmp_path)
        ).run(job.id)

    assert job.status is JobStatus.FAILED
    assert job.error_code == "object_unavailable"


@pytest.mark.asyncio
async def test_asset_workflow_does_not_repeat_a_completed_job(tmp_path) -> None:
    asset_version_id = uuid4()

    returned_id = await AssetVerificationWorkflow(
        CompletedLifecycle(asset_version_id), LocalObjectStore(tmp_path)
    ).run(uuid4())

    assert returned_id == asset_version_id
