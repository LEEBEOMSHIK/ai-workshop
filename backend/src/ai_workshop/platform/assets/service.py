from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.platform.assets.domain import AssetVersion, Document, Folder
from ai_workshop.platform.assets.repository import AssetRepository, SqlAlchemyAssetRepository
from ai_workshop.platform.assets.storage import ObjectStore
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.jobs.domain import Job
from ai_workshop.platform.jobs.service import JobService, get_job_service
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".html", ".htm"}


class AssetService:
    def __init__(
        self,
        repository: AssetRepository,
        object_store: ObjectStore,
        *,
        max_upload_bytes: int,
    ) -> None:
        self.repository = repository
        self.object_store = object_store
        self.max_upload_bytes = max_upload_bytes

    async def upload(
        self,
        *,
        user: User,
        workspace_id: UUID,
        folder_id: UUID | None,
        filename: str,
        media_type: str,
        content: AsyncIterator[bytes],
    ) -> Document:
        if not await self.repository.has_workspace_access(user.id, workspace_id):
            raise AppError("not_found", "The requested resource was not found.", 404)
        suffix = Path(filename).suffix.casefold()
        if suffix not in ALLOWED_EXTENSIONS:
            raise AppError("unsupported_document", "This document format is not supported.", 422)

        document = Document.create(workspace_id=workspace_id, folder_id=folder_id, name=filename)
        object_key = f"{workspace_id}/{document.id}/{uuid4().hex}{suffix}"

        async def bounded_content() -> AsyncIterator[bytes]:
            total = 0
            async for chunk in content:
                total += len(chunk)
                if total > self.max_upload_bytes:
                    raise AppError("file_too_large", "The document exceeds the upload limit.", 413)
                yield chunk

        stored = await self.object_store.put(object_key, bounded_content())
        document.new_version(
            object_key=stored.key,
            sha256=stored.sha256,
            media_type=media_type or "application/octet-stream",
            size=stored.size,
        )
        try:
            return await self.repository.save(document)
        except Exception:
            await self.object_store.delete(stored.key)
            raise

    async def list_documents(self, *, user: User, workspace_id: UUID) -> list[Document]:
        if not await self.repository.has_workspace_access(user.id, workspace_id):
            raise AppError("not_found", "The requested resource was not found.", 404)
        return await self.repository.list_documents(user.id, workspace_id)

    async def list_folders(self, *, user: User, workspace_id: UUID) -> list[Folder]:
        if not await self.repository.has_workspace_access(user.id, workspace_id):
            raise AppError("not_found", "The requested resource was not found.", 404)
        return await self.repository.list_folders(user.id, workspace_id)

    async def list_versions(self, *, user: User, document_id: UUID) -> list[AssetVersion]:
        document = await self.repository.find_document_for_user(user.id, document_id)
        if document is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return document.versions

    async def create_folder(
        self,
        *,
        user: User,
        workspace_id: UUID,
        parent_id: UUID | None,
        name: str,
    ) -> Folder:
        if not await self.repository.has_workspace_access(user.id, workspace_id):
            raise AppError("not_found", "The requested resource was not found.", 404)
        clean_name = name.strip()
        if parent_id and not await self.repository.folder_belongs_to(parent_id, workspace_id):
            raise AppError("not_found", "The requested resource was not found.", 404)
        if await self.repository.folder_name_exists(workspace_id, parent_id, clean_name):
            raise AppError("folder_exists", "A folder with this name already exists.", 409)
        return await self.repository.add_folder(
            Folder.create(workspace_id=workspace_id, parent_id=parent_id, name=clean_name)
        )

    async def upload_version(
        self,
        *,
        user: User,
        document_id: UUID,
        filename: str,
        media_type: str,
        content: AsyncIterator[bytes],
    ) -> Document:
        document = await self.repository.find_document_for_user(user.id, document_id)
        if document is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        suffix = Path(filename).suffix.casefold()
        if suffix not in ALLOWED_EXTENSIONS:
            raise AppError("unsupported_document", "This document format is not supported.", 422)
        object_key = f"{document.workspace_id}/{document.id}/{uuid4().hex}{suffix}"

        async def bounded_content() -> AsyncIterator[bytes]:
            total = 0
            async for chunk in content:
                total += len(chunk)
                if total > self.max_upload_bytes:
                    raise AppError("file_too_large", "The document exceeds the upload limit.", 413)
                yield chunk

        stored = await self.object_store.put(object_key, bounded_content())
        version = document.new_version(
            object_key=stored.key,
            sha256=stored.sha256,
            media_type=media_type or "application/octet-stream",
            size=stored.size,
        )
        try:
            return await self.repository.save_version(document, version)
        except Exception:
            await self.object_store.delete(stored.key)
            raise


@dataclass(frozen=True, slots=True)
class AssetUploadResult:
    document: Document
    job: Job
    job_created: bool


class AssetUploadCoordinator:
    def __init__(
        self,
        assets: AssetService,
        jobs: JobService,
        *,
        commit: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.assets = assets
        self.jobs = jobs
        self.commit = commit or _no_op_commit

    async def upload(
        self,
        *,
        user: User,
        workspace_id: UUID,
        folder_id: UUID | None,
        filename: str,
        media_type: str,
        content: AsyncIterator[bytes],
    ) -> AssetUploadResult:
        document = await self.assets.upload(
            user=user,
            workspace_id=workspace_id,
            folder_id=folder_id,
            filename=filename,
            media_type=media_type,
            content=content,
        )
        version = document.versions[-1]
        try:
            creation = await self.jobs.create_asset_verification(
                user_id=user.id,
                workspace_id=document.workspace_id,
                asset_version_id=version.id,
            )
        except Exception:
            await self.assets.object_store.delete(version.object_key)
            raise
        await self.commit()
        return AssetUploadResult(document, creation.job, creation.created)

    async def upload_version(
        self,
        *,
        user: User,
        document_id: UUID,
        filename: str,
        media_type: str,
        content: AsyncIterator[bytes],
    ) -> AssetUploadResult:
        document = await self.assets.upload_version(
            user=user,
            document_id=document_id,
            filename=filename,
            media_type=media_type,
            content=content,
        )
        version = document.versions[-1]
        try:
            creation = await self.jobs.create_asset_verification(
                user_id=user.id,
                workspace_id=document.workspace_id,
                asset_version_id=version.id,
            )
        except Exception:
            await self.assets.object_store.delete(version.object_key)
            raise
        await self.commit()
        return AssetUploadResult(document, creation.job, creation.created)


async def _no_op_commit() -> None:
    return None


def get_asset_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AssetService:
    return AssetService(
        SqlAlchemyAssetRepository(session),
        LocalObjectStore(settings.object_store_root),
        max_upload_bytes=50 * 1024 * 1024,
    )


def get_asset_upload_coordinator(
    assets: Annotated[AssetService, Depends(get_asset_service)],
    jobs: Annotated[JobService, Depends(get_job_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssetUploadCoordinator:
    return AssetUploadCoordinator(assets, jobs, commit=session.commit)
