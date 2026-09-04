from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest

from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.platform.assets.domain import AssetVersion, Document, VersionStatus
from ai_workshop.platform.assets.repository import AssetRepository
from ai_workshop.platform.assets.service import AssetService, AssetUploadCoordinator
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.platform.jobs.repository import JobRepository
from ai_workshop.platform.jobs.service import JobService
from ai_workshop.shared.errors import AppError


class MemoryAssetRepository(AssetRepository):
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.saved: Document | None = None

    async def has_workspace_access(self, user_id: UUID, workspace_id: UUID) -> bool:
        return self.allowed

    async def save(self, document: Document) -> Document:
        self.saved = document
        return document

    async def workspace_contains_sha256(self, workspace_id: UUID, sha256: str) -> bool:
        return bool(
            self.saved
            and self.saved.workspace_id == workspace_id
            and any(version.sha256 == sha256 for version in self.saved.versions)
        )

    async def find_document_for_user(self, user_id: UUID, document_id: UUID) -> Document | None:
        if self.allowed and self.saved and self.saved.id == document_id:
            return self.saved
        return None

    async def save_version(self, document: Document, version: AssetVersion) -> Document:
        self.saved = document
        return document

    async def find_version(self, version_id: UUID) -> AssetVersion | None:
        if self.saved is None:
            return None
        return next((version for version in self.saved.versions if version.id == version_id), None)


class MemoryJobRepository(JobRepository):
    def __init__(self) -> None:
        self.jobs: list[Job] = []

    async def find_by_idempotency(
        self, user_id: UUID, type: JobType, idempotency_key: str
    ) -> Job | None:
        return next(
            (
                job
                for job in self.jobs
                if job.user_id == user_id
                and job.type is type
                and job.idempotency_key == idempotency_key
            ),
            None,
        )

    async def add(self, job: Job) -> Job:
        self.jobs.append(job)
        return job

    async def find_for_user(self, user_id: UUID, job_id: UUID) -> Job | None:
        return next((job for job in self.jobs if job.id == job_id and job.user_id == user_id), None)

    async def find_by_id(self, job_id: UUID) -> Job | None:
        return next((job for job in self.jobs if job.id == job_id), None)

    async def update(self, job: Job) -> Job:
        return job


class FailingJobRepository(MemoryJobRepository):
    async def add(self, job: Job) -> Job:
        raise RuntimeError("database unavailable")


def owner() -> User:
    return User(
        id=uuid4(),
        display_name="Owner",
        email="owner@example.com",
        normalized_email="owner@example.com",
        password_hash="hash",
        role=UserRole.OWNER,
    )


async def content() -> AsyncIterator[bytes]:
    yield b"quarterly report"


async def changed_content() -> AsyncIterator[bytes]:
    yield b"changed quarterly report"


@pytest.mark.asyncio
async def test_upload_stores_allowed_document_and_creates_version(tmp_path) -> None:
    repository = MemoryAssetRepository()
    service = AssetService(repository, LocalObjectStore(tmp_path), max_upload_bytes=1024)

    document = await service.upload(
        user=owner(),
        workspace_id=uuid4(),
        folder_id=None,
        filename="quarterly-report.pdf",
        media_type="application/pdf",
        content=content(),
    )

    version = document.versions[0]
    assert version.number == 1
    assert version.status is VersionStatus.STORED
    assert version.size == 16
    assert (tmp_path / version.object_key).read_bytes() == b"quarterly report"


@pytest.mark.asyncio
async def test_upload_hides_workspace_without_membership(tmp_path) -> None:
    service = AssetService(
        MemoryAssetRepository(allowed=False),
        LocalObjectStore(tmp_path),
        max_upload_bytes=1024,
    )

    with pytest.raises(AppError) as exc_info:
        await service.upload(
            user=owner(),
            workspace_id=uuid4(),
            folder_id=None,
            filename="quarterly-report.pdf",
            media_type="application/pdf",
            content=content(),
        )

    assert exc_info.value.status_code == 404
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.asyncio
async def test_upload_rejects_exact_content_duplicate_in_same_workspace(tmp_path) -> None:
    repository = MemoryAssetRepository()
    service = AssetService(repository, LocalObjectStore(tmp_path), max_upload_bytes=1024)
    user = owner()
    workspace_id = uuid4()
    await service.upload(
        user=user,
        workspace_id=workspace_id,
        folder_id=None,
        filename="quarterly-report.pdf",
        media_type="application/pdf",
        content=content(),
    )

    with pytest.raises(AppError) as exc_info:
        await service.upload(
            user=user,
            workspace_id=workspace_id,
            folder_id=None,
            filename="renamed-copy.pdf",
            media_type="application/pdf",
            content=content(),
        )

    assert exc_info.value.code == "duplicate_document_content"
    assert exc_info.value.status_code == 409
    assert len(list(tmp_path.rglob("*.pdf"))) == 1


