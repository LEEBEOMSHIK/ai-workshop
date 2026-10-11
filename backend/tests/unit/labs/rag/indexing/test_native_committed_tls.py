"""Actual crypto/TLS source binding; only low external transports are fake."""

import asyncio
import importlib.util
import io
from copy import copy, deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_secured_read import NativeSecuredReadSource
from ai_workshop.labs.rag.indexing.alias_models import AliasRecoveryReceiptRecord
from tests.unit.labs.rag.indexing.native_committed_tls_fixture_support import prepare_tls

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.unit.labs.rag.indexing.native_secured_read_graph_support"]


@pytest.fixture
def graph(material_graph: Any) -> Any:
    return material_graph


async def test_actual_tls_recipe_bound_sample_then_reader_availability(graph: Any) -> None:
    recipe = prepare_tls(graph)
    store, assembly, deps, c, material = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    binding = await source.bind_verified(c.claim)
    sample = await source._private_read_bound_sample(binding)
    assert dict(sample.evidence.manifests)["tls_public_ca"] == recipe.manifest_json
    assert len(recipe.fixed_paths) == 7 and store.dml_count == store.commit_count == 0
    for path in recipe.fixed_paths:
        assert deps.private.read_protected(path, limit=262144).data
    assert not material.retained
    assert (
        importlib.util.find_spec("ai_workshop.labs.rag.indexing.access_epoch_committed_tls")
        is not None
    ), "committed_tls_reader_missing"


async def opened(graph: Any) -> tuple[Any, Any, Any, Any]:
    from ai_workshop.labs.rag.indexing.access_epoch_committed_tls import NativeCommittedTlsReader

    recipe = prepare_tls(graph)
    _, assembly, _, c, _ = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, graph[2])
    binding = await source.bind_verified(c.claim)
    reader = await NativeCommittedTlsReader._open_bound_source(source, binding)
    return recipe, source, binding, reader


async def receipt(graph: Any) -> None:
    store, _, _, c, _ = graph
    await c.repository.close_access_epoch(c.claim, c.proof)
    row = next(row for key, row in c.db.rows.items() if key[0] is AliasRecoveryReceiptRecord)
    row.access_epoch_id = UUID(c.epoch.binding.access_epoch_id)
    row.execution_id = UUID(c.epoch.binding.execution_id)
    for rows in store.tables.values():
        rows.clear()
    for record in c.db.rows.values():
        store.seed(record)


