from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
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
class PurgeSeed:
    user_id: UUID
    workspace_ids: tuple[UUID, UUID]
    batch_ids: tuple[UUID, UUID]


@dataclass(frozen=True, slots=True)
class IdentitySeed:
    user_id: UUID
    workspace_ids: tuple[UUID, UUID]


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _seed_identity(connection: psycopg.Connection[Any]) -> IdentitySeed:
    user_id = uuid4()
    email = f"purge-owner-{user_id}@example.test"
    connection.execute(
        "INSERT INTO users(id,display_name,email,normalized_email,password_hash,role,"
        "is_active,created_at,updated_at) VALUES (%s,'Synthetic purge owner',%s,%s,"
        "'hash','member',true,now(),now())",
        (user_id, email, email),
    )
    workspace_ids = (uuid4(), uuid4())
    for index, workspace_id in enumerate(workspace_ids):
        connection.execute(
            "INSERT INTO workspaces(id,name,kind,created_by,created_at,updated_at) "
            "VALUES (%s,%s,'company',%s,now(),now())",
            (workspace_id, f"Synthetic purge {index}", user_id),
        )
    return IdentitySeed(user_id, workspace_ids)


def _seed_batches(connection: psycopg.Connection[Any]) -> PurgeSeed:
    identity = _seed_identity(connection)
    batch_ids = (uuid4(), uuid4())
    for workspace_id, batch_id in zip(
        identity.workspace_ids, batch_ids, strict=True
    ):
        policy_id = uuid4()
        connection.execute(
            "INSERT INTO asset_retention_policies"
            "(id,workspace_id,version,days,created_by,created_at) "
            "VALUES (%s,%s,1,30,%s,now())",
            (policy_id, workspace_id, identity.user_id),
        )
        connection.execute(
            "INSERT INTO asset_trash_batches"
            "(id,workspace_id,actor_id,policy_version_id,trashed_at,purge_after,created_at) "
            "VALUES (%s,%s,%s,%s,now(),now()+interval '30 days',now())",
            (batch_id, workspace_id, identity.user_id, policy_id),
        )
    return PurgeSeed(identity.user_id, identity.workspace_ids, batch_ids)


@contextmanager
def _isolated_database_at(revision: str) -> Iterator[IsolatedPublishingDatabase]:
    monkeypatch = pytest.MonkeyPatch()
    try:
        with isolated_publishing_database(monkeypatch) as database:
            command.upgrade(database.config, revision)
            yield database
    finally:
        monkeypatch.undo()


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[IsolatedPublishingDatabase]:
    with _isolated_database_at("0036_asset_purge_jobs") as database:
        yield database


def _assert_rejected(
    connection: psycopg.Connection[Any],
    statement: str,
    parameters: tuple[object, ...],
) -> None:
    with pytest.raises(psycopg.Error), connection.transaction():
        connection.execute(statement, parameters)


def _insert_job(
    connection: psycopg.Connection[Any],
    job_id: UUID,
    workspace_id: UUID,
    batch_id: UUID,
    request_key: str,
    *,
    status: str = "purge_pending",
    attempt_count: int = 0,
    finished_at: datetime | None = None,
) -> None:
    connection.execute(
        "INSERT INTO asset_purge_jobs"
        "(id,workspace_id,trash_batch_id,request_key,status,attempt_count,available_at,"
        "error_code,finished_at,created_at,updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,now(),NULL,%s,now(),now())",
        (
            job_id,
            workspace_id,
            batch_id,
            request_key,
            status,
            attempt_count,
            finished_at,
        ),
    )


def _assert_downgrade_rejected_preserving(
    database: IsolatedPublishingDatabase,
    statement: str,
    parameters: tuple[object, ...],
    expected: tuple[object, ...],
) -> None:
    with pytest.raises(RuntimeError) as error:
        command.downgrade(database.config, "0035_asset_trash_state")
    assert str(error.value) == "asset_purge_downgrade_unsafe"
    engine = create_engine(database.database_url)
    try:
        schema = inspect(engine)
        assert schema.has_table("asset_purge_jobs")
        assert schema.has_table("asset_purge_dispatches")
    finally:
        engine.dispose()
    with psycopg.connect(_psycopg_url(database.database_url)) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("0036_asset_purge_jobs",)
        assert connection.execute(statement, parameters).fetchone() == expected


