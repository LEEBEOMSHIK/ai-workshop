from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.assets.domain import AssetVersion, Document, Folder
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord, FolderRecord
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.platform.workspaces.repository import workspace_is_active


class AssetRepository(Protocol):
    async def has_workspace_access(self, user_id: UUID, workspace_id: UUID) -> bool: ...
    async def save(self, document: Document) -> Document: ...
    async def list_documents(self, user_id: UUID, workspace_id: UUID) -> list[Document]: ...
    async def list_folders(self, user_id: UUID, workspace_id: UUID) -> list[Folder]: ...
    async def folder_name_exists(
        self, workspace_id: UUID, parent_id: UUID | None, name: str
    ) -> bool: ...
    async def folder_belongs_to(self, folder_id: UUID, workspace_id: UUID) -> bool: ...
    async def add_folder(self, folder: Folder) -> Folder: ...
    async def find_document_for_user(self, user_id: UUID, document_id: UUID) -> Document | None: ...
    async def save_version(self, document: Document, version: AssetVersion) -> Document: ...
    async def find_version(self, version_id: UUID) -> AssetVersion | None: ...


class SqlAlchemyAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def has_workspace_access(self, user_id: UUID, workspace_id: UUID) -> bool:
        result = await self.session.execute(
            select(WorkspaceMembershipRecord.id)
            .join(
                WorkspaceRecord,
                WorkspaceRecord.id == WorkspaceMembershipRecord.workspace_id,
            )
            .where(
                WorkspaceMembershipRecord.user_id == user_id,
                WorkspaceMembershipRecord.workspace_id == workspace_id,
                workspace_is_active(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def save(self, document: Document) -> Document:
        document_record = DocumentRecord(
            id=document.id,
            workspace_id=document.workspace_id,
            folder_id=document.folder_id,
            name=document.name,
            active_version_id=document.active_version_id,
        )
        self.session.add(document_record)
        await self.session.flush()
        for version in document.versions:
            self.session.add(
                AssetVersionRecord(
                    id=version.id,
                    document_id=version.document_id,
                    number=version.number,
                    object_key=version.object_key,
                    sha256=version.sha256,
                    media_type=version.media_type,
                    size=version.size,
                    status=version.status,
                )
            )
        await self.session.flush()
        return document

    async def list_documents(self, user_id: UUID, workspace_id: UUID) -> list[Document]:
        if not await self.has_workspace_access(user_id, workspace_id):
            return []
        result = await self.session.execute(
            select(DocumentRecord)
            .where(DocumentRecord.workspace_id == workspace_id)
            .order_by(DocumentRecord.name)
        )
        documents: list[Document] = []
        for record in result.scalars():
            version_result = await self.session.execute(
                select(AssetVersionRecord)
                .where(AssetVersionRecord.document_id == record.id)
                .order_by(AssetVersionRecord.number)
            )
            versions = [
                AssetVersion(
                    id=item.id,
                    document_id=item.document_id,
                    number=item.number,
                    object_key=item.object_key,
                    sha256=item.sha256,
                    media_type=item.media_type,
                    size=item.size,
                    status=item.status,
                )
                for item in version_result.scalars()
            ]
            documents.append(
                Document(
                    id=record.id,
                    workspace_id=record.workspace_id,
                    folder_id=record.folder_id,
                    name=record.name,
                    active_version_id=record.active_version_id,
                    versions=versions,
                )
            )
        return documents

    async def list_folders(self, user_id: UUID, workspace_id: UUID) -> list[Folder]:
        if not await self.has_workspace_access(user_id, workspace_id):
            return []
        result = await self.session.execute(
            select(FolderRecord)
            .where(FolderRecord.workspace_id == workspace_id)
            .order_by(FolderRecord.name)
        )
        return [
            Folder(item.id, item.workspace_id, item.parent_id, item.name)
            for item in result.scalars()
        ]

    async def folder_name_exists(
        self,
        workspace_id: UUID,
        parent_id: UUID | None,
        name: str,
    ) -> bool:
        result = await self.session.execute(
            select(FolderRecord.id)
            .where(
                FolderRecord.workspace_id == workspace_id,
                FolderRecord.parent_id == parent_id,
                FolderRecord.name == name,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def folder_belongs_to(self, folder_id: UUID, workspace_id: UUID) -> bool:
        result = await self.session.execute(
            select(FolderRecord.id)
            .where(FolderRecord.id == folder_id, FolderRecord.workspace_id == workspace_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def add_folder(self, folder: Folder) -> Folder:
        self.session.add(
            FolderRecord(
                id=folder.id,
                workspace_id=folder.workspace_id,
                parent_id=folder.parent_id,
                name=folder.name,
            )
        )
        await self.session.flush()
        return folder

    async def find_document_for_user(
        self,
        user_id: UUID,
        document_id: UUID,
    ) -> Document | None:
        result = await self.session.execute(
            select(DocumentRecord)
            .join(
                WorkspaceMembershipRecord,
                WorkspaceMembershipRecord.workspace_id == DocumentRecord.workspace_id,
            )
            .join(WorkspaceRecord, WorkspaceRecord.id == DocumentRecord.workspace_id)
            .where(
                DocumentRecord.id == document_id,
                WorkspaceMembershipRecord.user_id == user_id,
                workspace_is_active(),
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        version_result = await self.session.execute(
            select(AssetVersionRecord)
            .where(AssetVersionRecord.document_id == record.id)
            .order_by(AssetVersionRecord.number)
        )
        versions = [
            AssetVersion(
                id=item.id,
                document_id=item.document_id,
                number=item.number,
                object_key=item.object_key,
                sha256=item.sha256,
                media_type=item.media_type,
                size=item.size,
                status=item.status,
            )
            for item in version_result.scalars()
        ]
        return Document(
            id=record.id,
            workspace_id=record.workspace_id,
            folder_id=record.folder_id,
            name=record.name,
            active_version_id=record.active_version_id,
            versions=versions,
        )

    async def save_version(self, document: Document, version: AssetVersion) -> Document:
        self.session.add(
            AssetVersionRecord(
                id=version.id,
                document_id=version.document_id,
                number=version.number,
                object_key=version.object_key,
                sha256=version.sha256,
                media_type=version.media_type,
                size=version.size,
                status=version.status,
            )
        )
        await self.session.flush()
        return document

    async def find_version(self, version_id: UUID) -> AssetVersion | None:
        record = await self.session.get(AssetVersionRecord, version_id)
        if record is None:
            return None
        return _version_from_record(record)

    async def find_version_for_update(self, version_id: UUID) -> AssetVersion | None:
        record = await self.session.scalar(
            select(AssetVersionRecord)
            .where(AssetVersionRecord.id == version_id)
            .with_for_update()
        )
        if record is None:
            return None
        return _version_from_record(record)


def _version_from_record(record: AssetVersionRecord) -> AssetVersion:
    return AssetVersion(
        id=record.id,
        document_id=record.document_id,
        number=record.number,
        object_key=record.object_key,
        sha256=record.sha256,
        media_type=record.media_type,
        size=record.size,
        status=record.status,
    )
