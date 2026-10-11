"""Finite Task1 psycopg wire double. No ORM/session/issuer substitution."""

import asyncio
import re
from collections.abc import Callable
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast

import psycopg
from psycopg.types.json import Jsonb
from sqlalchemy import Table
from sqlalchemy.util import immutabledict

from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord
from ai_workshop.labs.rag.indexing.access_epoch_models import (
    AccessEpochEventRecord,
    AccessEpochExecutionRecord,
    AccessEpochFloorRecord,
    AccessEpochKeyEventRecord,
    AccessEpochRecord,
)
from ai_workshop.labs.rag.indexing.alias_models import (
    AliasClusterGateRecord,
    AliasOperationRecord,
    AliasRecoveryReceiptRecord,
)
from ai_workshop.labs.rag.models.models import ProfileModelBindingRecord, ProfileRecord
from ai_workshop.platform.identity.models import UserRecord

MODELS = (
    UserRecord,
    ProfileRecord,
    ProfileModelBindingRecord,
    RagIndexBuildRecord,
    AliasOperationRecord,
    AliasClusterGateRecord,
    AliasRecoveryReceiptRecord,
    AccessEpochRecord,
    AccessEpochExecutionRecord,
    AccessEpochFloorRecord,
    AccessEpochKeyEventRecord,
    AccessEpochEventRecord,
)
TABLES = {model.__tablename__: cast(Table, model.__table__) for model in MODELS}
_VALUE = re.compile(
    r"%\(([A-Za-z_][A-Za-z_0-9]*)\)s"
    r"(?:::(?:UUID|VARCHAR|INTEGER|BOOLEAN|JSONB|TIMESTAMP WITH TIME ZONE))?\Z"
)


def _denied() -> AssertionError:
    return AssertionError("synthetic_sql_transport_denied")


def _parameter(expression: str, parameters: dict[str, Any]) -> Any:
    match = _VALUE.fullmatch(expression)
    if match is None or match.group(1) not in parameters:
        raise _denied()
    value = parameters[match.group(1)]
    return deepcopy(value.obj if isinstance(value, Jsonb) else value)


