"""Movement tests operate exclusively on helper-created, validated disposable databases."""

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.platform.assets.domain import Folder
from ai_workshop.platform.assets.models import DocumentRecord, FolderRecord
from ai_workshop.platform.assets.movement import AssetMovementService
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.service import AssetService
from ai_workshop.platform.workspaces.domain import MembershipRole, WorkspaceKind
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.platform.assets.test_asset_originals import seed_original
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[IsolatedPublishingDatabase]:
    with isolated_publishing_database(monkeypatch) as database:
        command.upgrade(database.config, "head")
        yield database


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["document", "folder"])
async def test_move_roundtrip_noop_rollback_and_stale_identity_map(database, kind):
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source = Folder.create(workspace_id=seed.workspace_id, parent_id=None, name="source")
    destination = Folder.create(workspace_id=seed.workspace_id, parent_id=None, name="destination")
    try:
        async with sessions.begin() as session:
            repo = SqlAlchemyAssetRepository(session)
            await repo.add_folder(source)
            await repo.add_folder(destination)
        target = seed.document_id if kind == "document" else source.id
        model = DocumentRecord if kind == "document" else FolderRecord
        location = "folder_id" if kind == "document" else "parent_id"

        async def move(session, destination_id, revision):
            service = AssetMovementService(SqlAlchemyAssetRepository(session), max_depth=64)
            method = service.move_document if kind == "document" else service.move_folder
            return await method(
                user=seed.user,
                workspace_id=seed.workspace_id,
                **{f"{kind}_id": target},
                destination_folder_id=destination_id,
                expected_revision=revision,
            )

        async with sessions() as stale_session:
            stale_record = await stale_session.get(model, target)
            assert stale_record.metadata_revision == 1
            # The record remains in this session's identity map across another commit.
            async with sessions.begin() as session:
                moved, changed = await move(session, destination.id, 1)
                assert changed and moved.metadata_revision == 2
            with pytest.raises(AppError) as error:
                await move(stale_session, None, 1)
            assert error.value.code == "asset_revision_conflict"
            await stale_session.rollback()
        async with sessions.begin() as session:
            moved, changed = await move(session, destination.id, 2)
            assert not changed and moved.metadata_revision == 2
        with pytest.raises(RuntimeError):
            async with sessions.begin() as session:
                await move(session, None, 2)
                raise RuntimeError("rollback")
        async with sessions.begin() as session:
            record = await session.get(model, target)
            assert getattr(record, location) == destination.id and record.metadata_revision == 2
            moved, changed = await move(session, None, 2)
            assert changed and moved.metadata_revision == 3
        async with sessions() as session:
            document = await SqlAlchemyAssetRepository(session).find_document_for_user(
                seed.user.id, seed.document_id
            )
            assert document.active_version_id == seed.ready_version_id
            assert [v.id for v in document.versions] == [
                seed.ready_version_id,
                seed.processing_version_id,
            ]
            assert document.versions[0].object_key == seed.object_key
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["revision", "folder_revision", "cycle", "duplicate", "depth"])
async def test_serialized_races_have_only_one_winner(database, race, tmp_path):
    from ai_workshop.infrastructure.object_store.local import LocalObjectStore

    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    a = Folder.create(workspace_id=seed.workspace_id, parent_id=None, name="a")
    b = Folder.create(workspace_id=seed.workspace_id, parent_id=None, name="b")
    child = Folder.create(workspace_id=seed.workspace_id, parent_id=a.id, name="child")
    try:
        async with sessions.begin() as session:
            repo = SqlAlchemyAssetRepository(session)
            for folder in (a, b, child):
                await repo.add_folder(folder)

        async def operation(index):
            try:
                async with sessions.begin() as session:
                    repo = SqlAlchemyAssetRepository(session)
                    movement = AssetMovementService(repo, max_depth=3 if race == "depth" else 64)
                    if race == "revision":
                        await movement.move_document(
                            user=seed.user,
                            workspace_id=seed.workspace_id,
                            document_id=seed.document_id,
                            destination_folder_id=(a.id, b.id)[index],
                            expected_revision=1,
                        )
                    elif race == "folder_revision":
                        await movement.move_folder(
                            user=seed.user,
                            workspace_id=seed.workspace_id,
                            folder_id=child.id,
                            destination_folder_id=(None, b.id)[index],
                            expected_revision=1,
                        )
                    elif race == "cycle":
                        await movement.move_folder(
                            user=seed.user,
                            workspace_id=seed.workspace_id,
                            folder_id=(a.id, b.id)[index],
                            destination_folder_id=(b.id, a.id)[index],
                            expected_revision=1,
                        )
                    elif index == 0:
                        await movement.move_folder(
                            user=seed.user,
                            workspace_id=seed.workspace_id,
                            folder_id=a.id,
                            destination_folder_id=b.id,
                            expected_revision=1,
                        )
                    else:
                        service = AssetService(
                            repo,
                            LocalObjectStore(tmp_path),
                            max_upload_bytes=1024,
                            max_depth=3 if race == "depth" else 64,
                        )
                        await service.create_folder(
                            user=seed.user,
                            workspace_id=seed.workspace_id,
                            parent_id=child.id if race == "depth" else b.id,
                            name="new" if race == "depth" else " a ",
                        )
                return "success"
            except AppError as error:
                return error.code

        results = await asyncio.wait_for(asyncio.gather(operation(0), operation(1)), 15)
        expected = {
            "revision": "asset_revision_conflict",
            "folder_revision": "asset_revision_conflict",
            "cycle": "folder_cycle",
            "duplicate": "folder_exists",
            "depth": "folder_depth_exceeded",
        }[race]
        assert sorted(results) == sorted(["success", expected])
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_revoked_writer_waiting_on_workspace_lock_is_denied(database):
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == seed.workspace_id)
                .values(kind=WorkspaceKind.COMPANY, expires_at=None)
            )
            await session.execute(
                update(WorkspaceMembershipRecord)
                .where(WorkspaceMembershipRecord.workspace_id == seed.workspace_id)
                .values(can_read=True, can_write=True)
            )
        async with sessions() as revoker:
            await revoker.scalar(
                select(WorkspaceRecord.id)
                .where(WorkspaceRecord.id == seed.workspace_id)
                .with_for_update()
            )
            started = asyncio.Event()

            async def move():
                async with sessions.begin() as session:
                    started.set()
                    with pytest.raises(AppError) as error:
                        await AssetMovementService(
                            SqlAlchemyAssetRepository(session), max_depth=64
                        ).move_document(
                            user=seed.user,
                            workspace_id=seed.workspace_id,
                            document_id=seed.document_id,
                            destination_folder_id=None,
                            expected_revision=999,
                        )
                    assert error.value.status_code == 404

            task = asyncio.create_task(move())
            await started.wait()
            # Confirm a real PostgreSQL lock wait rather than relying on task timing.
            for _ in range(100):
                from sqlalchemy import text

                waiting = await revoker.scalar(
                    text(
                        "SELECT count(*) FROM pg_locks WHERE NOT granted AND pid<>pg_backend_pid()"
                    )
                )
                if waiting:
                    break
                await asyncio.sleep(0.02)
            assert waiting
            await revoker.execute(
                update(WorkspaceMembershipRecord)
                .where(WorkspaceMembershipRecord.workspace_id == seed.workspace_id)
                .values(can_write=False)
            )
            await revoker.commit()
            await asyncio.wait_for(task, 10)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_wrong_workspace_personal_nonowner_and_stale_version_save(database):
    seed = await seed_original(database.database_url)
    other = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    folder = Folder.create(workspace_id=seed.workspace_id, parent_id=None, name="destination")
    try:
        async with sessions.begin() as session:
            repo = SqlAlchemyAssetRepository(session)
            await repo.add_folder(folder)
            stale = await repo.find_document_for_user(seed.user.id, seed.document_id)
        async with sessions.begin() as session:
            service = AssetMovementService(SqlAlchemyAssetRepository(session), max_depth=64)
            with pytest.raises(AppError) as error:
                await service.move_document(
                    user=seed.user,
                    workspace_id=seed.workspace_id,
                    document_id=other.document_id,
                    destination_folder_id=None,
                    expected_revision=999,
                )
            assert error.value.status_code == 404
            await service.move_document(
                user=seed.user,
                workspace_id=seed.workspace_id,
                document_id=seed.document_id,
                destination_folder_id=folder.id,
                expected_revision=1,
            )
        async with sessions.begin() as session:
            version = stale.new_version(
                object_key=f"synthetic/{uuid4()}.txt",
                sha256="2" * 64,
                media_type="text/plain",
                size=1,
            )
            await SqlAlchemyAssetRepository(session).save_version(stale, version)
        async with sessions.begin() as session:
            current = await session.get(DocumentRecord, seed.document_id)
            assert current.folder_id == folder.id and current.metadata_revision == 2
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == seed.workspace_id)
                .values(kind=WorkspaceKind.PERSONAL, expires_at=None)
            )
            session.add(
                WorkspaceMembershipRecord(
                    workspace_id=seed.workspace_id,
                    user_id=seed.foreign_user_id,
                    role=MembershipRole.OWNER,
                )
            )
        async with sessions.begin() as session:
            with pytest.raises(AppError) as error:
                await AssetMovementService(
                    SqlAlchemyAssetRepository(session), max_depth=64
                ).move_document(
                    user=replace(seed.user, id=seed.foreign_user_id),
                    workspace_id=seed.workspace_id,
                    document_id=seed.document_id,
                    destination_folder_id=None,
                    expected_revision=999,
                )
            assert error.value.status_code == 404
    finally:
        await engine.dispose()


