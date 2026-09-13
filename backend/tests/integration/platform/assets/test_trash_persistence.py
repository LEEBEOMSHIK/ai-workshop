from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, inspect

from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@dataclass(frozen=True, slots=True)
class IdentitySeed:
    user_id: UUID
    removable_actor_id: UUID
    workspace_ids: tuple[UUID, UUID]


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _seed_identity(connection: psycopg.Connection[Any]) -> IdentitySeed:
    user_id = uuid4()
    removable_actor_id = uuid4()
    for user, label in ((user_id, "owner"), (removable_actor_id, "actor")):
        email = f"trash-{label}-{user}@example.test"
        connection.execute(
            "INSERT INTO users(id,display_name,email,normalized_email,password_hash,role,"
            "is_active,created_at,updated_at) VALUES (%s,%s,%s,%s,'hash','member',true,"
            "now(),now())",
            (user, f"Synthetic {label}", email, email),
        )
    workspace_ids = (uuid4(), uuid4())
    for index, workspace_id in enumerate(workspace_ids):
        connection.execute(
            "INSERT INTO workspaces(id,name,kind,created_by,created_at,updated_at) "
            "VALUES (%s,%s,'company',%s,now(),now())",
            (workspace_id, f"Synthetic trash {index}", user_id),
        )
    return IdentitySeed(user_id, removable_actor_id, workspace_ids)


@contextmanager
def _isolated_database_at(
    revision: str,
) -> Iterator[IsolatedPublishingDatabase]:
    monkeypatch = pytest.MonkeyPatch()
    try:
        with isolated_publishing_database(monkeypatch) as database:
            command.upgrade(database.config, revision)
            yield database
    finally:
        monkeypatch.undo()


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[IsolatedPublishingDatabase]:
    with _isolated_database_at("0035_asset_trash_state") as database:
        yield database


def _assert_rejected(
    connection: psycopg.Connection[Any],
    statement: str,
    parameters: tuple[object, ...],
) -> None:
    with pytest.raises(psycopg.Error), connection.transaction():
        connection.execute(statement, parameters)


def test_upgrade_adds_storage_contract_and_preserves_0034_rows() -> None:
    with _isolated_database_at("0034_asset_metadata_revision") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            seed = _seed_identity(connection)
            workspace_id = seed.workspace_ids[0]
            parent_id, child_id, document_id, version_id = (uuid4() for _ in range(4))
            connection.execute(
                "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,"
                "created_at,updated_at) VALUES (%s,%s,NULL,'Parent',7,now(),now()),"
                "(%s,%s,%s,'Child',8,now(),now())",
                (parent_id, workspace_id, child_id, workspace_id, parent_id),
            )
            connection.execute(
                "INSERT INTO documents(id,workspace_id,folder_id,name,active_version_id,"
                "metadata_revision,created_at,updated_at) VALUES "
                "(%s,%s,%s,'preserved.txt',%s,9,now(),now())",
                (document_id, workspace_id, child_id, version_id),
            )
            connection.execute(
                "INSERT INTO asset_versions(id,document_id,number,object_key,sha256,media_type,"
                "size,status,created_at,updated_at) VALUES "
                "(%s,%s,3,%s,%s,'text/plain',17,'ready',now(),now())",
                (version_id, document_id, f"synthetic/{version_id}", "a" * 64),
            )

        command.upgrade(database.config, "0035_asset_trash_state")

        engine = create_engine(database.database_url)
        try:
            schema = inspect(engine)
            assert {column["name"] for column in schema.get_columns("folders")} >= {
                "lifecycle",
                "lifecycle_generation",
                "trash_batch_id",
                "trashed_at",
                "purge_after",
            }
            assert schema.has_table("asset_retention_policies")
            assert schema.has_table("asset_trash_batches")
        finally:
            engine.dispose()

        with psycopg.connect(url) as connection:
            folder_rows = connection.execute(
                "SELECT id,name,parent_id,metadata_revision,lifecycle,lifecycle_generation,"
                "trash_batch_id,trashed_at,purge_after FROM folders ORDER BY name"
            ).fetchall()
            document_row = connection.execute(
                "SELECT id,name,folder_id,active_version_id,metadata_revision,lifecycle,"
                "lifecycle_generation,trash_batch_id,trashed_at,purge_after "
                "FROM documents WHERE id=%s",
                (document_id,),
            ).fetchone()
            version_row = connection.execute(
                "SELECT id,document_id,number,sha256,status FROM asset_versions WHERE id=%s",
                (version_id,),
            ).fetchone()

        assert folder_rows == [
            (child_id, "Child", parent_id, 8, "active", 1, None, None, None),
            (parent_id, "Parent", None, 7, "active", 1, None, None, None),
        ]
        assert document_row == (
            document_id,
            "preserved.txt",
            child_id,
            version_id,
            9,
            "active",
            1,
            None,
            None,
            None,
        )
        assert version_row == (version_id, document_id, 3, "a" * 64, "ready")


