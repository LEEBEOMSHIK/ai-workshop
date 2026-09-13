from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from ai_workshop.platform.assets.folder_names import (
    FOLDER_NAME_WHITESPACE_V1,
    folder_name_key,
)
from ai_workshop.platform.assets.trash_migration_preflight import (
    PreflightIssue,
    assert_trash_migration_ready,
    inspect_trash_migration,
)
from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[IsolatedPublishingDatabase]:
    with isolated_publishing_database(monkeypatch) as database:
        command.upgrade(database.config, "0034_asset_metadata_revision")
        yield database


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _seed_identity(connection: psycopg.Connection[Any], workspace_count: int = 2) -> list[UUID]:
    user_id = uuid4()
    connection.execute(
        "INSERT INTO users(id,display_name,email,normalized_email,password_hash,role,"
        "is_active,created_at,updated_at) VALUES (%s,'Synthetic','preflight@example.test',"
        "'preflight@example.test','hash','member',true,now(),now())",
        (user_id,),
    )
    workspace_ids = [uuid4() for _ in range(workspace_count)]
    for index, workspace_id in enumerate(workspace_ids):
        connection.execute(
            "INSERT INTO workspaces(id,name,kind,created_by,created_at,updated_at) "
            "VALUES (%s,%s,'company',%s,now(),now())",
            (workspace_id, f"Synthetic {index}", user_id),
        )
    return workspace_ids


def _insert_folder(
    connection: psycopg.Connection[Any],
    workspace_id: UUID,
    name: str,
    *,
    parent_id: UUID | None = None,
    folder_id: UUID | None = None,
    lifecycle: str | None = None,
) -> UUID:
    folder_id = folder_id or uuid4()
    columns = "id,workspace_id,parent_id,name,created_at,updated_at"
    values = "%s,%s,%s,%s,now(),now()"
    parameters: tuple[object, ...] = (folder_id, workspace_id, parent_id, name)
    if lifecycle is not None:
        columns += ",lifecycle"
        values += ",%s"
        parameters += (lifecycle,)
    connection.execute(
        f"INSERT INTO folders({columns}) VALUES ({values})",
        parameters,
    )
    return folder_id


def _insert_document(
    connection: psycopg.Connection[Any],
    workspace_id: UUID,
    folder_id: UUID | None,
) -> UUID:
    document_id = uuid4()
    connection.execute(
        "INSERT INTO documents(id,workspace_id,folder_id,name,created_at,updated_at) "
        "VALUES (%s,%s,%s,'synthetic.txt',now(),now())",
        (document_id, workspace_id, folder_id),
    )
    return document_id


def _table_fingerprint(connection: psycopg.Connection[Any], table: str) -> tuple[int, str]:
    query = psycopg.sql.SQL(
        "SELECT count(*), md5(coalesce(string_agg(row_to_json(rows)::text, '' "
        "ORDER BY id), '')) FROM (SELECT * FROM {}) AS rows"
    ).format(psycopg.sql.Identifier(table))
    result = connection.execute(query).fetchone()
    assert result is not None
    return result