def test_revision_migration_backfill_constraint_and_downgrade(monkeypatch):
    with isolated_publishing_database(monkeypatch) as database:
        command.upgrade(database.config, "0033_workspace_permissions")
        url = database.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        user, workspace, folder, document = (uuid4() for _ in range(4))
        with psycopg.connect(url) as connection:
            connection.execute(
                "INSERT INTO users(id,display_name,email,normalized_email,password_hash,role,"
                "is_active,created_at,updated_at) VALUES (%s,'Synthetic','m@example.test',"
                "'m@example.test','hash','member',true,now(),now())",
                (user,),
            )
            connection.execute(
                "INSERT INTO workspaces(id,name,kind,created_by,created_at,updated_at) "
                "VALUES (%s,'Synthetic','company',%s,now(),now())",
                (workspace, user),
            )
            connection.execute(
                "INSERT INTO folders(id,workspace_id,name,created_at,updated_at) "
                "VALUES (%s,%s,'folder',now(),now())",
                (folder, workspace),
            )
            connection.execute(
                "INSERT INTO documents(id,workspace_id,name,created_at,updated_at) "
                "VALUES (%s,%s,'doc',now(),now())",
                (document, workspace),
            )
        command.upgrade(database.config, "head")
        with psycopg.connect(url) as connection:
            for table in ("folders", "documents"):
                from psycopg import sql

                assert connection.execute(
                    sql.SQL("SELECT metadata_revision FROM {}").format(sql.Identifier(table))
                ).fetchone() == (1,)
                with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                    connection.execute(
                        sql.SQL("UPDATE {} SET metadata_revision=0").format(sql.Identifier(table))
                    )
        command.downgrade(database.config, "0033_workspace_permissions")
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name IN ('folders','documents') AND column_name='metadata_revision'"
            ).fetchone() == (0,)
            assert connection.execute("SELECT id FROM documents").fetchone() == (document,)


