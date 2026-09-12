from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, StringConstraints

from ai_workshop.platform.assets.domain import AssetVersion, Document, Folder, VersionStatus
from ai_workshop.platform.assets.library import LibraryPage
from ai_workshop.platform.workspaces.schemas import WorkspaceResponse


class FolderCreate(BaseModel):
    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=180),
    ]
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
    workspace_id: UUID
    folder_id: UUID | None
    name: str
    latest_version: int
    active_version_id: UUID | None
    latest_version_id: UUID
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
            workspace_id=document.workspace_id,
            folder_id=document.folder_id,
            name=document.name,
            latest_version=latest.number,
            active_version_id=document.active_version_id,
            latest_version_id=latest.id,
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


class LibraryFolderResponse(FolderResponse):
    has_children: bool


class LibraryPageResponse(BaseModel):
    workspace: WorkspaceResponse
    folder: FolderResponse | None
    ancestors: list[FolderResponse]
    folders: list[LibraryFolderResponse]
    documents: list[DocumentResponse]
    next_folder_cursor: str | None
    next_document_cursor: str | None

    @classmethod
    def from_domain(cls, page: LibraryPage) -> Self:
        return cls(
            workspace=WorkspaceResponse.from_domain(page.workspace),
            folder=(
                FolderResponse.from_domain(page.folder)
                if page.folder is not None
                else None
            ),
            ancestors=[FolderResponse.from_domain(folder) for folder in page.ancestors],
            folders=[
                LibraryFolderResponse(
                    **FolderResponse.from_domain(item.folder).model_dump(),
                    has_children=item.has_children,
                )
                for item in page.folders
            ],
            documents=[
                DocumentResponse.from_domain(document) for document in page.documents
            ],
            next_folder_cursor=page.next_folder_cursor,
            next_document_cursor=page.next_document_cursor,
        )


class AssetVersionPageResponse(BaseModel):
    items: list[AssetVersionResponse]
    next_cursor: str | None
