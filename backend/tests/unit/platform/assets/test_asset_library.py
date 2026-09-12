from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.config import Settings
from ai_workshop.platform.assets.domain import AssetVersion, Document, Folder, VersionStatus
from ai_workshop.platform.assets.library import LibraryFolder, LibraryPage, LibraryService
from ai_workshop.platform.assets.library_repository import NameCursor, VersionCursor
from ai_workshop.platform.assets.schemas import (
    DocumentResponse,
    FolderCreate,
    LibraryPageResponse,
)
from ai_workshop.platform.assets.service import AssetService
from ai_workshop.platform.assets.storage import StoredObject
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.workspaces.domain import Workspace, WorkspaceKind
from ai_workshop.shared.errors import AppError


class RecordingStore:
    def __init__(self) -> None:
        self.writes: list[str] = []

    async def put(self, key: str, source: AsyncIterator[bytes]) -> StoredObject:
        self.writes.append(key)
        payload = b"".join([chunk async for chunk in source])
        return StoredObject(key=key, size=len(payload), sha256="0" * 64)

    async def open(self, key: str) -> AsyncIterator[bytes]:
        if False:
            yield key.encode()

    async def delete(self, key: str) -> None:
        return None


class GuardRepository:
    def __init__(self, *, folder_allowed: bool = True) -> None:
        self.folder_allowed = folder_allowed
        self.added_folders: list[Folder] = []

    async def has_workspace_access(self, user_id: UUID, workspace_id: UUID) -> bool:
        return True

    async def require_workspace_write(
        self, user_id: UUID, workspace_id: UUID, *, lock: bool = False
    ) -> None:
        return None

    async def folder_belongs_to(self, folder_id: UUID, workspace_id: UUID) -> bool:
        return self.folder_allowed

    async def workspace_contains_sha256(self, workspace_id: UUID, sha256: str) -> bool:
        return False

    async def save(self, document: Document) -> Document:
        return document

    async def folder_name_exists(
        self,
        workspace_id: UUID,
        parent_id: UUID | None,
        name: str,
    ) -> bool:
        return False

    async def add_folder(self, folder: Folder) -> Folder:
        self.added_folders.append(folder)
        return folder