@pytest.mark.parametrize("attach_to_descendant", [False, True])
@pytest.mark.parametrize("noop", [False, True])
async def test_foreign_child_in_affected_subtree_blocks_move_without_changing_rows(
    database,
    attach_to_descendant,
    noop,
):
    seed = await seed_original(database.database_url)
    foreign = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source = Folder.create(workspace_id=seed.workspace_id, parent_id=None, name="source")
    child = Folder.create(workspace_id=seed.workspace_id, parent_id=source.id, name="child")
    destination = Folder.create(workspace_id=seed.workspace_id, parent_id=None, name="destination")
    corrupt = Folder.create(
        workspace_id=foreign.workspace_id,
        parent_id=child.id if attach_to_descendant else source.id,
        name="private",
    )
    try:
        async with sessions.begin() as session:
            repo = SqlAlchemyAssetRepository(session)
            for folder in (source, child, destination, corrupt):
                await repo.add_folder(folder)
        async with sessions() as session:
            before = (
                await session.execute(
                    select(
                        FolderRecord.id,
                        FolderRecord.workspace_id,
                        FolderRecord.parent_id,
                        FolderRecord.metadata_revision,
                    ).order_by(FolderRecord.id)
                )
            ).all()
        async with sessions.begin() as session:
            with pytest.raises(AppError) as error:
                await AssetMovementService(
                    SqlAlchemyAssetRepository(session), max_depth=64
                ).move_folder(
                    user=seed.user,
                    workspace_id=seed.workspace_id,
                    folder_id=source.id,
                    destination_folder_id=None if noop else destination.id,
                    expected_revision=1,
                )
            assert error.value.code == "folder_hierarchy_invalid"
            assert "private" not in str(error.value)
        async with sessions() as session:
            after = (
                await session.execute(
                    select(
                        FolderRecord.id,
                        FolderRecord.workspace_id,
                        FolderRecord.parent_id,
                        FolderRecord.metadata_revision,
                    ).order_by(FolderRecord.id)
                )
            ).all()
            assert after == before
    finally:
        await engine.dispose()


async def test_root_null_stripped_name_collision_preserves_source(database):
    seed = await seed_original(database.database_url)
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    parent = Folder.create(workspace_id=seed.workspace_id, parent_id=None, name="parent")
    root = Folder.create(workspace_id=seed.workspace_id, parent_id=None, name="same")
    root.name = " same "  # Synthetic legacy row, bypassing normalization intentionally.
    source = Folder.create(workspace_id=seed.workspace_id, parent_id=parent.id, name="same")
    try:
        async with sessions.begin() as session:
            repo = SqlAlchemyAssetRepository(session)
            for folder in (parent, root, source):
                await repo.add_folder(folder)
        async with sessions.begin() as session:
            with pytest.raises(AppError) as error:
                await AssetMovementService(
                    SqlAlchemyAssetRepository(session), max_depth=64
                ).move_folder(
                    user=seed.user,
                    workspace_id=seed.workspace_id,
                    folder_id=source.id,
                    destination_folder_id=None,
                    expected_revision=1,
                )
            assert error.value.code == "folder_exists"
        async with sessions() as session:
            record = await session.get(FolderRecord, source.id)
            assert (record.parent_id, record.name, record.metadata_revision) == (
                parent.id,
                "same",
                1,
            )
    finally:
        await engine.dispose()
