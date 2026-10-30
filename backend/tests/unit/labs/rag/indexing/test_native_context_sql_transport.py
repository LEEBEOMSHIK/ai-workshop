"""Namespace query shape over the actual owned engine and low psycopg fake."""

from collections.abc import AsyncIterator, Awaitable, Callable
from copy import deepcopy
from uuid import UUID

import psycopg
import pytest
from psycopg.types import TypeInfo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
    NativeSecuredReadAssembly,
)
from ai_workshop.labs.rag.models.models import ProfileRecord
from tests.unit.labs.rag.indexing import native_sql_row_transport_support as wire
from tests.unit.labs.rag.indexing.test_access_epoch_secured_read_assembly import missing_hstore

pytest_plugins = ["tests.unit.labs.rag.indexing.test_access_epoch_secured_read_assembly"]
type Graph = tuple[wire.RelationalRows, NativeSecuredReadAssembly]


@pytest.fixture
async def namespace_sql_graph(
    factory: Callable[[], Awaitable[NativeSecuredReadAssembly]],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Graph]:
    store = wire.RelationalRows()
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", store.connect)
    monkeypatch.setattr(TypeInfo, "fetch", missing_hstore)
    # Deliberately unsorted, with the unrelated row first. LIMIT must run after
    # filtering and optional ORDER BY, not slice this seed list first.
    for value, kind in (
        (9, "generation"),
        (3, "indexing"),
        (2, "document_processing"),
        (1, "indexing"),
    ):
        store.seed(ProfileRecord(id=UUID(int=value), kind=kind))
    before = deepcopy(store.tables)
    assembly = await factory()
    assert type(assembly._engine) is AsyncEngine
    assert assembly.control_repository.sessions.class_ is AsyncSession
    assert assembly.control_repository.sessions.kw["bind"] is assembly._engine
    try:
        yield store, assembly
    finally:
        await assembly.close()
        assert all(connection.closed for connection in store.connections)
        assert store.tables == before
        assert store.dml_count == store.commit_count == 0


async def test_actual_namespace_in_limit_returns_only_requested_profiles(
    namespace_sql_graph: Graph,
) -> None:
    store, assembly = namespace_sql_graph
    expected = {UUID(int=2): "document_processing", UUID(int=1): "indexing"}
    # Exact OriginalNamespaceSource._profiles statement, including len + 1.
    statement = (
        select(ProfileRecord.id, ProfileRecord.kind)
        .where(ProfileRecord.id.in_(tuple(expected)))
        .limit(len(expected) + 1)
    )
    async with assembly._engine.connect() as connection:
        rows = (await connection.execute(statement)).all()
    assert {row[0]: row[1] for row in rows} == expected and len(rows) == len(expected)
    assert all(type(row[0]) is UUID and type(row[1]) is str for row in rows)
    assert store.selected_tables == ["rag_profiles"]
    assert store.select_count == 1


async def test_actual_profile_ordering_precedes_bound_limit(namespace_sql_graph: Graph) -> None:
    _, assembly = namespace_sql_graph
    statement = (
        select(ProfileRecord.id, ProfileRecord.kind)
        .where(ProfileRecord.id.in_((UUID(int=3), UUID(int=1), UUID(int=2))))
        .order_by(ProfileRecord.id)
        .limit(2)
    )
    async with assembly._engine.connect() as connection:
        rows = (await connection.execute(statement)).all()
    assert list(rows) == [(UUID(int=1), "indexing"), (UUID(int=2), "document_processing")]


@pytest.mark.parametrize("limit", [0, 1], ids=["zero", "no-match"])
async def test_actual_profile_query_empty_result_respects_limit(
    namespace_sql_graph: Graph, limit: int
) -> None:
    _, assembly = namespace_sql_graph
    wanted = UUID(int=1 if limit == 0 else 100)
    statement = (
        select(ProfileRecord.id, ProfileRecord.kind)
        .where(ProfileRecord.id.in_((wanted,)))
        .limit(limit)
    )
    async with assembly._engine.connect() as connection:
        rows = (await connection.execute(statement)).all()
    assert rows == []


_QUERY = (
    "SELECT rag_profiles.id, rag_profiles.kind FROM rag_profiles "
    "WHERE rag_profiles.id IN (%(id_1_1)s::UUID) LIMIT %(param_1)s::INTEGER"
)


def _seeded_wire() -> wire.RelationalRows:
    store = wire.RelationalRows()
    store.seed(ProfileRecord(id=UUID(int=1), kind="indexing"))
    return store


@pytest.mark.parametrize(
    "limit",
    [-1, True, 1.5, "1", None],
    ids=["negative", "boolean", "fraction", "string", "null"],
)
def test_bound_limit_requires_nonnegative_exact_integer(limit: object) -> None:
    store = _seeded_wire()
    with pytest.raises(AssertionError, match="^synthetic_sql_transport_denied$"):
        store.run(_QUERY, {"id_1_1": UUID(int=1), "param_1": limit})
    assert store.select_count == store.dml_count == store.commit_count == 0


@pytest.mark.parametrize("missing", ["id_1_1", "param_1"], ids=["missing-id", "missing-limit"])
def test_profile_in_query_missing_binding_is_denied(missing: str) -> None:
    store = _seeded_wire()
    values: dict[str, object] = {"id_1_1": UUID(int=1), "param_1": 1}
    values.pop(missing)
    with pytest.raises(AssertionError, match="^synthetic_sql_transport_denied$"):
        store.run(_QUERY, values)
    assert store.select_count == store.dml_count == store.commit_count == 0


@pytest.mark.parametrize(
    "sql",
    [
        _QUERY.replace("rag_profiles.id, rag_profiles.kind", "*"),
        _QUERY.replace("rag_profiles.kind", "rag_profiles.unknown"),
        _QUERY.replace("IN (%(id_1_1)s::UUID)", "IN ()"),
        _QUERY.replace("IN (%(id_1_1)s::UUID)", "IN ('unbound')"),
        _QUERY.replace("WHERE rag_profiles.id", "WHERE users.id"),
        _QUERY.replace(" LIMIT", " ORDER BY users.id LIMIT"),
        _QUERY + "; DELETE FROM rag_profiles",
    ],
    ids=["star", "column", "empty-in", "literal", "foreign-filter", "foreign-order", "multi"],
)
def test_namespace_shape_extension_keeps_unknown_sql_closed(sql: str) -> None:
    store = _seeded_wire()
    with pytest.raises(AssertionError, match="^synthetic_sql_transport_denied$"):
        store.run(sql, {"id_1_1": UUID(int=1), "param_1": 1})
    assert store.select_count == store.dml_count == store.commit_count == 0
