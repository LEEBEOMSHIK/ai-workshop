"""Personal ownership remains mandatory even with a foreign owner membership."""

import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.platform.assets.library import LibraryService
from ai_workshop.platform.assets.library_repository import SqlAlchemyLibraryRepository
from ai_workshop.platform.assets.originals import OriginalService, SqlAlchemyOriginalRepository
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.service import AssetService
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository
from ai_workshop.platform.jobs.service import JobService
from ai_workshop.platform.workspaces.domain import MembershipRole, WorkspaceKind
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.platform.workspaces.repository import SqlAlchemyWorkspaceRepository
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.platform.assets.test_asset_originals import NeverPdfRenderer, seed_original
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[IsolatedPublishingDatabase]:
    with isolated_publishing_database(monkeypatch) as isolated:
        command.upgrade(isolated.config, "head")
        yield isolated


async def _content(value: bytes = b"synthetic unauthorized upload") -> AsyncIterator[bytes]:
    yield value


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.MEMBER, UserRole.OWNER])
async def test_foreign_membership_cannot_expose_personal_files(
    database: IsolatedPublishingDatabase, tmp_path: Path, role: UserRole
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    foreign = replace(seed.user, id=seed.foreign_user_id, role=role)
    store_root = Path("\\\\?\\" + str(tmp_path)) if os.name == "nt" else tmp_path
    store = LocalObjectStore(store_root)
    try:
        await store.put(seed.object_key, _content(seed.content))
        async with sessions.begin() as session:
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == seed.workspace_id)
                .values(kind=WorkspaceKind.PERSONAL, expires_at=None)
            )
            await session.execute(
                update(UserRecord).where(UserRecord.id == foreign.id).values(role=role)
            )
            session.add(
                WorkspaceMembershipRecord(
                    workspace_id=seed.workspace_id, user_id=foreign.id, role=MembershipRole.OWNER
                )
            )
        async with sessions() as session:
            assets = SqlAlchemyAssetRepository(session)
            workspaces = SqlAlchemyWorkspaceRepository(session)
            library = LibraryService(
                SqlAlchemyLibraryRepository(session),
                secret_key="synthetic-isolation-key",
                default_page_size=10,
                max_page_size=20,
                max_depth=10,
                cursor_max_chars=4096,
            )
            originals = SqlAlchemyOriginalRepository(session)
            original_service = OriginalService(
                originals,
                store,
                NeverPdfRenderer(),
                original_max_bytes=1024,
                text_preview_max_bytes=1024,
            )
            service = AssetService(assets, store, max_upload_bytes=1024)
            jobs = SqlAlchemyJobRepository(session)
            job = await jobs.add(
                Job.create(
                    user_id=seed.user.id,
                    workspace_id=seed.workspace_id,
                    asset_version_id=seed.ready_version_id,
                    type=JobType.VERIFY_ASSET,
                    idempotency_key="synthetic-isolation-job",
                )
            )
            assert await jobs.find_for_user(seed.user.id, job.id)
            # Positive controls prove the fixture contains accessible owner resources.
            assert await assets.has_workspace_access(seed.user.id, seed.workspace_id)
            assert await assets.find_document_for_user(seed.user.id, seed.document_id)
            assert await originals.resolve(
                user_id=seed.user.id, document_id=seed.document_id, version_id=seed.ready_version_id
            )
            preview = await original_service.preview(
                user=seed.user, document_id=seed.document_id, version_id=seed.ready_version_id
            )
            assert preview.text == seed.content.decode("utf-8-sig")
            download = await original_service.content(
                user=seed.user, document_id=seed.document_id, version_id=seed.ready_version_id
            )
            assert download.content == seed.content
            folder = await service.create_folder(
                user=seed.user,
                workspace_id=seed.workspace_id,
                parent_id=None,
                name="Synthetic owner folder",
            )
            leaks: list[str] = []
            if await jobs.find_for_user(foreign.id, job.id):
                leaks.append("job metadata")
            if await workspaces.list_for_user(foreign.id):
                leaks.append("workspace list")
            if await assets.list_documents(foreign.id, seed.workspace_id):
                leaks.append("document list")
            if await assets.list_folders(foreign.id, seed.workspace_id):
                leaks.append("folder list")
            if await assets.find_document_for_user(foreign.id, seed.document_id):
                leaks.append("exact document")
            if await originals.resolve(
                user_id=foreign.id, document_id=seed.document_id, version_id=seed.ready_version_id
            ):
                leaks.append("original resolution")
            operations = {
                "job request": lambda: JobService(jobs).get_for_user(
                    user_id=foreign.id, job_id=job.id
                ),
                "library root": lambda: library.browse(
                    user=foreign,
                    workspace_id=seed.workspace_id,
                    folder_id=None,
                    folder_cursor=None,
                    document_cursor=None,
                    limit=None,
                ),
                "library folder": lambda: library.browse(
                    user=foreign,
                    workspace_id=seed.workspace_id,
                    folder_id=folder.id,
                    folder_cursor=None,
                    document_cursor=None,
                    limit=None,
                ),
                "library document": lambda: library.document(
                    user=foreign, workspace_id=seed.workspace_id, document_id=seed.document_id
                ),
                "library versions": lambda: library.versions(
                    user=foreign,
                    workspace_id=seed.workspace_id,
                    document_id=seed.document_id,
                    cursor=None,
                    limit=None,
                ),
                "asset versions": lambda: service.list_versions(
                    user=foreign, document_id=seed.document_id
                ),
                "preview": lambda: original_service.preview(
                    user=foreign, document_id=seed.document_id, version_id=seed.ready_version_id
                ),
                "PDF page": lambda: original_service.pdf_page(
                    user=foreign,
                    document_id=seed.document_id,
                    version_id=seed.ready_version_id,
                    page_number=1,
                ),
                "download": lambda: original_service.content(
                    user=foreign, document_id=seed.document_id, version_id=seed.ready_version_id
                ),
                "new folder": lambda: service.create_folder(
                    user=foreign,
                    workspace_id=seed.workspace_id,
                    parent_id=None,
                    name="Forbidden folder",
                ),
                "upload": lambda: service.upload(
                    user=foreign,
                    workspace_id=seed.workspace_id,
                    folder_id=None,
                    filename="forbidden.txt",
                    media_type="text/plain",
                    content=_content(),
                ),
                "new version": lambda: service.upload_version(
                    user=foreign,
                    document_id=seed.document_id,
                    filename="forbidden.txt",
                    media_type="text/plain",
                    content=_content(),
                ),
            }
            for name, operation in operations.items():
                try:
                    await operation()
                except AppError as error:
                    if error.status_code != 404:
                        leaks.append(f"{name}: {error.status_code}")
                else:
                    leaks.append(name)
            # Existing team/company membership still permits reading and writing.
            for kind in (WorkspaceKind.TEAM, WorkspaceKind.COMPANY):
                await session.execute(
                    update(WorkspaceRecord)
                    .where(WorkspaceRecord.id == seed.workspace_id)
                    .values(kind=kind)
                )
                assert await assets.has_workspace_access(foreign.id, seed.workspace_id)
                assert await jobs.find_for_user(foreign.id, job.id)
                assert await originals.resolve(
                    user_id=foreign.id,
                    document_id=seed.document_id,
                    version_id=seed.ready_version_id,
                )
                assert await library.document(
                    user=foreign, workspace_id=seed.workspace_id, document_id=seed.document_id
                )
                assert await service.create_folder(
                    user=foreign,
                    workspace_id=seed.workspace_id,
                    parent_id=None,
                    name=f"Allowed {kind}",
                )
            assert leaks == [], f"personal access escaped authorization: {leaks}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_personal_creation_existence_uses_creator_not_membership(
    database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == seed.workspace_id)
                .values(kind=WorkspaceKind.PERSONAL, expires_at=None)
            )
            await session.execute(
                delete(WorkspaceMembershipRecord).where(
                    WorkspaceMembershipRecord.workspace_id == seed.workspace_id
                )
            )
            session.add(
                WorkspaceMembershipRecord(
                    workspace_id=seed.workspace_id,
                    user_id=seed.foreign_user_id,
                    role=MembershipRole.OWNER,
                )
            )
        async with sessions() as session:
            repository = SqlAlchemyWorkspaceRepository(session)
            actual = (
                await repository.has_personal(seed.user.id),
                await repository.has_personal(seed.foreign_user_id),
            )
            assert actual == (True, False)
            assert await repository.list_for_user(seed.user.id) == []
            assert not await SqlAlchemyAssetRepository(session).has_workspace_access(
                seed.user.id, seed.workspace_id
            )
    finally:
        await engine.dispose()
