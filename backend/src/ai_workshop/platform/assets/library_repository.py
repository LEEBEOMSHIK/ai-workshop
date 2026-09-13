from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ai_workshop.platform.assets.domain import AssetVersion, Document, Folder, VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord, FolderRecord
from ai_workshop.platform.workspaces.domain import Workspace
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import workspace_read_allowed
from ai_workshop.platform.workspaces.repository import (
    workspace_is_active,
    workspace_personal_owner_matches,
)


@dataclass(frozen=True, slots=True)
class NameCursor:
    name: str
    id: UUID


@dataclass(frozen=True, slots=True)
class VersionCursor:
    number: int
    id: UUID


class LibraryRepository(Protocol):
    async def workspace_for_user(self, user_id: UUID, workspace_id: UUID) -> Workspace | None: ...
    async def folder_for_workspace(self, workspace_id: UUID, folder_id: UUID) -> Folder | None: ...
    async def child_folders(
        self,
        workspace_id: UUID,
        parent_id: UUID | None,
        cursor: NameCursor | None,
        limit: int,
    ) -> list[tuple[Folder, bool]]: ...
    async def child_documents(
        self,
        workspace_id: UUID,
        folder_id: UUID | None,
        cursor: NameCursor | None,
        limit: int,
    ) -> list[Document]: ...
    async def document_for_workspace(
        self, workspace_id: UUID, document_id: UUID
    ) -> Document | None: ...
    async def document_versions(
        self,
        document_id: UUID,
        cursor: VersionCursor | None,
        limit: int,
    ) -> list[AssetVersion]: ...


class SqlAlchemyLibraryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def workspace_for_user(
        self,
        user_id: UUID,
        workspace_id: UUID,
    ) -> Workspace | None:
        record = await self.session.scalar(
            select(WorkspaceRecord)
            .join(
                WorkspaceMembershipRecord,
                WorkspaceMembershipRecord.workspace_id == WorkspaceRecord.id,
            )
            .where(
                WorkspaceRecord.id == workspace_id,
                WorkspaceMembershipRecord.user_id == user_id,
                workspace_read_allowed(user_id),
                workspace_is_active(),
                workspace_personal_owner_matches(user_id),
            )
            .limit(1)
        )
        if record is None:
            return None
        return Workspace(
            id=record.id,
            name=record.name,
            kind=record.kind,
            created_by=record.created_by,
            expires_at=record.expires_at,
        )

    async def folder_for_workspace(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> Folder | None:
        record = await self.session.scalar(
            select(FolderRecord)
            .where(
                FolderRecord.workspace_id == workspace_id,
                FolderRecord.id == folder_id,
            )
            .limit(1)
        )
        return _folder(record) if record is not None else None

    async def child_folders(
        self,
        workspace_id: UUID,
        parent_id: UUID | None,
        cursor: NameCursor | None,
        limit: int,
    ) -> list[tuple[Folder, bool]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        child = aliased(FolderRecord)
        has_children = exists(
            select(child.id).where(
                child.workspace_id == workspace_id,
                child.parent_id == FolderRecord.id,
            )
        ).label("has_children")
        statement = select(FolderRecord, has_children).where(
            FolderRecord.workspace_id == workspace_id,
            FolderRecord.parent_id == parent_id,
        )
        if cursor is not None:
            statement = statement.where(
                or_(
                    FolderRecord.name > cursor.name,
                    and_(FolderRecord.name == cursor.name, FolderRecord.id > cursor.id),
                )
            )
        rows = (
            await self.session.execute(
                statement.order_by(FolderRecord.name, FolderRecord.id).limit(limit)
            )
        ).all()
        return [(_folder(record), bool(has_child)) for record, has_child in rows]

    async def child_documents(
        self,
        workspace_id: UUID,
        folder_id: UUID | None,
        cursor: NameCursor | None,
        limit: int,
    ) -> list[Document]:
        return await self._documents(
            workspace_id=workspace_id,
            folder_id=folder_id,
            document_id=None,
            cursor=cursor,
            limit=limit,
        )

    async def document_for_workspace(
        self,
        workspace_id: UUID,
        document_id: UUID,
    ) -> Document | None:
        rows = await self._documents(
            workspace_id=workspace_id,
            folder_id=None,
            document_id=document_id,
            cursor=None,
            limit=1,
        )
        return rows[0] if rows else None

    async def _documents(
        self,
        *,
        workspace_id: UUID,
        folder_id: UUID | None,
        document_id: UUID | None,
        cursor: NameCursor | None,
        limit: int,
    ) -> list[Document]:
        if limit < 1:
            raise ValueError("limit must be positive")
        latest_number = (
            select(func.max(AssetVersionRecord.number))
            .where(AssetVersionRecord.document_id == DocumentRecord.id)
            .correlate(DocumentRecord)
            .scalar_subquery()
        )
        statement = (
            select(DocumentRecord, AssetVersionRecord)
            .join(
                AssetVersionRecord,
                and_(
                    AssetVersionRecord.document_id == DocumentRecord.id,
                    AssetVersionRecord.number == latest_number,
                ),
            )
            .where(DocumentRecord.workspace_id == workspace_id)
        )
        if document_id is None:
            statement = statement.where(DocumentRecord.folder_id == folder_id)
            if cursor is not None:
                statement = statement.where(
                    or_(
                        DocumentRecord.name > cursor.name,
                        and_(
                            DocumentRecord.name == cursor.name,
                            DocumentRecord.id > cursor.id,
                        ),
                    )
                )
        else:
            statement = statement.where(DocumentRecord.id == document_id)
        rows = (
            await self.session.execute(
                statement.order_by(DocumentRecord.name, DocumentRecord.id).limit(limit)
            )
        ).all()
        return [_document(document, version) for document, version in rows]

    async def document_versions(
        self,
        document_id: UUID,
        cursor: VersionCursor | None,
        limit: int,
    ) -> list[AssetVersion]:
        if limit < 1:
            raise ValueError("limit must be positive")
        statement = select(AssetVersionRecord).where(AssetVersionRecord.document_id == document_id)
        if cursor is not None:
            statement = statement.where(
                or_(
                    AssetVersionRecord.number < cursor.number,
                    and_(
                        AssetVersionRecord.number == cursor.number,
                        AssetVersionRecord.id < cursor.id,
                    ),
                )
            )
        records = (
            await self.session.scalars(
                statement.order_by(
                    AssetVersionRecord.number.desc(),
                    AssetVersionRecord.id.desc(),
                ).limit(limit)
            )
        ).all()
        return [_version(record) for record in records]


def _folder(record: FolderRecord) -> Folder:
    return Folder(
        record.id, record.workspace_id, record.parent_id, record.name, record.metadata_revision
    )


def _version(record: AssetVersionRecord) -> AssetVersion:
    return AssetVersion(
        id=record.id,
        document_id=record.document_id,
        number=record.number,
        object_key=record.object_key,
        sha256=record.sha256,
        media_type=record.media_type,
        size=record.size,
        status=VersionStatus(record.status),
    )


def _document(record: DocumentRecord, latest: AssetVersionRecord) -> Document:
    return Document(
        id=record.id,
        workspace_id=record.workspace_id,
        folder_id=record.folder_id,
        name=record.name,
        active_version_id=record.active_version_id,
        versions=[_version(latest)],
        metadata_revision=record.metadata_revision,
    )