class MemoryLibraryRepository:
    def __init__(
        self,
        *,
        workspace: Workspace | None,
        folders: tuple[Folder, ...] = (),
        documents: tuple[Document, ...] = (),
    ) -> None:
        self.workspace = workspace
        self.folders = folders
        self.documents = documents
        self.row_fetches = 0

    async def workspace_for_user(
        self,
        user_id: UUID,
        workspace_id: UUID,
    ) -> Workspace | None:
        if self.workspace is None or self.workspace.id != workspace_id:
            return None
        return self.workspace

    async def folder_for_workspace(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> Folder | None:
        return next(
            (
                folder
                for folder in self.folders
                if folder.id == folder_id and folder.workspace_id == workspace_id
            ),
            None,
        )

    async def child_folders(
        self,
        workspace_id: UUID,
        parent_id: UUID | None,
        cursor: NameCursor | None,
        limit: int,
    ) -> list[tuple[Folder, bool]]:
        self.row_fetches += 1
        rows = sorted(
            (
                folder
                for folder in self.folders
                if folder.workspace_id == workspace_id and folder.parent_id == parent_id
            ),
            key=lambda folder: (folder.name, folder.id),
        )
        if cursor is not None:
            rows = [row for row in rows if (row.name, row.id) > (cursor.name, cursor.id)]
        return [
            (
                row,
                any(child.parent_id == row.id for child in self.folders),
            )
            for row in rows[:limit]
        ]

    async def child_documents(
        self,
        workspace_id: UUID,
        folder_id: UUID | None,
        cursor: NameCursor | None,
        limit: int,
    ) -> list[Document]:
        self.row_fetches += 1
        rows = sorted(
            (
                document
                for document in self.documents
                if document.workspace_id == workspace_id and document.folder_id == folder_id
            ),
            key=lambda document: (document.name, document.id),
        )
        if cursor is not None:
            rows = [row for row in rows if (row.name, row.id) > (cursor.name, cursor.id)]
        return rows[:limit]

    async def document_for_workspace(
        self,
        workspace_id: UUID,
        document_id: UUID,
    ) -> Document | None:
        self.row_fetches += 1
        return next(
            (
                document
                for document in self.documents
                if document.id == document_id and document.workspace_id == workspace_id
            ),
            None,
        )

    async def document_versions(
        self,
        document_id: UUID,
        cursor: VersionCursor | None,
        limit: int,
    ) -> list[AssetVersion]:
        self.row_fetches += 1
        document = next(item for item in self.documents if item.id == document_id)
        rows = sorted(
            document.versions,
            key=lambda version: (version.number, version.id),
            reverse=True,
        )
        if cursor is not None:
            rows = [row for row in rows if (row.number, row.id) < (cursor.number, cursor.id)]
        return rows[:limit]


def member() -> User:
    return User(
        id=uuid4(),
        display_name="Synthetic member",
        email="member@example.test",
        normalized_email="member@example.test",
        password_hash="synthetic-hash",
        role=UserRole.MEMBER,
    )


async def chunks() -> AsyncIterator[bytes]:
    yield b"synthetic public text"


def workspace() -> Workspace:
    actor = member()
    return Workspace.create(name="Synthetic library", kind=WorkspaceKind.TEAM, creator=actor)


def document(
    workspace_id: UUID,
    *,
    name: str,
    folder_id: UUID | None = None,
    version_count: int = 1,
) -> Document:
    item = Document.create(workspace_id=workspace_id, folder_id=folder_id, name=name)
    for number in range(1, version_count + 1):
        item.versions.append(
            AssetVersion(
                id=uuid4(),
                document_id=item.id,
                number=number,
                object_key=f"synthetic/{item.id}/v{number}.md",
                sha256=str(number) * 64,
                media_type="text/markdown",
                size=number,
                status=VersionStatus.READY,
            )
        )
    item.active_version_id = item.versions[0].id
    return item


def library_service(repository: MemoryLibraryRepository, *, max_depth: int = 64) -> LibraryService:
    return LibraryService(
        repository,
        secret_key="synthetic-library-secret-key-value",
        default_page_size=2,
        max_page_size=3,
        max_depth=max_depth,
        cursor_max_chars=4096,
    )


def test_document_response_exposes_server_owned_location_and_version_ids() -> None:
    workspace_id = uuid4()
    folder_id = uuid4()
    document = Document.create(
        workspace_id=workspace_id,
        folder_id=folder_id,
        name="synthetic.md",
    )
    active = document.new_version(
        object_key="synthetic/v1.md",
        sha256="1" * 64,
        media_type="text/markdown",
        size=10,
    )
    latest = document.new_version(
        object_key="synthetic/v2.md",
        sha256="2" * 64,
        media_type="text/markdown",
        size=20,
    )
    document.active_version_id = active.id

    response = DocumentResponse.from_domain(document)

    assert response.workspace_id == workspace_id
    assert response.folder_id == folder_id
    assert response.active_version_id == active.id
    assert response.latest_version_id == latest.id


def test_library_page_response_preserves_platform_domain_payload() -> None:
    space = workspace()
    folder = Folder(uuid4(), space.id, None, "Reports")
    child = Folder(uuid4(), space.id, folder.id, "Annual")
    item = document(space.id, folder_id=folder.id, name="status.md")
    item.versions.append(
        AssetVersion(
            id=uuid4(),
            document_id=item.id,
            number=2,
            object_key="synthetic/status-v2.md",
            sha256="2" * 64,
            media_type="text/markdown",
            size=2,
            status=VersionStatus.PROCESSING,
        )
    )
    page = LibraryPage(
        workspace=space,
        folder=folder,
        ancestors=(),
        folders=(LibraryFolder(child, True),),
        documents=(item,),
        next_folder_cursor="next-folder",
        next_document_cursor="next-document",
    )

    response = LibraryPageResponse.from_domain(page)

    assert response.workspace.id == space.id
    assert response.folder is not None and response.folder.id == folder.id
    assert response.folders[0].id == child.id
    assert response.folders[0].has_children is True
    assert response.documents[0].status is VersionStatus.PROCESSING
    assert response.documents[0].active_version_id == item.active_version_id
    assert response.next_folder_cursor == "next-folder"
    assert response.next_document_cursor == "next-document"


@pytest.mark.parametrize("name", ["", "   ", "x" * 181])
def test_folder_create_rejects_blank_or_oversized_trimmed_names(name: str) -> None:
    with pytest.raises(ValidationError):
        FolderCreate(name=name)


def test_library_settings_default_and_maximum_are_consistent() -> None:
    settings = Settings(_env_file=None, secret_key="x" * 32)

    assert settings.library_page_size == 50
    assert settings.library_max_page_size == 200
    assert settings.library_max_depth == 64
    assert settings.library_cursor_max_chars == 4096
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            secret_key="x" * 32,
            library_page_size=100,
            library_max_page_size=50,
        )


