from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.trash_migration_preflight import inspect_trash_migration
from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def _isolated_database_at(revision: str) -> Iterator[IsolatedPublishingDatabase]:
    monkeypatch = pytest.MonkeyPatch()
    try:
        with isolated_publishing_database(monkeypatch) as database:
            command.upgrade(database.config, revision)
            yield database
    finally:
        monkeypatch.undo()


def _seed_workspace(connection: psycopg.Connection[Any]) -> tuple[UUID, UUID]:
    user_id = uuid4()
    workspace_id = uuid4()
    email = f"folder-migration-{user_id}@example.test"
    connection.execute(
        "INSERT INTO users(id,display_name,email,normalized_email,password_hash,role,"
        "is_active,created_at,updated_at) VALUES (%s,'Synthetic owner',%s,%s,'hash',"
        "'member',true,now(),now())",
        (user_id, email, email),
    )
    connection.execute(
        "INSERT INTO workspaces(id,name,kind,created_by,created_at,updated_at) "
        "VALUES (%s,'Synthetic folder migration','company',%s,now(),now())",
        (workspace_id, user_id),
    )
    return user_id, workspace_id


def _insert_active_folder(
    connection: psycopg.Connection[Any],
    workspace_id: UUID,
    name: str,
    *,
    parent_id: UUID | None = None,
) -> UUID:
    folder_id = uuid4()
    connection.execute(
        "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,lifecycle,"
        "lifecycle_generation,created_at,updated_at) "
        "VALUES (%s,%s,%s,%s,1,'active',1,now(),now())",
        (folder_id, workspace_id, parent_id, name),
    )
    return folder_id


def _seed_trash_batch(
    connection: psycopg.Connection[Any], user_id: UUID, workspace_id: UUID
) -> UUID:
    policy_id, batch_id = uuid4(), uuid4()
    connection.execute(
        "INSERT INTO asset_retention_policies"
        "(id,workspace_id,version,days,created_by,created_at) "
        "VALUES (%s,%s,1,30,%s,now())",
        (policy_id, workspace_id, user_id),
    )
    connection.execute(
        "INSERT INTO asset_trash_batches"
        "(id,workspace_id,actor_id,policy_version_id,trashed_at,purge_after,created_at) "
        "VALUES (%s,%s,%s,%s,now(),now()+interval '30 days',now())",
        (batch_id, workspace_id, user_id, policy_id),
    )
    return batch_id


def _database_accepts(statement: str, parameters: tuple[object, ...], *, url: str) -> bool:
    with psycopg.connect(url) as connection:
        try:
            connection.execute(statement, parameters)
        except psycopg.Error:
            connection.rollback()
            return False
        connection.rollback()
        return True


def _index_names(connection: psycopg.Connection[Any]) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname=current_schema() "
            "AND tablename='folders'"
        ).fetchall()
    }


def _configured_head(database: IsolatedPublishingDatabase) -> str:
    head = ScriptDirectory.from_config(database.config).get_current_head()
    assert head is not None
    return head


def test_head_replaces_the_old_folder_unique_constraint_with_active_name_keys() -> None:
    with _isolated_database_at("0036_asset_purge_jobs") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            user_id, workspace_id = _seed_workspace(connection)
            parent_id = _insert_active_folder(connection, workspace_id, "Parent")
            batch_id = _seed_trash_batch(connection, user_id, workspace_id)

        duplicate_root = (
            "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,lifecycle,"
            "lifecycle_generation,created_at,updated_at) "
            "VALUES (%s,%s,NULL,'Root',1,'active',1,now(),now()),"
            "(%s,%s,NULL,'Root',1,'active',1,now(),now())"
        )
        assert _database_accepts(
            duplicate_root,
            (uuid4(), workspace_id, uuid4(), workspace_id),
            url=url,
        )
        active_and_inactive_siblings = (
            "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,lifecycle,"
            "lifecycle_generation,trash_batch_id,trashed_at,purge_after,created_at,updated_at) "
            "VALUES (%s,%s,%s,'Sibling',1,'active',1,NULL,NULL,NULL,now(),now()),"
            "(%s,%s,%s,'Sibling',1,'trashed',2,%s,now(),now()+interval '30 days',now(),now())"
        )
        sibling_parameters = (
            uuid4(),
            workspace_id,
            parent_id,
            uuid4(),
            workspace_id,
            parent_id,
            batch_id,
        )
        assert not _database_accepts(active_and_inactive_siblings, sibling_parameters, url=url)

        command.upgrade(database.config, "head")

        assert not _database_accepts(
            duplicate_root,
            (uuid4(), workspace_id, uuid4(), workspace_id),
            url=url,
        )
        assert _database_accepts(active_and_inactive_siblings, sibling_parameters, url=url)

        active_pair = (
            "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,lifecycle,"
            "lifecycle_generation,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,1,'active',1,now(),now()),"
            "(%s,%s,%s,%s,1,'active',1,now(),now())"
        )
        assert not _database_accepts(
            active_pair,
            (
                uuid4(),
                workspace_id,
                parent_id,
                "\t자료",
                uuid4(),
                workspace_id,
                parent_id,
                "자료\u3000",
            ),
            url=url,
        )
        for left, right in (("Case", "case"), ("한글", "한 글"), ("자료", "\u200b자료")):
            assert _database_accepts(
                active_pair,
                (
                    uuid4(),
                    workspace_id,
                    parent_id,
                    left,
                    uuid4(),
                    workspace_id,
                    parent_id,
                    right,
                ),
                url=url,
            )
        with psycopg.connect(url) as connection:
            _other_user, other_workspace = _seed_workspace(connection)
            other_parent = _insert_active_folder(connection, workspace_id, "Other parent")
        assert _database_accepts(
            active_pair,
            (
                uuid4(),
                workspace_id,
                None,
                "Reusable",
                uuid4(),
                other_workspace,
                None,
                "Reusable",
            ),
            url=url,
        )
        assert _database_accepts(
            active_pair,
            (
                uuid4(),
                workspace_id,
                parent_id,
                "Reusable",
                uuid4(),
                workspace_id,
                other_parent,
                "Reusable",
            ),
            url=url,
        )