class RelationalRows:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {name: [] for name in TABLES}
        self.connections: list[Connection] = []
        self.select_count = self.dml_count = self.commit_count = self.rollback_count = 0
        self.commit_failure: str | None = None
        self.unknown_shape: str | None = None
        self.readonly_count = self.readonly_reads = 0
        self.selected_tables: list[str] = []
        self.cancel_read_at: int | None = None
        self.fail_read_at: int | None = None
        self.rollback_failure_once = False

    def seed(self, record: Any) -> None:
        table = record.__table__
        if table.name not in TABLES or TABLES[table.name] is not table:
            raise _denied()
        self.tables[table.name].append(
            {col.name: deepcopy(getattr(record, col.name)) for col in table.columns}
        )

    async def connect(self, *args: Any, **kwargs: Any) -> "Connection":
        connection = Connection(self)
        self.connections.append(connection)
        return connection

    def column(self, table: str, name: str) -> None:
        if table not in TABLES or name not in TABLES[table].columns:
            raise _denied()

    def predicate(
        self, table: str, condition: str, parameters: dict[str, Any]
    ) -> Callable[[dict[str, Any]], bool]:
        if table == "rag_profile_model_bindings":
            match = re.fullmatch(r"rag_profile_model_bindings.profile_id IN \((.+)\)", condition)
            if match is None:
                raise _denied()
            values = [_parameter(part, parameters) for part in match.group(1).split(", ")]
            return lambda row: row["profile_id"] in values
        terms = condition.split(" AND ") if condition else []
        wanted: dict[str, Any] = {}
        for term in terms:
            match = re.fullmatch(r"([a-z_][a-z_0-9]*)\.([a-z_][a-z_0-9]*) = (.+)", term)
            if match is None or match.group(1) != table:
                raise _denied()
            column = match.group(2)
            self.column(table, column)
            if column in wanted:
                raise _denied()
            wanted[column] = _parameter(match.group(3), parameters)
        return lambda row: all(row[name] == value for name, value in wanted.items())

    def run(
        self, sql: str, parameters: dict[str, Any]
    ) -> tuple[list[str], list[tuple[Any, ...]], int]:
        normalized = " ".join(sql.split())
        initialization = {
            "select pg_catalog.version()": "PostgreSQL 16.4 synthetic",
            "select current_schema()": "public",
            "show transaction isolation level": "read committed",
            "show standard_conforming_strings": "on",
            "select 1": "1",
            ";": "1",
        }
        if normalized.lower() in initialization:
            return ["value"], [(initialization[normalized.lower()],)], 1
        selected = re.fullmatch(
            r"SELECT (.+) FROM ([a-z_][a-z_0-9]*)(?: WHERE (.*?))?"
            r"(?: ORDER BY ([a-z_][a-z_0-9]*)\.([a-z_][a-z_0-9]*))?(?: FOR UPDATE)?",
            normalized,
        )
        if selected:
            projected, table, where, ordering_table, ordering = selected.groups()
            self.selected_tables.append(table)
            if table not in TABLES:
                raise _denied()
            columns = []
            for item in projected.split(", "):
                if table == "rag_profile_model_bindings" and " AS " in item:
                    raw, label = item.split(" AS ")
                    if label != raw.replace(".", "_"):
                        raise _denied()
                    item = raw
                column = re.fullmatch(r"([a-z_][a-z_0-9]*)\.([a-z_][a-z_0-9]*)", item)
                if column is None or column.group(1) != table:
                    raise _denied()
                self.column(table, column.group(2))
                columns.append(column.group(2))
            if ordering is not None:
                if ordering_table != table:
                    raise _denied()
                self.column(table, ordering)
            found = [
                r for r in self.tables[table] if self.predicate(table, where or "", parameters)(r)
            ]
            if ordering is not None:
                found.sort(key=lambda row: row[ordering])
            self.select_count += 1
            return columns, [tuple(deepcopy(row[c]) for c in columns) for row in found], len(found)
        inserted = re.fullmatch(
            r"INSERT INTO ([a-z_][a-z_0-9]*) \(([^()]+)\) VALUES \((.*)\)"
            r"( ON CONFLICT \(cluster_uuid\) DO NOTHING)?",
            normalized,
        )
        if inserted:
            table, column_text, values_text, conflict = inserted.groups()
            if table not in {
                "rag_alias_cluster_gates",
                "rag_access_epochs",
                "rag_access_epoch_executions",
            }:
                raise _denied()
            columns, values = column_text.split(", "), values_text.split(", ")
            if len(columns) != len(values) or len(set(columns)) != len(columns):
                raise _denied()
            row: dict[str, Any] = {column.name: None for column in TABLES[table].columns}
            for column, expression in zip(columns, values, strict=True):
                self.column(table, column)
                row[column] = _parameter(expression, parameters)
            if conflict:
                if table != "rag_alias_cluster_gates" or columns != ["cluster_uuid"]:
                    raise _denied()
                if any(r["cluster_uuid"] == row["cluster_uuid"] for r in self.tables[table]):
                    self.dml_count += 1
                    return [], [], 0
                row.update(state="admitted", revision=0)
            primary = [column.name for column in TABLES[table].primary_key.columns]
            if any(all(old[c] == row[c] for c in primary) for old in self.tables[table]):
                raise psycopg.IntegrityError("synthetic_sql_duplicate")
            self.tables[table].append(row)
            self.dml_count += 1
            return [], [], 1
        updated = re.fullmatch(r"UPDATE (rag_alias_cluster_gates) SET (.+) WHERE (.+)", normalized)
        if updated:
            table, assignments, where = updated.groups()
            updates = {}
            for assignment in assignments.split(", "):
                matched = re.fullmatch(r"([a-z_][a-z_0-9]*)=(.+)", assignment)
                if matched is None:
                    raise _denied()
                self.column(table, matched.group(1))
                updates[matched.group(1)] = _parameter(matched.group(2), parameters)
            selected_rows = [
                row for row in self.tables[table] if self.predicate(table, where, parameters)(row)
            ]
            for row in selected_rows:
                row.update(updates)
            self.dml_count += 1
            return [], [], len(selected_rows)
        self.unknown_shape = normalized.split(" ", 1)[0]
        raise _denied()