@pytest.mark.asyncio
async def test_upload_rejects_foreign_folder_before_storage_write() -> None:
    repository = GuardRepository(folder_allowed=False)
    store = RecordingStore()
    service = AssetService(repository, store, max_upload_bytes=1024)  # type: ignore[arg-type]

    with pytest.raises(AppError) as failure:
        await service.upload(
            user=member(),
            workspace_id=uuid4(),
            folder_id=uuid4(),
            filename="synthetic.md",
            media_type="text/markdown",
            content=chunks(),
        )

    assert failure.value.status_code == 404
    assert store.writes == []


@pytest.mark.parametrize("name", ["   ", "x" * 181])
@pytest.mark.asyncio
async def test_create_folder_rejects_invalid_trimmed_names_in_service(name: str) -> None:
    repository = GuardRepository()
    service = AssetService(repository, RecordingStore(), max_upload_bytes=1024)  # type: ignore[arg-type]

    with pytest.raises(AppError) as failure:
        await service.create_folder(
            user=member(),
            workspace_id=uuid4(),
            parent_id=None,
            name=name,
        )

    assert failure.value.status_code == 422
    assert repository.added_folders == []


@pytest.mark.asyncio
async def test_browse_returns_only_direct_root_and_child_rows_with_ancestors() -> None:
    space = workspace()
    root = Folder(uuid4(), space.id, None, "Root")
    child = Folder(uuid4(), space.id, root.id, "Child")
    grandchild = Folder(uuid4(), space.id, child.id, "Grandchild")
    root_document = document(space.id, name="root.md")
    child_document = document(space.id, name="child.md", folder_id=child.id)
    nested_document = document(space.id, name="nested.md", folder_id=grandchild.id)
    repository = MemoryLibraryRepository(
        workspace=space,
        folders=(root, child, grandchild),
        documents=(root_document, child_document, nested_document),
    )
    service = library_service(repository)

    root_page = await service.browse(
        user=member(),
        workspace_id=space.id,
        folder_id=None,
        folder_cursor=None,
        document_cursor=None,
        limit=3,
    )
    child_page = await service.browse(
        user=member(),
        workspace_id=space.id,
        folder_id=child.id,
        folder_cursor=None,
        document_cursor=None,
        limit=3,
    )

    assert [(item.folder.name, item.has_children) for item in root_page.folders] == [("Root", True)]
    assert [item.name for item in root_page.documents] == ["root.md"]
    assert child_page.folder == child
    assert child_page.ancestors == (root,)
    assert [item.folder.name for item in child_page.folders] == ["Grandchild"]
    assert [item.name for item in child_page.documents] == ["child.md"]


@pytest.mark.asyncio
async def test_browse_paginates_name_ties_with_scope_bound_cursors() -> None:
    space = workspace()
    folders = tuple(Folder(uuid4(), space.id, None, "Same") for _ in range(3))
    documents = tuple(document(space.id, name="same.md") for _ in range(3))
    repository = MemoryLibraryRepository(
        workspace=space,
        folders=folders,
        documents=documents,
    )
    service = library_service(repository)
    user = member()

    first = await service.browse(
        user=user,
        workspace_id=space.id,
        folder_id=None,
        folder_cursor=None,
        document_cursor=None,
        limit=2,
    )
    second = await service.browse(
        user=user,
        workspace_id=space.id,
        folder_id=None,
        folder_cursor=first.next_folder_cursor,
        document_cursor=first.next_document_cursor,
        limit=2,
    )

    assert len(first.folders) == len(first.documents) == 2
    assert len(second.folders) == len(second.documents) == 1
    assert {item.folder.id for item in first.folders}.isdisjoint(
        {item.folder.id for item in second.folders}
    )
    assert {item.id for item in first.documents}.isdisjoint({item.id for item in second.documents})
    with pytest.raises(AppError) as failure:
        await service.browse(
            user=user,
            workspace_id=space.id,
            folder_id=None,
            folder_cursor=first.next_document_cursor,
            document_cursor=None,
            limit=2,
        )
    assert failure.value.status_code == 422


