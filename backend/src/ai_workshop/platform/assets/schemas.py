from uuid import UUID

from pydantic import BaseModel

from ai_workshop.platform.assets.domain import Document, Folder, VersionStatus


class FolderCreate(BaseModel):
    name: str
    parent_id: UUID | None = None


class FolderResponse(BaseModel):
    id: UUID
    name: str
    parent_id: UUID | None

    @classmethod
    def from_domain(cls, folder: Folder) -> "FolderResponse":
        return cls(id=folder.id, name=folder.name, parent_id=folder.parent_id)


class DocumentResponse(BaseModel):
    id: UUID
    name: str
    latest_version: int
    status: VersionStatus

    @classmethod
    def from_domain(cls, document: Document) -> "DocumentResponse":
        latest = document.versions[-1]
        return cls(
            id=document.id,
            name=document.name,
            latest_version=latest.number,
            status=latest.status,
        )
