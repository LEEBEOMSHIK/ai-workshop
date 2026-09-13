import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.library_repository import (
    NameCursor,
    SqlAlchemyLibraryRepository,
    VersionCursor,
)
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord, FolderRecord
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.service import AssetService
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.domain import MembershipRole, WorkspaceKind
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@pytest.fixture
def isolated_asset_database(
    monkeypatch: pytest.MonkeyPatch,
) -> IsolatedPublishingDatabase:
    with isolated_publishing_database(monkeypatch) as database:
        command.upgrade(database.config, "head")
        yield database


@dataclass(frozen=True, slots=True)
class LibrarySeed:
    user: User
    workspace_id: UUID
    expired_workspace_id: UUID
    foreign_workspace_id: UUID
    root_folder_ids: tuple[UUID, UUID]
    child_folder_id: UUID
    root_document_ids: tuple[UUID, UUID]
    child_document_id: UUID
    active_version_id: UUID
    latest_version_id: UUID


async def _seed_library(database_url: str) -> LibrarySeed:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid4()
    foreign_user_id = uuid4()
    workspace_id = uuid4()
    expired_workspace_id = uuid4()
    foreign_workspace_id = uuid4()
    root_folder_ids = tuple(sorted((uuid4(), uuid4())))
    child_folder_id = uuid4()
    root_document_ids = tuple(sorted((uuid4(), uuid4())))
    child_document_id = uuid4()
    active_version_id = uuid4()
    latest_version_id = uuid4()
    try:
        async with sessions.begin() as session:
            session.add_all(
                [
                    UserRecord(
                        id=user_id,
                        display_name="Synthetic library member",
                        email=f"library-{user_id}@example.test",
                        normalized_email=f"library-{user_id}@example.test",
                        password_hash="synthetic-password-hash",
                        role=UserRole.MEMBER,
                        is_active=True,
                    ),
                    UserRecord(
                        id=foreign_user_id,
                        display_name="Synthetic foreign member",
                        email=f"library-{foreign_user_id}@example.test",
                        normalized_email=f"library-{foreign_user_id}@example.test",
                        password_hash="synthetic-password-hash",
                        role=UserRole.MEMBER,
                        is_active=True,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    WorkspaceRecord(
                        id=workspace_id,
                        name="Synthetic active library",
                        kind=WorkspaceKind.TEAM,
                        created_by=user_id,
                        expires_at=None,
                    ),
                    WorkspaceRecord(
                        id=expired_workspace_id,
                        name="Synthetic expired library",
                        kind=WorkspaceKind.TEMPORARY,
                        created_by=user_id,
                        expires_at=datetime.now(UTC) - timedelta(minutes=1),
                    ),
                    WorkspaceRecord(
                        id=foreign_workspace_id,
                        name="Synthetic foreign library",
                        kind=WorkspaceKind.TEAM,
                        created_by=foreign_user_id,
                        expires_at=None,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    WorkspaceMembershipRecord(
                        workspace_id=workspace_id,
                        user_id=user_id,
                        role=MembershipRole.MEMBER,
                    ),
                    WorkspaceMembershipRecord(
                        workspace_id=expired_workspace_id,
                        user_id=user_id,
                        role=MembershipRole.MEMBER,
                    ),
                    WorkspaceMembershipRecord(
                        workspace_id=foreign_workspace_id,
                        user_id=foreign_user_id,
                        role=MembershipRole.MEMBER,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    FolderRecord(
                        id=root_folder_ids[0],
                        workspace_id=workspace_id,
                        parent_id=None,
                        name="First root",
                    ),
                    FolderRecord(
                        id=root_folder_ids[1],
                        workspace_id=workspace_id,
                        parent_id=None,
                        name="Second root",
                    ),
                    FolderRecord(
                        id=child_folder_id,
                        workspace_id=workspace_id,
                        parent_id=root_folder_ids[0],
                        name="Child",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    DocumentRecord(
                        id=root_document_ids[0],
                        workspace_id=workspace_id,
                        folder_id=None,
                        name="same.md",
                        active_version_id=active_version_id,
                    ),
                    DocumentRecord(
                        id=root_document_ids[1],
                        workspace_id=workspace_id,
                        folder_id=None,
                        name="same.md",
                        active_version_id=None,
                    ),
                    DocumentRecord(
                        id=child_document_id,
                        workspace_id=workspace_id,
                        folder_id=child_folder_id,
                        name="child.md",
                        active_version_id=None,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    AssetVersionRecord(
                        id=active_version_id,
                        document_id=root_document_ids[0],
                        number=1,
                        object_key=f"synthetic/{root_document_ids[0]}/v1.md",
                        sha256="1" * 64,
                        media_type="text/markdown",
                        size=1,
                        status=VersionStatus.READY,
                    ),
                    AssetVersionRecord(
                        id=latest_version_id,
                        document_id=root_document_ids[0],
                        number=2,
                        object_key=f"synthetic/{root_document_ids[0]}/v2.md",
                        sha256="2" * 64,
                        media_type="text/markdown",
                        size=2,
                        status=VersionStatus.PROCESSING,
                    ),
                    AssetVersionRecord(
                        id=uuid4(),
                        document_id=root_document_ids[1],
                        number=1,
                        object_key=f"synthetic/{root_document_ids[1]}/v1.md",
                        sha256="3" * 64,
                        media_type="text/markdown",
                        size=3,
                        status=VersionStatus.STORED,
                    ),
                    AssetVersionRecord(
                        id=uuid4(),
                        document_id=child_document_id,
                        number=1,
                        object_key=f"synthetic/{child_document_id}/v1.md",
                        sha256="4" * 64,
                        media_type="text/markdown",
                        size=4,
                        status=VersionStatus.STORED,
                    ),
                ]
            )
    finally:
        await engine.dispose()
    return LibrarySeed(
        user=User(
            id=user_id,
            display_name="Synthetic library member",
            email=f"library-{user_id}@example.test",
            normalized_email=f"library-{user_id}@example.test",
            password_hash="synthetic-password-hash",
            role=UserRole.MEMBER,
        ),
        workspace_id=workspace_id,
        expired_workspace_id=expired_workspace_id,
        foreign_workspace_id=foreign_workspace_id,
        root_folder_ids=root_folder_ids,
        child_folder_id=child_folder_id,
        root_document_ids=root_document_ids,
        child_document_id=child_document_id,
        active_version_id=active_version_id,
        latest_version_id=latest_version_id,
    )


@pytest.mark.asyncio
async def test_library_repository_scopes_and_bounds_rows(
    isolated_asset_database: IsolatedPublishingDatabase,
) -> None:
    seed = await _seed_library(isolated_asset_database.database_url)
    engine = create_async_engine(isolated_asset_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            repository = SqlAlchemyLibraryRepository(session)

            workspace = await repository.workspace_for_user(seed.user.id, seed.workspace_id)
            expired = await repository.workspace_for_user(
                seed.user.id, seed.expired_workspace_id
            )
            foreign = await repository.workspace_for_user(
                seed.user.id, seed.foreign_workspace_id
            )
            first_folders = await repository.child_folders(
                seed.workspace_id, None, None, 1
            )
            second_folders = await repository.child_folders(
                seed.workspace_id,
                None,
                NameCursor(first_folders[0][0].name, first_folders[0][0].id),
                2,
            )
            first_documents = await repository.child_documents(
                seed.workspace_id, None, None, 1
            )
            second_documents = await repository.child_documents(
                seed.workspace_id,
                None,
                NameCursor(first_documents[0].name, first_documents[0].id),
                2,
            )
            exact = await repository.document_for_workspace(
                seed.workspace_id, seed.root_document_ids[0]
            )
            unrelated = await repository.document_for_workspace(
                seed.foreign_workspace_id, seed.root_document_ids[0]
            )
            first_versions = await repository.document_versions(
                seed.root_document_ids[0], None, 1
            )
            second_versions = await repository.document_versions(
                seed.root_document_ids[0],
                VersionCursor(first_versions[0].number, first_versions[0].id),
                2,
            )

        assert workspace is not None and workspace.id == seed.workspace_id
        assert expired is None
        assert foreign is None
        assert first_folders[0][0].id == seed.root_folder_ids[0]
        assert first_folders[0][1] is True
        assert [item[0].id for item in second_folders] == [seed.root_folder_ids[1]]
        assert first_documents[0].id == seed.root_document_ids[0]
        assert [item.id for item in second_documents] == [seed.root_document_ids[1]]
        assert exact is not None
        assert exact.folder_id is None
        assert exact.active_version_id == seed.active_version_id
        assert exact.versions[0].id == seed.latest_version_id
        assert exact.versions[0].status is VersionStatus.PROCESSING
        assert unrelated is None
        assert [item.number for item in first_versions] == [2]
        assert [item.number for item in second_versions] == [1]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_root_folder_creation_serializes_duplicate_check(
    isolated_asset_database: IsolatedPublishingDatabase,
    tmp_path,
) -> None:
    seed = await _seed_library(isolated_asset_database.database_url)
    engine = create_async_engine(isolated_asset_database.database_url, pool_size=2)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def create_same_folder() -> object:
        async with sessions.begin() as session:
            service = AssetService(
                SqlAlchemyAssetRepository(session),
                LocalObjectStore(tmp_path),
                max_upload_bytes=1024,
                max_depth=64,
            )
            return await service.create_folder(
                user=seed.user,
                workspace_id=seed.workspace_id,
                parent_id=None,
                name=" Concurrent ",
            )

    try:
        results = await asyncio.gather(
            create_same_folder(),
            create_same_folder(),
            return_exceptions=True,
        )
        async with sessions() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(FolderRecord)
                .where(
                    FolderRecord.workspace_id == seed.workspace_id,
                    FolderRecord.parent_id.is_(None),
                    FolderRecord.name == "Concurrent",
                )
            )

        errors = [item for item in results if isinstance(item, AppError)]
        assert len(errors) == 1
        assert errors[0].status_code == 409
        assert count == 1
    finally:
        await engine.dispose()
