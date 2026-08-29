from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest

from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.platform.assets.domain import AssetVersion, Document, VersionStatus
from ai_workshop.platform.assets.repository import AssetRepository
from ai_workshop.platform.assets.service import AssetService
from ai_workshop.platform.identity.domain import User, UserRole
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

    async def find_document_for_user(self, user_id: UUID, document_id: UUID) -> Document | None:
        if self.allowed and self.saved and self.saved.id == document_id:
            return self.saved
        return None

    async def save_version(self, document: Document, version: AssetVersion) -> Document:
        self.saved = document
        return document


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
        content=content(),
    )

    assert [version.number for version in updated.versions] == [1, 2]