def test_inspection_reports_0034_conflicts_with_sorted_opaque_ids(database) -> None:
    url = _psycopg_url(database.database_url)
    with psycopg.connect(url) as connection:
        workspace_a, workspace_b = _seed_identity(connection)
        root_a = _insert_folder(connection, workspace_a, "root")
        root_b = _insert_folder(connection, workspace_a, " root ")
        _insert_folder(connection, workspace_b, "root")
        parent_a = _insert_folder(connection, workspace_a, "parent-a")
        parent_b = _insert_folder(connection, workspace_a, "parent-b")
        sibling_a = _insert_folder(connection, workspace_a, "same", parent_id=parent_a)
        sibling_b = _insert_folder(connection, workspace_a, "\tsame", parent_id=parent_a)
        _insert_folder(connection, workspace_a, "same", parent_id=parent_b)
        empty = _insert_folder(connection, workspace_a, " \t")
        cross_parent = _insert_folder(connection, workspace_b, "cross", parent_id=root_a)
        cross_document = _insert_document(connection, workspace_b, root_a)
        self_cycle = _insert_folder(connection, workspace_a, "self")
        connection.execute(
            "UPDATE folders SET parent_id=%s WHERE id=%s", (self_cycle, self_cycle)
        )
        cycle_a = _insert_folder(connection, workspace_a, "cycle-a")
        cycle_b = _insert_folder(connection, workspace_a, "cycle-b", parent_id=cycle_a)
        cycle_c = _insert_folder(connection, workspace_a, "cycle-c", parent_id=cycle_b)
        connection.execute("UPDATE folders SET parent_id=%s WHERE id=%s", (cycle_c, cycle_a))
        missing_parent = uuid4()
        missing_folder = uuid4()
        missing_document = uuid4()
        connection.execute("ALTER TABLE folders DROP CONSTRAINT folders_parent_id_fkey")
        connection.execute("ALTER TABLE documents DROP CONSTRAINT documents_folder_id_fkey")
        _insert_folder(
            connection,
            workspace_a,
            "orphan",
            parent_id=missing_parent,
            folder_id=missing_folder,
        )
        connection.execute(
            "INSERT INTO documents(id,workspace_id,folder_id,name,created_at,updated_at) "
            "VALUES (%s,%s,%s,'orphan.txt',now(),now())",
            (missing_document, workspace_a, uuid4()),
        )

    engine = create_engine(database.database_url)
    try:
        with engine.connect() as connection:
            report = inspect_trash_migration(connection)
            issues = {issue.code: issue.entity_ids for issue in report.issues}

            assert not report.ready
            assert issues == {
                "document_folder_missing": (missing_document,),
                "document_folder_workspace_mismatch": (cross_document,),
                "folder_cycle": tuple(sorted((self_cycle, cycle_a, cycle_b, cycle_c))),
                "folder_name_empty": (empty,),
                "folder_name_noncanonical": tuple(sorted((root_b, sibling_b, empty))),
                "folder_parent_missing": (missing_folder,),
                "folder_parent_workspace_mismatch": (cross_parent,),
                "folder_root_name_conflict": tuple(sorted((root_a, root_b))),
                "folder_sibling_name_conflict": tuple(sorted((sibling_a, sibling_b))),
            }
            with pytest.raises(RuntimeError) as error:
                assert_trash_migration_ready(connection)
            assert str(error.value) == "asset_trash_preflight_failed"
    finally:
        engine.dispose()


def test_inspection_is_read_only_and_clean_0034_data_is_ready(database) -> None:
    url = _psycopg_url(database.database_url)
    with psycopg.connect(url) as connection:
        workspace_a, workspace_b = _seed_identity(connection)
        parent_a = _insert_folder(connection, workspace_a, "parent-a")
        parent_b = _insert_folder(connection, workspace_a, "parent-b")
        _insert_folder(connection, workspace_a, "same", parent_id=parent_a)
        _insert_folder(connection, workspace_a, "same", parent_id=parent_b)
        _insert_folder(connection, workspace_b, "parent-a")
        _insert_document(connection, workspace_a, parent_a)
        before = {
            table: _table_fingerprint(connection, table) for table in ("folders", "documents")
        }

    engine = create_engine(database.database_url)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            )
            assert connection.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"

            report = inspect_trash_migration(connection)

            assert report.ready
            assert report.issues == ()
            assert connection.in_transaction()
            assert connection.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
    finally:
        engine.dispose()

    with psycopg.connect(url) as connection:
        after = {
            table: _table_fingerprint(connection, table) for table in ("folders", "documents")
        }
    assert after == before