async def test_actual_reader_positive_memory_assert_and_close(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    recipe, source, binding, reader = await opened(graph)
    store, assembly, _, c, material = graph
    obs = await reader.observe()
    assert obs.manifest_json == recipe.manifest_json and obs.phase == "verified"
    assert obs.epoch_id == binding.epoch_id and obs.action_id == recipe.action.action_id
    assert obs.original_ipv4 == "172.18.0.2"
    reader.assert_observed(obs)
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        reader.assert_observed(copy(obs))
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        await copy(reader).observe()
    reader.assert_observed(obs)
    assert not material.retained and store.dml_count == store.commit_count == 0

    def no_io(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("memory_assert_performed_io")

    with monkeypatch.context() as low:
        low.setattr(Path, "stat", no_io)
        low.setattr(Path, "read_bytes", no_io)
        low.setattr(io, "open", no_io)
        reader.assert_observed(obs)
        assert reader.close() is None
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        reader.assert_observed(obs)
    source.assert_bound(binding)
    assembly.assert_issued(graph[2])
    assert c.claim and store.dml_count == store.commit_count == 0


async def test_receipted_observation_never_regresses_to_verified(graph: Any) -> None:
    _, _, _, reader = await opened(graph)
    store = graph[0]
    prior = deepcopy(store.tables)
    await receipt(graph)
    obs = await reader.observe()
    assert obs.phase == "receipted"
    reader.assert_observed(obs)
    # Ordinary synthetic relational restore, not an original database mutation.
    store.tables = prior
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        await reader.observe()


@pytest.mark.parametrize("graph", ["receipted"], indirect=True)
async def test_reader_initial_exact_receipted_source(graph: Any) -> None:
    recipe, _, _, reader = await opened(graph)
    obs = await reader.observe()
    assert obs.phase == "receipted" and obs.manifest_json == recipe.manifest_json
    reader.assert_observed(obs)
    reader.close()


@pytest.mark.parametrize("change", ["missing", "pem_changed", "equal_bytes_replaced", "owner"])
async def test_reader_fresh_files_and_owner_cannot_be_reused(graph: Any, change: str) -> None:
    recipe, source, binding, reader = await opened(graph)
    material = graph[4]
    target = material.mapped(recipe.fixed_paths[1])
    assert target is not None
    prior = target.read_bytes()
    if change == "missing":
        target.unlink()
    elif change == "pem_changed":
        target.write_bytes(prior + b"\n")
    elif change == "equal_bytes_replaced":
        replacement = target.with_suffix(".replacement")
        replacement.write_bytes(prior)
        replacement.replace(target)
    else:
        material.owner_valid = False
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        await reader.observe()
    target.write_bytes(prior)
    material.owner_valid = True
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        await reader.observe()
    source.assert_bound(binding)
    assert graph[0].dml_count == graph[0].commit_count == 0 and not material.retained


async def test_reader_cancel_preserves_primary_and_invalidates_only_exact_reader(
    graph: Any,
) -> None:
    _, source, binding, reader = await opened(graph)
    material = graph[4]
    material.cancel_decrypt = True
    with pytest.raises(asyncio.CancelledError):
        await reader.observe()
    material.cancel_decrypt = False
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        await reader.observe()
    source.assert_bound(binding)
    graph[1].assert_issued(graph[2])
    assert not material.retained and graph[0].dml_count == graph[0].commit_count == 0


async def test_reader_cap_primitive_mutation_and_copied_binding_deny(graph: Any) -> None:
    from ai_workshop.labs.rag.indexing.access_epoch_committed_tls import NativeCommittedTlsReader

    _, source, binding, reader = await opened(graph)
    obs = await reader.observe()
    for name, replacement in (
        ("nonce", UUID(int=0)),
        ("epoch_id", copy(obs.epoch_id)),
        ("manifest_json", "{}"),
        ("phase", True),
    ):
        prior = getattr(obs, name)
        if name == "epoch_id":
            replacement = UUID(int=1)
        object.__setattr__(obs, name, replacement)
        with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
            reader.assert_observed(obs)
        object.__setattr__(obs, name, prior)
    reader.assert_observed(obs)
    before = graph[0].readonly_count
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        await NativeCommittedTlsReader._open_bound_source(source, copy(binding))
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        await NativeCommittedTlsReader._open_bound_source(copy(source), binding)
    assert graph[0].readonly_count == before
    reader.assert_observed(obs)
    reader.close()


async def test_reader_mid_actual_sql_binding_mutation_denies(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, binding, reader = await opened(graph)
    store, _, _, _, material = graph
    first_read, run = store.readonly_reads, store.run

    def low_sql(query: str, parameters: dict[str, Any]) -> Any:
        result = run(query, parameters)
        if store.readonly_reads == first_read + 2:
            object.__setattr__(binding, "ordinal", True)
        return result

    monkeypatch.setattr(store, "run", low_sql)
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        await reader.observe()
    assert store.readonly_reads > first_read and store.dml_count == store.commit_count == 0
    assert not material.retained


@pytest.mark.parametrize("fault", ["wrong_target", "wrong_scope", "pem_der_swapped"])
async def test_crypto_correspondence_denies_consistent_committed_but_wrong_tls(
    graph: Any, fault: str
) -> None:
    from ai_workshop.labs.rag.indexing.access_epoch_committed_tls import NativeCommittedTlsReader

    recipe = prepare_tls(graph, fault=fault)
    store, assembly, deps, c, material = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    binding = await source.bind_verified(c.claim)
    sample = await source._private_read_bound_sample(binding)
    assert dict(sample.evidence.manifests)["tls_public_ca"] == recipe.manifest_json
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        await NativeCommittedTlsReader._open_bound_source(source, binding)
    source.assert_bound(binding)
    assert store.dml_count == store.commit_count == 0 and not material.retained


async def test_full_settled_deployment_row_must_equal_evidence_packet(graph: Any) -> None:
    from ai_workshop.labs.rag.indexing.access_epoch_committed_tls import NativeCommittedTlsReader

    recipe = prepare_tls(graph, fault="row_evidence_mismatch")
    store, assembly, deps, c, material = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    binding = await source.bind_verified(c.claim)
    sample = await source._private_read_bound_sample(binding)
    assert dict(sample.evidence.manifests)["tls_public_ca"] == recipe.manifest_json
    row = next(row for row in sample.state.actions if row.action.kind.value == "start_secured")
    assert row.manifest_json != dict(sample.evidence.manifests)["new_deployment"]
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        await NativeCommittedTlsReader._open_bound_source(source, binding)
    assert store.dml_count == store.commit_count == 0 and not material.retained