def test_repository_uses_the_database_name_key_and_ignores_inactive_folders() -> None:
    with _isolated_database_at("head") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            user_id, workspace_id = _seed_workspace(connection)
            batch_id = _seed_trash_batch(connection, user_id, workspace_id)
            active_id = _insert_active_folder(connection, workspace_id, "\t연구\u3000")
            inactive_id = uuid4()
            connection.execute(
                "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,lifecycle,"
                "lifecycle_generation,trash_batch_id,trashed_at,purge_after,created_at,updated_at) "
                "VALUES (%s,%s,NULL,'Archived',1,'trashed',2,%s,now(),"
                "now()+interval '30 days',now(),now())",
                (inactive_id, workspace_id, batch_id),
            )

        async def lookups() -> tuple[bool, bool]:
            engine = create_async_engine(database.database_url)
            try:
                async with AsyncSession(engine) as session:
                    repository = SqlAlchemyAssetRepository(session)
                    return (
                        await repository.folder_name_exists(workspace_id, None, "연구"),
                        await repository.folder_name_exists(workspace_id, None, "Archived"),
                    )
            finally:
                await engine.dispose()

        assert asyncio.run(lookups()) == (True, False)
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT name FROM folders WHERE id=%s", (active_id,)
            ).fetchone() == ("\t연구\u3000",)


def test_0034_head_0034_round_trip_preserves_assets_and_schema_contract() -> None:
    with _isolated_database_at("0034_asset_metadata_revision") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            _user_id, workspace_id = _seed_workspace(connection)
            folder_id, document_a, document_b, version_id = (uuid4() for _ in range(4))
            connection.execute(
                "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,"
                "created_at,updated_at) VALUES (%s,%s,NULL,'Preserved',7,now(),now())",
                (folder_id, workspace_id),
            )
            connection.execute(
                "INSERT INTO documents(id,workspace_id,folder_id,name,active_version_id,"
                "metadata_revision,created_at,updated_at) VALUES "
                "(%s,%s,%s,'same.txt',%s,8,now(),now()),"
                "(%s,%s,%s,'same.txt',NULL,9,now(),now())",
                (
                    document_a,
                    workspace_id,
                    folder_id,
                    version_id,
                    document_b,
                    workspace_id,
                    folder_id,
                ),
            )
            connection.execute(
                "INSERT INTO asset_versions(id,document_id,number,object_key,sha256,media_type,"
                "size,status,created_at,updated_at) VALUES "
                "(%s,%s,2,%s,%s,'text/plain',17,'ready',now(),now())",
                (version_id, document_a, f"synthetic/{version_id}", "a" * 64),
            )

        command.upgrade(database.config, "head")
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == (_configured_head(database),)
            assert _index_names(connection) >= {
                "ix_folders_active_root_name",
                "ix_folders_active_sibling_name",
            }
            assert connection.execute(
                "SELECT count(*) FROM asset_retention_policies"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT id,name,parent_id,metadata_revision,lifecycle,lifecycle_generation "
                "FROM folders WHERE id=%s",
                (folder_id,),
            ).fetchone() == (folder_id, "Preserved", None, 7, "active", 1)

        command.downgrade(database.config, "0034_asset_metadata_revision")
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0034_asset_metadata_revision",)
            assert connection.execute(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_name='folders' AND constraint_type='UNIQUE'"
            ).fetchall() == [("folders_workspace_id_parent_id_name_key",)]
            assert connection.execute(
                "SELECT id,name,parent_id,metadata_revision FROM folders WHERE id=%s",
                (folder_id,),
            ).fetchone() == (folder_id, "Preserved", None, 7)
            assert connection.execute(
                "SELECT id,name,folder_id,active_version_id,metadata_revision "
                "FROM documents WHERE id IN (%s,%s) ORDER BY id",
                (document_a, document_b),
            ).fetchall() == sorted(
                [
                    (document_a, "same.txt", folder_id, version_id, 8),
                    (document_b, "same.txt", folder_id, None, 9),
                ]
            )
            assert connection.execute(
                "SELECT id,document_id,number,sha256,status FROM asset_versions WHERE id=%s",
                (version_id,),
            ).fetchone() == (version_id, document_a, 2, "a" * 64, "ready")