@pytest.mark.asyncio
async def test_upload_allows_same_filename_when_content_differs(tmp_path) -> None:
    repository = MemoryAssetRepository()
    service = AssetService(repository, LocalObjectStore(tmp_path), max_upload_bytes=1024)
    user = owner()
    workspace_id = uuid4()
    first = await service.upload(
        user=user,
        workspace_id=workspace_id,
        folder_id=None,
        filename="quarterly-report.pdf",
        media_type="application/pdf",
        content=content(),
    )

    second = await service.upload(
        user=user,
        workspace_id=workspace_id,
        folder_id=None,
        filename="quarterly-report.pdf",
        media_type="application/pdf",
        content=changed_content(),
    )

    assert first.id != second.id
    assert first.versions[0].sha256 != second.versions[0].sha256


@pytest.mark.asyncio
async def test_upload_allows_exact_content_in_a_different_workspace(tmp_path) -> None:
    repository = MemoryAssetRepository()
    service = AssetService(repository, LocalObjectStore(tmp_path), max_upload_bytes=1024)
    user = owner()
    first = await service.upload(
        user=user,
        workspace_id=uuid4(),
        folder_id=None,
        filename="quarterly-report.pdf",
        media_type="application/pdf",
        content=content(),
    )

    second = await service.upload(
        user=user,
        workspace_id=uuid4(),
        folder_id=None,
        filename="quarterly-report.pdf",
        media_type="application/pdf",
        content=content(),
    )

    assert first.workspace_id != second.workspace_id
    assert first.versions[0].sha256 == second.versions[0].sha256


@pytest.mark.asyncio
async def test_upload_version_increments_existing_document(tmp_path) -> None:
    repository = MemoryAssetRepository()
    service = AssetService(repository, LocalObjectStore(tmp_path), max_upload_bytes=1024)
    user = owner()
    document = await service.upload(
        user=user,
        workspace_id=uuid4(),
        folder_id=None,
        filename="quarterly-report.pdf",
        media_type="application/pdf",
        content=content(),
    )

    updated = await service.upload_version(
        user=user,
        document_id=document.id,
        filename="quarterly-report.pdf",
        media_type="application/pdf",
        content=changed_content(),
    )

    assert [version.number for version in updated.versions] == [1, 2]


@pytest.mark.asyncio
async def test_upload_version_rejects_unchanged_exact_content(tmp_path) -> None:
    repository = MemoryAssetRepository()
    service = AssetService(repository, LocalObjectStore(tmp_path), max_upload_bytes=1024)
    user = owner()
    document = await service.upload(
        user=user,
        workspace_id=uuid4(),
        folder_id=None,
        filename="quarterly-report.pdf",
        media_type="application/pdf",
        content=content(),
    )

    with pytest.raises(AppError) as exc_info:
        await service.upload_version(
            user=user,
            document_id=document.id,
            filename="quarterly-report.pdf",
            media_type="application/pdf",
            content=content(),
        )

    assert exc_info.value.code == "duplicate_document_content"
    assert [version.number for version in document.versions] == [1]
    assert len(list(tmp_path.rglob("*.pdf"))) == 1


@pytest.mark.asyncio
async def test_upload_coordinator_creates_a_durable_verification_job(tmp_path) -> None:
    asset_service = AssetService(
        MemoryAssetRepository(), LocalObjectStore(tmp_path), max_upload_bytes=1024
    )
    job_repository = MemoryJobRepository()
    commit_count = 0

    async def commit() -> None:
        nonlocal commit_count
        commit_count += 1

    coordinator = AssetUploadCoordinator(
        asset_service,
        JobService(job_repository),
        commit=commit,
    )
    user = owner()

    result = await coordinator.upload(
        user=user,
        workspace_id=uuid4(),
        folder_id=None,
        filename="quarterly-report.pdf",
        media_type="application/pdf",
        content=content(),
    )

    assert result.job.status.value == "queued"
    assert result.job.asset_version_id == result.document.versions[-1].id
    assert result.job_created is True
    assert job_repository.jobs == [result.job]
    assert commit_count == 1


@pytest.mark.asyncio
async def test_upload_removes_object_when_durable_job_creation_fails(tmp_path) -> None:
    asset_service = AssetService(
        MemoryAssetRepository(), LocalObjectStore(tmp_path), max_upload_bytes=1024
    )
    coordinator = AssetUploadCoordinator(asset_service, JobService(FailingJobRepository()))

    with pytest.raises(RuntimeError, match="database unavailable"):
        await coordinator.upload(
            user=owner(),
            workspace_id=uuid4(),
            folder_id=None,
            filename="quarterly-report.pdf",
            media_type="application/pdf",
            content=content(),
        )

    assert list(tmp_path.rglob("*.pdf")) == []
