"""Transactional location changes and the shared folder hierarchy policy."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.platform.assets.domain import Document, Folder
from ai_workshop.platform.assets.folder_names import folder_name_key
from ai_workshop.platform.assets.repository import AssetRepository, SqlAlchemyAssetRepository
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError


def revision_conflict() -> AppError:
    return AppError("asset_revision_conflict", "The asset changed. Reload and confirm again.", 409)


def hierarchy_invalid() -> AppError:
    return AppError("folder_hierarchy_invalid", "The folder hierarchy needs repair.", 409)


class FolderHierarchy:
    def __init__(self, folders: list[Folder], *, max_depth: int) -> None:
        self.folders = {folder.id: folder for folder in folders}
        self.max_depth = max_depth

    def depth(self, folder_id: UUID | None) -> int:
        seen: set[UUID] = set()
        while folder_id is not None:
            if folder_id in seen or folder_id not in self.folders:
                raise hierarchy_invalid()
            seen.add(folder_id)
            folder_id = self.folders[folder_id].parent_id
        return len(seen)

    def validate_create(self, parent_id: UUID | None) -> None:
        self._check_depth(self.depth(parent_id) + 1)

    def _check_depth(self, depth: int) -> None:
        if depth > self.max_depth:
            raise AppError(
                "folder_depth_exceeded", "The folder depth limit would be exceeded.", 409
            )

    def validate_move(self, source_id: UUID, destination_id: UUID | None) -> set[UUID]:
        self.depth(source_id)
        destination_depth = self.depth(destination_id)
        children: dict[UUID, list[UUID]] = {}
        for folder in self.folders.values():
            if folder.parent_id is not None:
                children.setdefault(folder.parent_id, []).append(folder.id)
        pending = [(source_id, 1)]
        seen: set[UUID] = set()
        height = 0
        while pending:
            current, level = pending.pop()
            if current in seen:
                raise hierarchy_invalid()
            seen.add(current)
            height = max(height, level)
            pending.extend((child, level + 1) for child in children.get(current, []))
        if destination_id in seen:
            raise AppError("folder_cycle", "A folder cannot move into itself or a descendant.", 409)
        self._check_depth(destination_depth + height)
        return seen


class AssetMovementService:
    def __init__(self, repository: AssetRepository, *, max_depth: int) -> None:
        self.repository = repository
        self.max_depth = max_depth

    async def move_document(
        self,
        *,
        user: User,
        workspace_id: UUID,
        document_id: UUID,
        destination_folder_id: UUID | None,
        expected_revision: int,
    ) -> tuple[Document, bool]:
        await self.repository.require_workspace_write(user.id, workspace_id, lock=True)
        document = await self.repository.find_document_for_user(user.id, document_id)
        if document is None or document.workspace_id != workspace_id:
            raise AppError("not_found", "The requested resource was not found.", 404)
        await self._require_destination(workspace_id, destination_folder_id)
        if document.metadata_revision != expected_revision:
            raise revision_conflict()
        folders = await self.repository.list_folders(user.id, workspace_id)
        hierarchy = FolderHierarchy(folders, max_depth=self.max_depth)
        hierarchy.depth(document.folder_id)
        hierarchy.depth(destination_folder_id)
        if document.folder_id == destination_folder_id:
            return document, False
        if not await self.repository.move_document_location(
            workspace_id, document_id, destination_folder_id, expected_revision
        ):
            raise revision_conflict()
        document.folder_id = destination_folder_id
        document.metadata_revision += 1
        return document, True

    async def _require_destination(self, workspace_id: UUID, destination_id: UUID | None) -> None:
        if destination_id is not None and not await self.repository.folder_belongs_to(
            destination_id, workspace_id
        ):
            raise AppError("not_found", "The requested resource was not found.", 404)

    async def move_folder(
        self,
        *,
        user: User,
        workspace_id: UUID,
        folder_id: UUID,
        destination_folder_id: UUID | None,
        expected_revision: int,
    ) -> tuple[Folder, bool]:
        await self.repository.require_workspace_write(user.id, workspace_id, lock=True)
        folders = await self.repository.list_folders(user.id, workspace_id)
        source = next((folder for folder in folders if folder.id == folder_id), None)
        if source is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        await self._require_destination(workspace_id, destination_folder_id)
        if source.metadata_revision != expected_revision:
            raise revision_conflict()
        hierarchy = FolderHierarchy(folders, max_depth=self.max_depth)
        subtree = hierarchy.validate_move(source.id, destination_folder_id)
        if await self.repository.has_foreign_folder_children(workspace_id, subtree):
            raise hierarchy_invalid()
        if source.parent_id == destination_folder_id:
            return source, False
        if any(
            folder.id != source.id
            and folder.parent_id == destination_folder_id
            and folder_name_key(folder.name) == folder_name_key(source.name)
            for folder in folders
        ):
            raise AppError("folder_exists", "A folder with this name already exists.", 409)
        if not await self.repository.move_folder_location(
            workspace_id, folder_id, destination_folder_id, expected_revision
        ):
            raise revision_conflict()
        source.parent_id = destination_folder_id
        source.metadata_revision += 1
        return source, True


def get_asset_movement_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AssetMovementService:
    return AssetMovementService(
        SqlAlchemyAssetRepository(session), max_depth=settings.library_max_depth
    )