def test_database_rejects_invalid_policy_batch_and_lifecycle_state(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_identity(connection)
        workspace_a, workspace_b = seed.workspace_ids
        policy_a, policy_b, batch_a = uuid4(), uuid4(), uuid4()
        connection.execute(
            "INSERT INTO asset_retention_policies"
            "(id,workspace_id,version,days,created_by,created_at) "
            "VALUES (%s,%s,1,30,%s,now()),(%s,%s,1,60,%s,now())",
            (
                policy_a,
                workspace_a,
                seed.removable_actor_id,
                policy_b,
                workspace_b,
                seed.removable_actor_id,
            ),
        )
        connection.execute(
            "INSERT INTO asset_trash_batches"
            "(id,workspace_id,actor_id,policy_version_id,trashed_at,purge_after,created_at) "
            "VALUES (%s,%s,%s,%s,now(),now()+interval '30 days',now())",
            (batch_a, workspace_a, seed.removable_actor_id, policy_a),
        )

        _assert_rejected(
            connection,
            "INSERT INTO asset_retention_policies"
            "(id,workspace_id,version,days,created_by,created_at) "
            "VALUES (%s,%s,0,1,%s,now())",
            (uuid4(), workspace_a, uuid4()),
        )
        _assert_rejected(
            connection,
            "INSERT INTO asset_retention_policies"
            "(id,workspace_id,version,days,created_by,created_at) "
            "VALUES (%s,%s,1,31,%s,now())",
            (uuid4(), workspace_a, uuid4()),
        )
        _assert_rejected(
            connection,
            "UPDATE asset_retention_policies SET days=31 WHERE id=%s",
            (policy_a,),
        )
        _assert_rejected(
            connection,
            "INSERT INTO asset_trash_batches"
            "(id,workspace_id,actor_id,policy_version_id,trashed_at,purge_after,created_at) "
            "VALUES (%s,%s,%s,%s,now(),now()+interval '1 day',now())",
            (uuid4(), workspace_b, uuid4(), policy_a),
        )
        _assert_rejected(
            connection,
            "INSERT INTO asset_trash_batches"
            "(id,workspace_id,actor_id,policy_version_id,trashed_at,purge_after,created_at) "
            "VALUES (%s,%s,%s,%s,now(),now(),now())",
            (uuid4(), workspace_a, uuid4(), policy_a),
        )

        valid_inactive = {
            "batch": batch_a,
            "trashed": datetime.now(UTC),
            "purge": datetime.now(UTC) + timedelta(days=30),
        }
        invalid_rows = (
            ("purged", 2, batch_a, valid_inactive["trashed"], valid_inactive["purge"]),
            ("active", 1, batch_a, valid_inactive["trashed"], valid_inactive["purge"]),
            ("trashed", 2, None, valid_inactive["trashed"], valid_inactive["purge"]),
            ("trashed", 0, batch_a, valid_inactive["trashed"], valid_inactive["purge"]),
            ("trashed", 2, batch_a, valid_inactive["purge"], valid_inactive["trashed"]),
        )
        for lifecycle, generation, batch_id, trashed_at, purge_after in invalid_rows:
            _assert_rejected(
                connection,
                "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,lifecycle,"
                "lifecycle_generation,trash_batch_id,trashed_at,purge_after,created_at,updated_at) "
                "VALUES (%s,%s,NULL,%s,1,%s,%s,%s,%s,%s,now(),now())",
                (
                    uuid4(),
                    workspace_a,
                    f"invalid-{uuid4()}",
                    lifecycle,
                    generation,
                    batch_id,
                    trashed_at,
                    purge_after,
                ),
            )
        _assert_rejected(
            connection,
            "INSERT INTO documents(id,workspace_id,folder_id,name,metadata_revision,lifecycle,"
            "lifecycle_generation,trash_batch_id,trashed_at,purge_after,created_at,updated_at) "
            "VALUES (%s,%s,NULL,'cross-space.txt',1,'trashed',2,%s,now(),"
            "now()+interval '1 day',now(),now())",
            (uuid4(), workspace_b, batch_a),
        )

        folder_id, document_id = uuid4(), uuid4()
        connection.execute(
            "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,lifecycle,"
            "lifecycle_generation,trash_batch_id,trashed_at,purge_after,created_at,updated_at) "
            "VALUES (%s,%s,NULL,'Valid trashed',1,'trashed',2,%s,%s,%s,now(),now())",
            (
                folder_id,
                workspace_a,
                batch_a,
                valid_inactive["trashed"],
                valid_inactive["purge"],
            ),
        )
        connection.execute(
            "INSERT INTO documents(id,workspace_id,folder_id,name,metadata_revision,lifecycle,"
            "lifecycle_generation,trash_batch_id,trashed_at,purge_after,created_at,updated_at) "
            "VALUES (%s,%s,%s,'valid.txt',1,'blocked',4,%s,%s,%s,now(),now())",
            (
                document_id,
                workspace_a,
                folder_id,
                batch_a,
                valid_inactive["trashed"],
                valid_inactive["purge"],
            ),
        )
        connection.execute("DELETE FROM users WHERE id=%s", (seed.removable_actor_id,))
        assert connection.execute(
            "SELECT count(*) FROM asset_retention_policies WHERE id=%s",
            (policy_a,),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM asset_trash_batches WHERE id=%s",
            (batch_a,),
        ).fetchone() == (1,)
        _assert_rejected(
            connection,
            "DELETE FROM asset_trash_batches WHERE id=%s",
            (batch_a,),
        )
        _assert_rejected(
            connection,
            "DELETE FROM asset_retention_policies WHERE id=%s",
            (policy_a,),
        )


def test_clean_downgrade_round_trip_preserves_original_data() -> None:
    with _isolated_database_at("0034_asset_metadata_revision") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            seed = _seed_identity(connection)
            workspace_id = seed.workspace_ids[0]
            folder_id, document_id, version_id = uuid4(), uuid4(), uuid4()
            connection.execute(
                "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,"
                "created_at,updated_at) VALUES (%s,%s,NULL,'Round trip',5,now(),now())",
                (folder_id, workspace_id),
            )
            connection.execute(
                "INSERT INTO documents(id,workspace_id,folder_id,name,active_version_id,"
                "metadata_revision,created_at,updated_at) VALUES "
                "(%s,%s,%s,'roundtrip.txt',%s,6,now(),now())",
                (document_id, workspace_id, folder_id, version_id),
            )
            connection.execute(
                "INSERT INTO asset_versions(id,document_id,number,object_key,sha256,media_type,"
                "size,status,created_at,updated_at) VALUES "
                "(%s,%s,2,%s,%s,'text/plain',5,'ready',now(),now())",
                (version_id, document_id, f"synthetic/{version_id}", "b" * 64),
            )

        command.upgrade(database.config, "0035_asset_trash_state")
        command.downgrade(database.config, "0034_asset_metadata_revision")

        engine = create_engine(database.database_url)
        try:
            schema = inspect(engine)
            assert "lifecycle" not in {
                column["name"] for column in schema.get_columns("folders")
            }
            assert not schema.has_table("asset_retention_policies")
            assert not schema.has_table("asset_trash_batches")
        finally:
            engine.dispose()
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT id,name,parent_id,metadata_revision FROM folders WHERE id=%s",
                (folder_id,),
            ).fetchone() == (folder_id, "Round trip", None, 5)
            assert connection.execute(
                "SELECT id,name,folder_id,active_version_id,metadata_revision "
                "FROM documents WHERE id=%s",
                (document_id,),
            ).fetchone() == (document_id, "roundtrip.txt", folder_id, version_id, 6)
            assert connection.execute(
                "SELECT id,document_id,number,sha256,status FROM asset_versions WHERE id=%s",
                (version_id,),
            ).fetchone() == (version_id, document_id, 2, "b" * 64, "ready")


