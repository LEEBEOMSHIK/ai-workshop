"""Real committed producers; only external SQL/private file transport is synthetic."""

import json
from copy import copy, deepcopy
from hashlib import sha256
from typing import Any

import pytest

from tests.unit.labs.rag.indexing.test_native_committed_tls import opened, receipt

pytest_plugins = ["tests.unit.labs.rag.indexing.native_secured_read_graph_support"]
pytestmark = pytest.mark.asyncio


@pytest.fixture
def graph(material_graph: Any) -> Any:
    return material_graph


@pytest.mark.parametrize("graph", ["verified", "receipted"], indirect=True)
async def test_private_sample_retains_actual_loaded_credentials(graph: Any) -> None:
    _, source, binding, _ = await opened(graph)
    before = graph[0].readonly_reads
    sample = await source._private_read_bound_sample(binding)
    assert graph[0].readonly_reads > before
    assert tuple(row.action.role for row, _ in sample.credentials) == (
        "reader",
        "writer",
        "collector",
    )
    for row, envelope in sample.credentials:
        assert row.result.key_id == envelope.key_id
        assert envelope.epoch_id == binding.epoch_id
        assert envelope.role == row.action.role
        assert envelope.secret.get_secret_value() not in repr(sample)
    assert not graph[4].retained
    assert graph[0].dml_count == graph[0].commit_count == 0


@pytest.mark.parametrize("graph", ["verified", "receipted"], indirect=True)
async def test_private_http_material_comes_from_current_protected_tls(graph: Any) -> None:
    recipe, source, binding, reader = await opened(graph)
    before = (graph[0].readonly_reads, graph[4].opens, graph[4].dpapi_reads)
    material = await reader._private_read_http_material(source, binding)
    public = json.loads(recipe.manifest_json)
    assert material.ca_pem == recipe.bundle.http.ca_certificate_pem
    assert sha256(material.ca_pem).hexdigest() == public["http_ca_sha256"]
    assert material.leaf_sha256 == public["http_leaf_der_sha256"]
    assert material.manifest_json == recipe.manifest_json
    assert material.phase == binding.phase
    assert all(
        after > old
        for old, after in zip(
            before, (graph[0].readonly_reads, graph[4].opens, graph[4].dpapi_reads), strict=True
        )
    )
    assert "BEGIN CERTIFICATE" not in repr(material)
    assert not hasattr(material, "private_key")
    assert not graph[4].retained
    assert graph[0].dml_count == graph[0].commit_count == 0


@pytest.mark.parametrize("copy_target", ["source", "binding", "reader"])
async def test_private_http_material_cannot_adopt_copied_owner(
    graph: Any, copy_target: str
) -> None:
    _, source, binding, reader = await opened(graph)
    before = (graph[0].readonly_reads, graph[4].opens)
    args = dict(source=source, binding=binding, reader=reader)
    args[copy_target] = copy(args[copy_target])
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        await args["reader"]._private_read_http_material(args["source"], args["binding"])
    assert before == (graph[0].readonly_reads, graph[4].opens)


async def test_private_http_material_keeps_forward_phase_and_denies_regression(graph: Any) -> None:
    _, source, binding, reader = await opened(graph)
    prior = deepcopy(graph[0].tables)
    await receipt(graph)
    material = await reader._private_read_http_material(source, binding)
    assert material.phase == "receipted"
    graph[0].tables = prior
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        await reader._private_read_http_material(source, binding)


async def test_private_http_material_denied_after_close(graph: Any) -> None:
    _, source, binding, reader = await opened(graph)
    reader.close()
    with pytest.raises(ValueError, match="^committed_tls_read_denied$"):
        await reader._private_read_http_material(source, binding)
