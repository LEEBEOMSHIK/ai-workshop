"""Source-private sample uses actual dependency and material issuers."""

from copy import copy, deepcopy
from typing import Any

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_secured_read import NativeSecuredReadSource

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.unit.labs.rag.indexing.native_secured_read_graph_support"]


@pytest.fixture
def graph(material_graph: Any) -> Any:
    return material_graph


async def test_actual_private_bound_verified_sample(graph: Any) -> None:
    store, assembly, deps, c, material = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    cap = await source.bind_verified(c.claim)
    sample = await source._private_read_bound_sample(cap)
    assert sample.evidence == c.evidence and sample.state.phase == "verified"
    assert sample.material and store.dml_count == store.commit_count == 0
    assert not material.retained


@pytest.mark.parametrize("graph", ["receipted"], indirect=True)
async def test_actual_private_bound_receipted_sample(graph: Any) -> None:
    store, assembly, deps, c, material = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    cap = await source.bind_verified(c.claim)
    sample = await source._private_read_bound_sample(cap)
    assert sample.state.phase == "receipted" and sample.evidence == c.evidence
    assert sample.material and not material.retained
    assert store.dml_count == store.commit_count == 0


@pytest.mark.parametrize("change", ["owner", "cipher", "claim"])
async def test_private_bound_sample_is_fresh_and_denies_drift(graph: Any, change: str) -> None:
    store, assembly, deps, c, material = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    cap = await source.bind_verified(c.claim)
    if change == "owner":
        material.owner_valid = False
    elif change == "cipher":
        (material.files / c.epoch.binding.access_epoch_id / "reader.dpapi").write_bytes(b"bad")
    else:
        object.__setattr__(c.claim, "revision", True)
    with pytest.raises(ValueError, match="^secured_read_binding_denied$"):
        await source._private_read_bound_sample(cap)
    assert len(source._issued) == 1 and not material.retained
    assert store.dml_count == store.commit_count == 0


async def test_private_bound_sample_does_not_adopt_component_or_cap_copy(graph: Any) -> None:
    from copy import copy

    store, assembly, deps, c, _ = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    cap = await source.bind_verified(c.claim)
    before = store.readonly_count
    with pytest.raises(ValueError):
        await source._private_read_bound_sample(copy(cap))
    component = NativeSecuredReadSource(deps.settings, deps.repository, deps.store, deps.keys)
    with pytest.raises(ValueError):
        await component._private_read_bound_sample(cap)
    assert store.readonly_count == before


@pytest.mark.parametrize("change", ["copied_source", "foreign_source"])
async def test_bound_sample_source_identity_is_exact(graph: Any, change: str) -> None:
    store, assembly, deps, c, material = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    cap = await source.bind_verified(c.claim)
    other = (
        copy(source)
        if change == "copied_source"
        else NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    )
    before = store.readonly_count
    with pytest.raises(ValueError):
        await other._private_read_bound_sample(cap)
    assert store.readonly_count == before and not material.retained


async def test_mid_actual_sql_binding_drift_denies_without_material_or_dml_change(
    graph: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, assembly, deps, c, material = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    cap = await source.bind_verified(c.claim)
    rows_before = deepcopy(store.tables)
    files_before = {
        file.relative_to(material.files): file.read_bytes()
        for file in material.files.rglob("*.dpapi")
    }
    first_read = store.readonly_reads
    original_run = store.run

    def low_sql(query: str, parameters: dict[str, Any]) -> Any:
        result = original_run(query, parameters)
        if store.readonly_reads == first_read + 2:
            object.__setattr__(cap, "ordinal", True)
        return result

    monkeypatch.setattr(store, "run", low_sql)  # External DBAPI row transport only.
    with pytest.raises(ValueError, match="^secured_read_binding_denied$"):
        await source._private_read_bound_sample(cap)
    assert store.tables == rows_before
    assert {
        file.relative_to(material.files): file.read_bytes()
        for file in material.files.rglob("*.dpapi")
    } == files_before
    assert store.dml_count == store.commit_count == 0 and not material.retained