def test_unsafe_downgrade_preserves_revision_schema_and_policy() -> None:
    with _isolated_database_at("0035_asset_trash_state") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            seed = _seed_identity(connection)
            policy_id = uuid4()
            connection.execute(
                "INSERT INTO asset_retention_policies"
                "(id,workspace_id,version,days,created_by,created_at) "
                "VALUES (%s,%s,1,30,%s,now())",
                (policy_id, seed.workspace_ids[0], seed.user_id),
            )

        with pytest.raises(RuntimeError) as error:
            command.downgrade(database.config, "0034_asset_metadata_revision")
        assert str(error.value) == "asset_trash_downgrade_unsafe"

        engine = create_engine(database.database_url)
        try:
            schema = inspect(engine)
            assert "lifecycle" in {
                column["name"] for column in schema.get_columns("folders")
            }
            assert schema.has_table("asset_retention_policies")
        finally:
            engine.dispose()
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0035_asset_trash_state",)
            assert connection.execute(
                "SELECT id FROM asset_retention_policies WHERE id=%s", (policy_id,)
            ).fetchone() == (policy_id,)


def test_preflight_failure_rolls_back_every_upgrade_change() -> None:
    with _isolated_database_at("0034_asset_metadata_revision") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            seed = _seed_identity(connection)
            workspace_id = seed.workspace_ids[0]
            connection.execute(
                "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,"
                "created_at,updated_at) VALUES (%s,%s,NULL,' duplicate ',1,now(),now()),"
                "(%s,%s,NULL,'duplicate',1,now(),now())",
                (uuid4(), workspace_id, uuid4(), workspace_id),
            )

        with pytest.raises(RuntimeError) as error:
            command.upgrade(database.config, "0035_asset_trash_state")
        assert str(error.value) == "asset_trash_preflight_failed"

        engine = create_engine(database.database_url)
        try:
            schema = inspect(engine)
            assert "lifecycle" not in {
                column["name"] for column in schema.get_columns("folders")
            }
            assert not schema.has_table("asset_retention_policies")
        finally:
            engine.dispose()
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0034_asset_metadata_revision",)


def test_asset_repository_import_registers_trash_fk_targets_in_a_fresh_process() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    script = """
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.models import DocumentRecord, FolderRecord
from ai_workshop.shared.models import Base
assert SqlAlchemyAssetRepository
assert 'asset_trash_batches' in Base.metadata.tables
for table in (FolderRecord.__table__, DocumentRecord.__table__):
    for foreign_key in table.foreign_keys:
        foreign_key.column
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=backend_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