class Connection:
    def __init__(self, store: RelationalRows) -> None:
        self.store = store
        self.autocommit = False
        self.closed = False
        self.broken = False
        self.read_only = False
        self.statement_seen = False
        self.info = SimpleNamespace(transaction_status=0)
        self.before: dict[str, list[dict[str, Any]]] | None = None

    def cursor(self, *args: Any, **kwargs: Any) -> "Cursor":
        return Cursor(self)

    def add_notice_handler(self, handler: Any) -> None:
        pass

    async def set_autocommit(self, value: bool) -> None:
        self.autocommit = value

    async def commit(self) -> None:
        failure = self.store.commit_failure
        if failure == "cancel_before":
            await self.rollback()
            raise asyncio.CancelledError()
        if failure == "rollback":
            await self.rollback()
            raise psycopg.OperationalError("synthetic_commit_failure")
        self.store.commit_count += 1
        self.before = None
        self.info.transaction_status = 0
        self.read_only = self.statement_seen = False
        if failure == "lost_ack":
            raise psycopg.OperationalError("synthetic_commit_response_lost")

    async def rollback(self) -> None:
        was_read_only = self.read_only
        if self.before is not None:
            self.store.tables = self.before
        self.before = None
        self.info.transaction_status = 0
        self.store.rollback_count += 1
        self.read_only = self.statement_seen = False
        if self.store.rollback_failure_once and was_read_only:
            self.store.rollback_failure_once = False
            raise psycopg.OperationalError("synthetic_rollback_failure")

    async def close(self) -> None:
        self.closed = True


class Cursor:
    arraysize = 1

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.rows: list[tuple[Any, ...]] = []
        self.rowcount = 0
        self.description: list[tuple[Any, ...]] | None = None
        self.pgresult = SimpleNamespace(status=2)

    async def execute(self, query: Any, params: Any = None, **kwargs: Any) -> None:
        if type(query) is not str or (
            params is not None and type(params) not in (dict, immutabledict)
        ):
            raise _denied()
        if not self.connection.autocommit and self.connection.before is None:
            self.connection.before = deepcopy(self.connection.store.tables)
            self.connection.info.transaction_status = 2
        normalized = " ".join(query.split())
        if normalized == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY":
            if self.connection.statement_seen or params:
                raise _denied()
            self.connection.statement_seen = self.connection.read_only = True
            self.connection.store.readonly_count += 1
            columns: list[str] = []
            self.rows, self.rowcount = [], 0
        else:
            if self.connection.read_only:
                if not normalized.startswith("SELECT ") or "FOR UPDATE" in normalized:
                    raise _denied()
                self.connection.store.readonly_reads += 1
                ordinal = self.connection.store.readonly_reads
                if ordinal == self.connection.store.cancel_read_at:
                    raise asyncio.CancelledError()
                if ordinal == self.connection.store.fail_read_at:
                    raise psycopg.OperationalError("synthetic_read_failure")
            if not self.connection.autocommit:
                self.connection.statement_seen = True
            columns, self.rows, self.rowcount = self.connection.store.run(query, params or {})
        self.description = (
            [(column, 25, None, None, None, None, None) for column in columns] if columns else None
        )
        self.pgresult.status = 2 if columns else 1

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows

    def _close(self) -> None:
        pass
