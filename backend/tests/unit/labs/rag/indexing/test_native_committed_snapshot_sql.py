"""Actual maker composite snapshot over finite synthetic SQL/file transport."""

import asyncio
from copy import copy, deepcopy
from typing import Any, cast

import pytest
from sqlalchemy.pool import AsyncAdaptedQueuePool

from ai_workshop.labs.rag.indexing.access_epoch_committed_snapshot import (
    _read_committed_from_dependencies,
    read_committed_snapshot,
)
from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
    NativeReadDependencies,
    NativeSecuredReadAssembly,
)
from tests.unit.labs.rag.indexing import native_sql_row_transport_support as wire

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.unit.labs.rag.indexing.native_secured_read_graph_support"]
type Graph = tuple[wire.RelationalRows, NativeSecuredReadAssembly, NativeReadDependencies, Any]


@pytest.fixture
def graph(sql_graph: Any) -> Any:
    return sql_graph


async def test_actual_owned_maker_verified_snapshot_select_only(graph: Graph) -> None:
    store, assembly, deps, c = graph
    before = deepcopy(store.tables)
    value = await read_committed_snapshot(assembly.control_repository, deps.keys, c.claim)
    assert "rag_profile_model_bindings" not in store.selected_tables
    assert value.evidence == c.evidence
    assert value.state.phase == "verified" and len(value.state.actions) == 12
    assert len(value.completed_keys) == 3
    assert value.floor == c.repository.floor_from_verified(c.evidence)
    assert store.tables == before and store.dml_count == store.commit_count == 0
    assert store.rollback_count > 0
    assembly.assert_issued(deps)


@pytest.mark.parametrize("graph", ["receipted"], indirect=True)
async def test_actual_receipted_snapshot_allows_retired_profiles(graph: Graph) -> None:
    store, assembly, deps, c = graph
    value = await read_committed_snapshot(assembly.control_repository, deps.keys, c.claim)
    assert value.state.phase == "receipted" and value.state.receipt is not None
    assert value.state.receipt.proof == c.proof
    assert not store.tables["rag_profiles"]
    assert store.dml_count == store.commit_count == 0
    assert cast(AsyncAdaptedQueuePool, assembly._engine.pool).checkedout() == 0


@pytest.mark.parametrize("change", ["owner", "gate", "action", "key", "floor", "pending"])
async def test_actual_snapshot_rejects_persisted_truth_drift(graph: Graph, change: str) -> None:
    store, assembly, deps, c = graph
    if change == "owner":
        store.tables["users"][0]["is_active"] = False
    elif change == "gate":
        store.tables["rag_alias_cluster_gates"][0]["revision"] += 1
    elif change == "action":
        store.tables["rag_access_epoch_events"][0]["executor_generation"] = "foreign"
    elif change == "key":
        store.tables["rag_access_epoch_key_events"][0]["role"] = "admin"
    elif change == "floor":
        store.tables["rag_access_epoch_floors"][0]["ordinal"] += 1
    else:
        store.tables["rag_access_epochs"][0]["phase"] = "secured_started"
    before = deepcopy(store.tables)
    with pytest.raises(ValueError, match="^committed_snapshot_denied$"):
        await read_committed_snapshot(assembly.control_repository, deps.keys, c.claim)
    assert store.tables == before and store.dml_count == store.commit_count == 0
    assert store.readonly_count == 1
    assert cast(AsyncAdaptedQueuePool, assembly._engine.pool).checkedout() == 0


@pytest.mark.parametrize("failure", ["read", "cancel", "rollback", "cancel_rollback"])
async def test_actual_snapshot_failure_rolls_back_and_releases_owned_session(
    graph: Graph, failure: str
) -> None:
    store, assembly, deps, c = graph
    before = deepcopy(store.tables)
    if failure in {"cancel", "cancel_rollback"}:
        store.cancel_read_at = 2
    elif failure == "read":
        store.fail_read_at = 2
    store.rollback_failure_once = failure in {"rollback", "cancel_rollback"}
    expected = asyncio.CancelledError if failure.startswith("cancel") else ValueError
    with pytest.raises(expected):
        await read_committed_snapshot(assembly.control_repository, deps.keys, c.claim)
    assert store.tables == before and store.dml_count == store.commit_count == 0
    assert cast(AsyncAdaptedQueuePool, assembly._engine.pool).checkedout() == 0


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT users.id FROM users FOR UPDATE",
        "UPDATE rag_alias_cluster_gates SET state=%(state)s "
        "WHERE rag_alias_cluster_gates.cluster_uuid = %(cluster_uuid)s::VARCHAR",
        "INSERT INTO rag_alias_cluster_gates (cluster_uuid) VALUES (%(cluster_uuid)s::VARCHAR) "
        "ON CONFLICT (cluster_uuid) DO NOTHING",
        "DELETE FROM users",
    ],
)
async def test_readonly_low_connection_refuses_locks_and_mutations(sql: str) -> None:
    store = wire.RelationalRows()
    connection = await store.connect()
    cursor = connection.cursor()
    await cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    with pytest.raises(AssertionError, match="^synthetic_sql_transport_denied$"):
        await cursor.execute(sql, {"state": "admitted", "cluster_uuid": "synthetic"})
    assert store.dml_count == 0
    await connection.rollback()
    await connection.close()
    assert connection.closed


async def test_actual_private_dependency_path_uses_exact_owned_graph(graph: Graph) -> None:
    store, assembly, deps, c = graph
    value = await _read_committed_from_dependencies(assembly, deps, c.claim)
    assert value.evidence == c.evidence and len(value.completed_keys) == 3
    assert "rag_profile_model_bindings" not in store.selected_tables
    assert store.readonly_count == 1 and store.dml_count == store.commit_count == 0
    assembly.assert_issued(deps)


async def test_actual_private_dependency_copy_is_denied_before_connection(graph: Graph) -> None:
    store, assembly, deps, c = graph
    with pytest.raises(ValueError, match="^committed_snapshot_denied$"):
        await _read_committed_from_dependencies(assembly, copy(deps), c.claim)
    assert not store.connections and store.readonly_count == 0