@pytest.mark.asyncio
async def test_browse_authorizes_active_workspace_before_rows() -> None:
    repository = MemoryLibraryRepository(workspace=None)
    service = library_service(repository)

    with pytest.raises(AppError) as failure:
        await service.browse(
            user=member(),
            workspace_id=uuid4(),
            folder_id=None,
            folder_cursor="malformed",
            document_cursor=None,
            limit=2,
        )

    assert failure.value.status_code == 404
    assert repository.row_fetches == 0


@pytest.mark.asyncio
async def test_browse_rejects_foreign_folder_and_invalid_cursor_or_limit() -> None:
    space = workspace()
    service = library_service(MemoryLibraryRepository(workspace=space))

    with pytest.raises(AppError) as foreign:
        await service.browse(
            user=member(),
            workspace_id=space.id,
            folder_id=uuid4(),
            folder_cursor=None,
            document_cursor=None,
            limit=2,
        )
    with pytest.raises(AppError) as malformed:
        await service.browse(
            user=member(),
            workspace_id=space.id,
            folder_id=None,
            folder_cursor="malformed",
            document_cursor=None,
            limit=2,
        )
    with pytest.raises(AppError) as oversized_cursor:
        await service.browse(
            user=member(),
            workspace_id=space.id,
            folder_id=None,
            folder_cursor="x" * 4097,
            document_cursor=None,
            limit=2,
        )
    with pytest.raises(AppError) as excessive:
        await service.browse(
            user=member(),
            workspace_id=space.id,
            folder_id=None,
            folder_cursor=None,
            document_cursor=None,
            limit=4,
        )

    assert foreign.value.status_code == 404
    assert malformed.value.status_code == 422
    assert oversized_cursor.value.status_code == 422
    assert excessive.value.status_code == 422


@pytest.mark.asyncio
async def test_document_lookup_rejects_document_from_another_workspace() -> None:
    space = workspace()
    foreign = document(uuid4(), name="foreign.md")
    service = library_service(MemoryLibraryRepository(workspace=space, documents=(foreign,)))

    with pytest.raises(AppError) as failure:
        await service.document(user=member(), workspace_id=space.id, document_id=foreign.id)

    assert failure.value.status_code == 404


@pytest.mark.asyncio
async def test_versions_are_bounded_descending_and_document_scoped() -> None:
    space = workspace()
    first_document = document(space.id, name="first.md", version_count=4)
    second_document = document(space.id, name="second.md", version_count=1)
    service = library_service(
        MemoryLibraryRepository(
            workspace=space,
            documents=(first_document, second_document),
        )
    )
    user = member()

    first = await service.versions(
        user=user,
        workspace_id=space.id,
        document_id=first_document.id,
        cursor=None,
        limit=2,
    )
    second = await service.versions(
        user=user,
        workspace_id=space.id,
        document_id=first_document.id,
        cursor=first.next_cursor,
        limit=2,
    )

    assert [item.number for item in first.items] == [4, 3]
    assert [item.number for item in second.items] == [2, 1]
    assert first.next_cursor is not None
    assert second.next_cursor is None
    with pytest.raises(AppError) as failure:
        await service.versions(
            user=user,
            workspace_id=space.id,
            document_id=second_document.id,
            cursor=first.next_cursor,
            limit=2,
        )
    assert failure.value.status_code == 422


@pytest.mark.asyncio
async def test_ancestor_cycle_and_depth_overflow_fail_closed() -> None:
    space = workspace()
    first = Folder(uuid4(), space.id, None, "First")
    second = Folder(uuid4(), space.id, first.id, "Second")
    first.parent_id = second.id
    cycle_service = library_service(
        MemoryLibraryRepository(workspace=space, folders=(first, second))
    )

    with pytest.raises(AppError) as cycle:
        await cycle_service.browse(
            user=member(),
            workspace_id=space.id,
            folder_id=first.id,
            folder_cursor=None,
            document_cursor=None,
            limit=2,
        )

    root = Folder(uuid4(), space.id, None, "Root")
    child = Folder(uuid4(), space.id, root.id, "Child")
    depth_service = library_service(
        MemoryLibraryRepository(workspace=space, folders=(root, child)),
        max_depth=1,
    )
    with pytest.raises(AppError) as depth:
        await depth_service.browse(
            user=member(),
            workspace_id=space.id,
            folder_id=child.id,
            folder_cursor=None,
            document_cursor=None,
            limit=2,
        )

    assert cycle.value.status_code == 409
    assert depth.value.status_code == 409