def test_corrupt_0034_data_blocks_upgrade_without_exposing_or_changing_rows() -> None:
    with _isolated_database_at("0034_asset_metadata_revision") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            _user_id, workspace_id = _seed_workspace(connection)
            first_id, second_id = uuid4(), uuid4()
            connection.execute(
                "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,"
                "created_at,updated_at) VALUES (%s,%s,NULL,'Conflict',1,now(),now()),"
                "(%s,%s,NULL,'Conflict',1,now(),now())",
                (first_id, workspace_id, second_id, workspace_id),
            )
        engine = create_engine(database.database_url)
        try:
            with engine.connect() as connection:
                report = inspect_trash_migration(connection)
        finally:
            engine.dispose()
        assert [(issue.code, issue.entity_ids) for issue in report.issues] == [
            ("folder_root_name_conflict", tuple(sorted((first_id, second_id))))
        ]

        with pytest.raises(RuntimeError, match="^asset_trash_preflight_failed$"):
            command.upgrade(database.config, "head")
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0034_asset_metadata_revision",)
            expected_ids = sorted([(first_id,), (second_id,)])
            assert connection.execute(
                "SELECT id FROM folders WHERE id IN (%s,%s) ORDER BY id",
                (first_id, second_id),
            ).fetchall() == expected_ids
            assert connection.execute(
                "SELECT count(*) FROM information_schema.columns WHERE table_name='folders' "
                "AND column_name='lifecycle'"
            ).fetchone() == (0,)


def test_0037_failure_rolls_back_preceding_revisions_to_0034() -> None:
    with _isolated_database_at("0034_asset_metadata_revision") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            _user_id, workspace_id = _seed_workspace(connection)
            folder_id = uuid4()
            connection.execute(
                "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,"
                "created_at,updated_at) VALUES (%s,%s,NULL,'Canonical',4,now(),now())",
                (folder_id, workspace_id),
            )
            connection.execute(
                "ALTER TABLE folders RENAME CONSTRAINT "
                "folders_workspace_id_parent_id_name_key TO unexpected_folder_unique"
            )

        with pytest.raises(RuntimeError, match="^asset_folder_name_constraint_mismatch$"):
            command.upgrade(database.config, "head")
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0034_asset_metadata_revision",)
            assert connection.execute(
                "SELECT id,name,metadata_revision FROM folders WHERE id=%s", (folder_id,)
            ).fetchone() == (folder_id, "Canonical", 4)
            assert connection.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name IN "
                "('asset_retention_policies','asset_trash_batches','asset_purge_jobs',"
                "'asset_purge_dispatches')"
            ).fetchone() == (0,)


def test_dirty_downgrade_preserves_head_revision_schema_and_data() -> None:
    with _isolated_database_at("head") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            _user_id, workspace_id = _seed_workspace(connection)
            folder_id = uuid4()
            connection.execute(
                "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,lifecycle,"
                "lifecycle_generation,created_at,updated_at) "
                "VALUES (%s,%s,NULL,'Used state',1,'active',2,now(),now())",
                (folder_id, workspace_id),
            )

        with pytest.raises(RuntimeError, match="^asset_folder_name_downgrade_unsafe$"):
            command.downgrade(database.config, "0034_asset_metadata_revision")
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == (_configured_head(database),)
            assert _index_names(connection) >= {
                "ix_folders_active_root_name",
                "ix_folders_active_sibling_name",
            }
            assert connection.execute(
                "SELECT id,lifecycle_generation FROM folders WHERE id=%s", (folder_id,)
            ).fetchone() == (folder_id, 2)
            assert connection.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name IN "
                "('asset_retention_policies','asset_trash_batches','asset_purge_jobs',"
                "'asset_purge_dispatches')"
            ).fetchone() == (4,)


def test_downgrade_refuses_to_restore_an_impossible_old_unique_constraint() -> None:
    with _isolated_database_at("head") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            _user_id, workspace_id = _seed_workspace(connection)
            parent_id = _insert_active_folder(connection, workspace_id, "Parent")
            connection.execute("DROP INDEX ix_folders_active_sibling_name")
            _insert_active_folder(connection, workspace_id, "Duplicate", parent_id=parent_id)
            duplicate_id = _insert_active_folder(
                connection, workspace_id, "Duplicate", parent_id=parent_id
            )

        with pytest.raises(
            RuntimeError, match="^asset_folder_name_unique_restore_unsafe$"
        ):
            command.downgrade(database.config, "0036_asset_purge_jobs")
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == (_configured_head(database),)
            assert connection.execute(
                "SELECT id,name FROM folders WHERE id=%s", (duplicate_id,)
            ).fetchone() == (duplicate_id, "Duplicate")
            assert "ix_folders_active_root_name" in _index_names(connection)
