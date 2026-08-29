from uuid import UUID

from pydantic import BaseModel

from ai_workshop.platform.assets.domain import AssetVersion, Document, Folder, VersionStatus


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
    job_id: UUID | None = None

    @classmethod
    def from_domain(
        cls,
        document: Document,
        *,
        job_id: UUID | None = None,
    ) -> "DocumentResponse":
        latest = document.versions[-1]
        return cls(
            id=document.id,
            name=document.name,
            latest_version=latest.number,
            status=latest.status,
            job_id=job_id,
        )


class AssetVersionResponse(BaseModel):
    id: UUID
    number: int
    media_type: str
    size: int
    status: VersionStatus

    @classmethod
    def from_domain(cls, version: AssetVersion) -> "AssetVersionResponse":
        return cls(
            id=version.id,
            number=version.number,
            media_type=version.media_type,
            size=version.size,
            status=version.status,
        )