def test_database_enforces_job_and_dispatch_contracts(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_batches(connection)
        workspace_a, workspace_b = seed.workspace_ids
        batch_a, batch_b = seed.batch_ids
        batch_a2 = uuid4()
        policy_row = connection.execute(
            "SELECT policy_version_id FROM asset_trash_batches WHERE id=%s",
            (batch_a,),
        ).fetchone()
        assert policy_row is not None
        policy_a = policy_row[0]
        connection.execute(
            "INSERT INTO asset_trash_batches"
            "(id,workspace_id,actor_id,policy_version_id,trashed_at,purge_after,created_at) "
            "VALUES (%s,%s,%s,%s,now(),now()+interval '30 days',now())",
            (batch_a2, workspace_a, seed.user_id, policy_a),
        )
        batch_b2 = uuid4()
        policy_b_row = connection.execute(
            "SELECT policy_version_id FROM asset_trash_batches WHERE id=%s",
            (batch_b,),
        ).fetchone()
        assert policy_b_row is not None
        connection.execute(
            "INSERT INTO asset_trash_batches"
            "(id,workspace_id,actor_id,policy_version_id,trashed_at,purge_after,created_at) "
            "VALUES (%s,%s,%s,%s,now(),now()+interval '30 days',now())",
            (batch_b2, workspace_b, seed.user_id, policy_b_row[0]),
        )
        job_id = uuid4()
        _insert_job(connection, job_id, workspace_a, batch_a, "purge-request-a")
        same_key_other_workspace_job_id = uuid4()
        _insert_job(
            connection,
            same_key_other_workspace_job_id,
            workspace_b,
            batch_b,
            "purge-request-a",
        )
        assert connection.execute(
            "SELECT workspace_id,request_key FROM asset_purge_jobs "
            "WHERE id=%s",
            (same_key_other_workspace_job_id,),
        ).fetchone() == (workspace_b, "purge-request-a")

        rejected_jobs = (
            (workspace_a, batch_b2, "cross-space", "purge_pending", 0, None),
            (workspace_a, batch_a2, "purge-request-a", "purge_pending", 0, None),
            (workspace_a, batch_a, "duplicate-batch", "purge_pending", 0, None),
            (workspace_a, batch_a2, "negative", "purge_pending", -1, None),
            (workspace_a, batch_a2, "unknown", "unknown", 0, None),
            (workspace_a, batch_a2, "unfinished-purged", "purged", 0, None),
            (
                workspace_a,
                batch_a2,
                "finished-pending",
                "purge_pending",
                0,
                datetime.now(UTC),
            ),
        )
        for workspace_id, batch_id, key, status, attempts, finished_at in rejected_jobs:
            _assert_rejected(
                connection,
                "INSERT INTO asset_purge_jobs"
                "(id,workspace_id,trash_batch_id,request_key,status,attempt_count,"
                "available_at,error_code,finished_at,created_at,updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,now(),NULL,%s,now(),now())",
                (uuid4(), workspace_id, batch_id, key, status, attempts, finished_at),
            )

        invalid_dispatches = (
            ("pending", uuid4(), datetime.now(UTC), None, 0),
            ("claimed", None, datetime.now(UTC), None, 0),
            ("claimed", uuid4(), None, None, 0),
            ("sent", uuid4(), datetime.now(UTC), datetime.now(UTC), 0),
            ("sent", None, None, None, 0),
            ("pending", None, None, None, -1),
            ("unknown", None, None, None, 0),
        )
        for status, token, claimed_at, sent_at, attempts in invalid_dispatches:
            _assert_rejected(
                connection,
                "INSERT INTO asset_purge_dispatches"
                "(id,job_id,status,attempt_count,available_at,claim_token,claimed_at,sent_at,"
                "created_at,updated_at) VALUES (%s,%s,%s,%s,now(),%s,%s,%s,now(),now())",
                (uuid4(), job_id, status, attempts, token, claimed_at, sent_at),
            )

        dispatch_id = uuid4()
        connection.execute(
            "INSERT INTO asset_purge_dispatches(id,job_id,available_at,created_at,updated_at) "
            "VALUES (%s,%s,now(),now(),now())",
            (dispatch_id, job_id),
        )
        assert connection.execute(
            "SELECT status,attempt_count,claim_token,claimed_at,sent_at "
            "FROM asset_purge_dispatches WHERE id=%s",
            (dispatch_id,),
        ).fetchone() == ("pending", 0, None, None, None)
        claim_token = uuid4()
        connection.execute(
            "UPDATE asset_purge_dispatches SET status='claimed',claim_token=%s,"
            "claimed_at=now() WHERE id=%s",
            (claim_token, dispatch_id),
        )
        claimed_row = connection.execute(
            "SELECT status,claim_token,claimed_at,sent_at "
            "FROM asset_purge_dispatches WHERE id=%s",
            (dispatch_id,),
        ).fetchone()
        assert claimed_row is not None
        assert claimed_row[:2] == ("claimed", claim_token)
        connection.execute(
            "UPDATE asset_purge_dispatches SET status='sent',claim_token=NULL,"
            "claimed_at=NULL,sent_at=now() WHERE id=%s",
            (dispatch_id,),
        )
        assert connection.execute(
            "SELECT status,claim_token,claimed_at,sent_at IS NOT NULL "
            "FROM asset_purge_dispatches WHERE id=%s",
            (dispatch_id,),
        ).fetchone() == ("sent", None, None, True)
        _assert_rejected(
            connection,
            "INSERT INTO asset_purge_dispatches"
            "(id,job_id,available_at,created_at,updated_at) "
            "VALUES (%s,%s,now(),now(),now())",
            (uuid4(), job_id),
        )
        _insert_job(
            connection,
            uuid4(),
            workspace_a,
            batch_a2,
            "completed-request",
            status="purged",
            finished_at=datetime.now(UTC),
        )

        constraint_rows = connection.execute(
            "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid IN ('asset_purge_jobs'::regclass,"
            "'asset_purge_dispatches'::regclass)"
        ).fetchall()
        constraints = {name: definition for name, definition in constraint_rows}
        expected_constraint_names = {
            "ck_asset_purge_jobs_status",
            "ck_asset_purge_jobs_attempt_count",
            "ck_asset_purge_jobs_finished_state",
            "uq_asset_purge_jobs_workspace_request_key",
            "uq_asset_purge_jobs_trash_batch_id",
            "ck_asset_purge_dispatches_status",
            "ck_asset_purge_dispatches_attempt_count",
            "ck_asset_purge_dispatches_claim_state",
            "uq_asset_purge_dispatches_job_id",
        }
        assert constraints.keys() >= expected_constraint_names
        assert all(
            value in constraints["ck_asset_purge_jobs_status"]
            for value in ("purge_pending", "purging", "retry_wait", "blocked", "purged")
        )
        assert all(
            value in constraints["ck_asset_purge_dispatches_status"]
            for value in ("pending", "claimed", "sent")
        )

        column_rows = connection.execute(
            "SELECT table_name,column_name,is_nullable,column_default "
            "FROM information_schema.columns WHERE table_schema=current_schema() "
            "AND table_name IN ('asset_purge_jobs','asset_purge_dispatches')"
        ).fetchall()
        columns = {
            (table, column): (nullable, default)
            for table, column, nullable, default in column_rows
        }
        assert columns[("asset_purge_jobs", "request_key")][0] == "NO"
        assert columns[("asset_purge_jobs", "error_code")][0] == "YES"
        assert columns[("asset_purge_jobs", "status")] == (
            "NO",
            "'purge_pending'::character varying",
        )
        assert columns[("asset_purge_jobs", "attempt_count")] == ("NO", "0")
        assert columns[("asset_purge_dispatches", "status")] == (
            "NO",
            "'pending'::character varying",
        )
        assert columns[("asset_purge_dispatches", "attempt_count")] == ("NO", "0")


def test_job_dispatch_transaction_rolls_back_together(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    job_id, dispatch_id = uuid4(), uuid4()
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_batches(connection)
        connection.execute("SAVEPOINT purge_pair")
        _insert_job(
            connection,
            job_id,
            seed.workspace_ids[0],
            seed.batch_ids[0],
            "rollback-request",
        )
        connection.execute(
            "INSERT INTO asset_purge_dispatches"
            "(id,job_id,available_at,created_at,updated_at) "
            "VALUES (%s,%s,now(),now(),now())",
            (dispatch_id, job_id),
        )
        connection.execute("ROLLBACK TO SAVEPOINT purge_pair")
        assert connection.execute(
            "SELECT count(*) FROM asset_purge_jobs WHERE id=%s", (job_id,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM asset_purge_dispatches WHERE id=%s", (dispatch_id,)
        ).fetchone() == (0,)


def test_jobs_survive_source_removal_and_restrict_owned_references(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_batches(connection)
        workspace_id = seed.workspace_ids[0]
        batch_id = seed.batch_ids[0]
        document_id, version_id, job_id = uuid4(), uuid4(), uuid4()
        connection.execute(
            "INSERT INTO documents(id,workspace_id,folder_id,name,active_version_id,"
            "metadata_revision,created_at,updated_at) "
            "VALUES (%s,%s,NULL,'synthetic-purge.txt',%s,1,now(),now())",
            (document_id, workspace_id, version_id),
        )
        connection.execute(
            "INSERT INTO asset_versions(id,document_id,number,object_key,sha256,media_type,"
            "size,status,created_at,updated_at) VALUES "
            "(%s,%s,1,%s,%s,'text/plain',1,'ready',now(),now())",
            (version_id, document_id, f"synthetic/{version_id}", "c" * 64),
        )
        _insert_job(connection, job_id, workspace_id, batch_id, "source-independent")
        connection.execute("DELETE FROM asset_versions WHERE id=%s", (version_id,))
        connection.execute("DELETE FROM documents WHERE id=%s", (document_id,))
        assert connection.execute(
            "SELECT trash_batch_id FROM asset_purge_jobs WHERE id=%s", (job_id,)
        ).fetchone() == (batch_id,)
        _assert_rejected(
            connection,
            "DELETE FROM asset_trash_batches WHERE id=%s",
            (batch_id,),
        )
        _assert_rejected(
            connection,
            "DELETE FROM workspaces WHERE id=%s",
            (workspace_id,),
        )


def test_clean_round_trip_and_nonempty_downgrade_guard() -> None:
    with _isolated_database_at("0035_asset_trash_state") as database:
        engine = create_engine(database.database_url)
        try:
            command.upgrade(database.config, "0036_asset_purge_jobs")
            assert inspect(engine).has_table("asset_purge_jobs")
            command.downgrade(database.config, "0035_asset_trash_state")
            schema = inspect(engine)
            assert not schema.has_table("asset_purge_jobs")
            assert not schema.has_table("asset_purge_dispatches")
        finally:
            engine.dispose()

    with _isolated_database_at("0036_asset_purge_jobs") as database:
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
        _assert_downgrade_rejected_preserving(
            database,
            "SELECT id FROM asset_retention_policies WHERE id=%s",
            (policy_id,),
            (policy_id,),
        )

    with _isolated_database_at("0036_asset_purge_jobs") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            seed = _seed_identity(connection)
            folder_id = uuid4()
            connection.execute(
                "INSERT INTO folders(id,workspace_id,parent_id,name,metadata_revision,"
                "lifecycle,lifecycle_generation,created_at,updated_at) "
                "VALUES (%s,%s,NULL,'Raw generation folder',1,'active',2,now(),now())",
                (folder_id, seed.workspace_ids[0]),
            )
            assert connection.execute(
                "SELECT count(*) FROM asset_retention_policies"
            ).fetchone() == (0,)
        _assert_downgrade_rejected_preserving(
            database,
            "SELECT id,lifecycle_generation FROM folders WHERE id=%s",
            (folder_id,),
            (folder_id, 2),
        )

    with _isolated_database_at("0036_asset_purge_jobs") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            seed = _seed_identity(connection)
            document_id = uuid4()
            connection.execute(
                "INSERT INTO documents(id,workspace_id,folder_id,name,metadata_revision,"
                "lifecycle,lifecycle_generation,created_at,updated_at) "
                "VALUES (%s,%s,NULL,'raw-generation.txt',1,'active',2,now(),now())",
                (document_id, seed.workspace_ids[0]),
            )
            assert connection.execute(
                "SELECT count(*) FROM asset_retention_policies"
            ).fetchone() == (0,)
        _assert_downgrade_rejected_preserving(
            database,
            "SELECT id,lifecycle_generation FROM documents WHERE id=%s",
            (document_id,),
            (document_id, 2),
        )

    with _isolated_database_at("0036_asset_purge_jobs") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            purge_seed = _seed_batches(connection)
            job_id = uuid4()
            _insert_job(
                connection,
                job_id,
                purge_seed.workspace_ids[0],
                purge_seed.batch_ids[0],
                "unsafe-downgrade",
            )
        _assert_downgrade_rejected_preserving(
            database,
            "SELECT id FROM asset_purge_jobs WHERE id=%s",
            (job_id,),
            (job_id,),
        )

    migration_source = (
        Path(__file__).resolve().parents[4]
        / "alembic"
        / "versions"
        / "0036_asset_purge_jobs.py"
    ).read_text(encoding="utf-8")
    for table_name in (
        "asset_trash_batches",
        "asset_purge_jobs",
        "asset_purge_dispatches",
    ):
        assert f"EXISTS (SELECT 1 FROM {table_name})" in migration_source


def test_model_registry_resolves_purge_foreign_keys_in_a_fresh_process() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    script = """
from ai_workshop.shared.model_registry import load_models
from ai_workshop.shared.models import Base
load_models()
for table_name in ('asset_purge_jobs', 'asset_purge_dispatches'):
    table = Base.metadata.tables[table_name]
    for foreign_key in table.foreign_keys:
        foreign_key.column
dispatch = Base.metadata.tables['asset_purge_dispatches']
job = Base.metadata.tables['asset_purge_jobs']
assert {
    column.name: (
        column.nullable,
        str(column.server_default.arg) if column.server_default else None,
    )
    for column in job.columns
} == {
    'id': (False, None),
    'workspace_id': (False, None),
    'trash_batch_id': (False, None),
    'request_key': (False, None),
    'status': (False, 'purge_pending'),
    'attempt_count': (False, '0'),
    'available_at': (False, None),
    'error_code': (True, None),
    'finished_at': (True, None),
    'created_at': (False, 'now()'),
    'updated_at': (False, 'now()'),
}
assert {
    column.name: (
        column.nullable,
        str(column.server_default.arg) if column.server_default else None,
    )
    for column in dispatch.columns
} == {
    'id': (False, None),
    'job_id': (False, None),
    'status': (False, 'pending'),
    'attempt_count': (False, '0'),
    'available_at': (False, None),
    'claim_token': (True, None),
    'claimed_at': (True, None),
    'sent_at': (True, None),
    'created_at': (False, 'now()'),
    'updated_at': (False, 'now()'),
}
assert {
    constraint.name for constraint in job.constraints if constraint.name
} >= {
    'ck_asset_purge_jobs_status',
    'ck_asset_purge_jobs_attempt_count',
    'ck_asset_purge_jobs_finished_state',
    'uq_asset_purge_jobs_workspace_request_key',
    'uq_asset_purge_jobs_trash_batch_id',
}
assert {
    constraint.name for constraint in dispatch.constraints if constraint.name
} >= {
    'ck_asset_purge_dispatches_status',
    'ck_asset_purge_dispatches_attempt_count',
    'ck_asset_purge_dispatches_claim_state',
    'uq_asset_purge_dispatches_job_id',
}
assert {
    (index.name, tuple(column.name for column in index.columns))
    for index in dispatch.indexes
} == {('ix_asset_purge_dispatches_status_available_at', ('status', 'available_at'))}
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=backend_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
