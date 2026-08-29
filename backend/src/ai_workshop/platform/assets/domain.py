from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4


class VersionStatus(StrEnum):
    STORED = "stored"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AssetVersion:
    id: UUID
    document_id: UUID
    number: int
    object_key: str
    sha256: str
    media_type: str
    size: int
    status: VersionStatus


@dataclass(slots=True)
class Folder:
    id: UUID
    workspace_id: UUID
    parent_id: UUID | None
    name: str

    @classmethod
    def create(
        cls,
        *,
        workspace_id: UUID,
        parent_id: UUID | None,
        name: str,
    ) -> "Folder":
        return cls(uuid4(), workspace_id, parent_id, name.strip())

    def move_to(
        self,
        new_parent_id: UUID | None,
        *,
        new_parent_ancestors: tuple[UUID, ...],
    ) -> None:
        if new_parent_id == self.id or self.id in new_parent_ancestors:
            raise ValueError("A folder move cannot create a cycle.")
        self.parent_id = new_parent_id


@dataclass(slots=True)
class Document:
    id: UUID
    workspace_id: UUID
    folder_id: UUID | None
    name: str
    active_version_id: UUID | None = None
    versions: list[AssetVersion] = field(default_factory=list)

    @classmethod
    def create(cls, *, workspace_id: UUID, folder_id: UUID | None, name: str) -> "Document":
        return cls(uuid4(), workspace_id, folder_id, name.strip())

    def new_version(
        self,
        *,
        object_key: str,
        sha256: str,
        media_type: str,
        size: int,
    ) -> AssetVersion:
        version = AssetVersion(
            id=uuid4(),
            document_id=self.id,
            number=len(self.versions) + 1,
            object_key=object_key,
            sha256=sha256,
            media_type=media_type,
            size=size,
            status=VersionStatus.STORED,
        )
        self.versions.append(version)
        return version