def test_lifecycle_filters_only_name_conflicts_not_name_validity(database) -> None:
    url = _psycopg_url(database.database_url)
    with psycopg.connect(url) as connection:
        connection.execute(
            "ALTER TABLE folders ADD COLUMN lifecycle varchar(32) NOT NULL DEFAULT 'active'"
        )
        workspace_a, workspace_b = _seed_identity(connection)
        active_root = _insert_folder(connection, workspace_a, "same", lifecycle="active")
        inactive_noncanonical = _insert_folder(
            connection,
            workspace_a,
            " same ",
            lifecycle="trashed",
        )
        inactive_empty = _insert_folder(
            connection,
            workspace_a,
            "\t",
            lifecycle="trashed",
        )
        cross_parent = _insert_folder(
            connection,
            workspace_b,
            "cross",
            parent_id=active_root,
            lifecycle="trashed",
        )
        cycle_a = _insert_folder(connection, workspace_a, "cycle-a", lifecycle="trashed")
        cycle_b = _insert_folder(
            connection,
            workspace_a,
            "cycle-b",
            parent_id=cycle_a,
            lifecycle="trashed",
        )
        connection.execute("UPDATE folders SET parent_id=%s WHERE id=%s", (cycle_b, cycle_a))

    engine = create_engine(database.database_url)
    try:
        with engine.connect() as connection:
            issues = {
                issue.code: issue.entity_ids for issue in inspect_trash_migration(connection).issues
            }
    finally:
        engine.dispose()

    assert issues == {
        "folder_cycle": tuple(sorted((cycle_a, cycle_b))),
        "folder_name_empty": (inactive_empty,),
        "folder_name_noncanonical": tuple(sorted((inactive_noncanonical, inactive_empty))),
        "folder_parent_workspace_mismatch": (cross_parent,),
    }


def test_postgresql_btrim_matches_python_folder_name_key(database) -> None:
    names = (
        "",
        "plain",
        "\t 연구 \u3000",
        "\u200b연구\u200b",
        "e\u0301",
        "\u00a0e\u0301\u202f",
        FOLDER_NAME_WHITESPACE_V1,
    )
    engine = create_engine(database.database_url)
    try:
        with engine.connect() as connection:
            for name in names:
                postgres_key = connection.execute(
                    text("SELECT btrim(:name, :chars)"),
                    {"name": name, "chars": FOLDER_NAME_WHITESPACE_V1},
                ).scalar_one()

                assert postgres_key == folder_name_key(name)
    finally:
        engine.dispose()


def test_thousands_deep_chains_are_iterative_and_report_only_terminal_cycle(database) -> None:
    url = _psycopg_url(database.database_url)
    depth = 2_500
    acyclic_ids = tuple(UUID(int=index) for index in range(1, depth + 1))
    cyclic_ids = tuple(UUID(int=index) for index in range(depth + 1, (depth * 2) + 1))
    with psycopg.connect(url) as connection:
        (workspace_id,) = _seed_identity(connection, workspace_count=1)
        folder_rows = [
            (folder_id, workspace_id, f"deep-{index}")
            for index, folder_id in enumerate((*acyclic_ids, *cyclic_ids))
        ]
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO folders(id,workspace_id,name,created_at,updated_at) "
                "VALUES (%s,%s,%s,now(),now())",
                folder_rows,
            )
        parent_rows = [
            (acyclic_ids[index + 1], acyclic_ids[index]) for index in range(depth - 1)
        ]
        parent_rows.extend(
            (cyclic_ids[index + 1], cyclic_ids[index]) for index in range(depth - 1)
        )
        parent_rows.append((cyclic_ids[-2], cyclic_ids[-1]))
        with connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE folders SET parent_id=%s WHERE id=%s",
                parent_rows,
            )

    engine = create_engine(database.database_url)
    try:
        with engine.connect() as connection:
            report = inspect_trash_migration(connection)
    finally:
        engine.dispose()

    assert report.issues == (
        PreflightIssue(
            code="folder_cycle",
            entity_ids=tuple(sorted(cyclic_ids[-2:])),
        ),
    )


def test_empty_postgresql_database_fails_closed_without_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_publishing_database(monkeypatch) as database:
        engine = create_engine(database.database_url)
        try:
            with engine.connect() as connection, pytest.raises(RuntimeError) as error:
                inspect_trash_migration(connection)
        finally:
            engine.dispose()

    assert str(error.value) == "asset_trash_preflight_inspection_failed"
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__


def test_non_postgresql_connection_fails_closed() -> None:
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        with engine.connect() as connection, pytest.raises(RuntimeError) as error:
            inspect_trash_migration(connection)
    finally:
        engine.dispose()

    assert str(error.value) == "asset_trash_preflight_unsupported_database"
