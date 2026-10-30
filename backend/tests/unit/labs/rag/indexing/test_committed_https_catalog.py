"""Catalog assembly over actual committed SQL/store/TLS producers, no model or HTTP."""

import importlib
import json
from copy import copy
from typing import Any

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_committed_tls import NativeCommittedTlsReader
from ai_workshop.labs.rag.indexing.access_epoch_secured_read import NativeSecuredReadSource
from tests.unit.labs.rag.indexing.native_committed_https_fixture_support import prepare_https

pytest_plugins = ["tests.unit.labs.rag.indexing.native_secured_read_graph_support"]
pytestmark = pytest.mark.asyncio


@pytest.fixture
def graph(material_graph: Any) -> Any:
    return material_graph


async def opened(graph: Any, *, mismatched_role: str | None = None) -> Any:
    recipe, permissions = prepare_https(graph, mismatched_role=mismatched_role)
    _, assembly, deps, c, _ = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    binding = await source.bind_verified(c.claim)
    reader = await NativeCommittedTlsReader._open_bound_source(source, binding)
    return recipe, permissions, source, binding, reader


def module() -> Any:
    name = "ai_workshop.labs.rag.indexing.access_epoch_committed_https"
    assert importlib.util.find_spec(name) is not None, "committed HTTPS catalog missing"
    return importlib.import_module(name)


@pytest.mark.parametrize("graph", ["verified", "receipted"], indirect=True)
async def test_catalog_uses_current_committed_credentials_and_ledger_policy(graph: Any) -> None:
    recipe, permissions, source, binding, reader = await opened(graph)
    before = graph[0].readonly_reads
    result = await module()._read_committed_https_catalog(source, binding, reader)
    catalog = result.catalog
    assert catalog.epoch_id == binding.epoch_id
    assert catalog.permissions == permissions
    assert catalog.http_ca_pem == recipe.bundle.http.ca_certificate_pem
    assert catalog.http_leaf_sha256 == json.loads(recipe.manifest_json)["http_leaf_der_sha256"]
    sample = await source._private_read_bound_sample(binding)
    for key, (row, envelope) in zip(catalog.keys, sample.credentials, strict=True):
        assert key.key_id == envelope.key_id
        assert key.key_name == f"ai-workshop-{binding.epoch_id}-{key.role}-{row.action.issuance_id}"
        assert key.encoded.get_secret_value() == envelope.secret.get_secret_value()
        assert key.encoded.get_secret_value() not in repr(result)
    assert result.phase == binding.phase
    assert graph[0].readonly_reads > before
    assert graph[0].dml_count == graph[0].commit_count == 0
    assert not graph[4].retained


@pytest.mark.parametrize("role", ["reader", "writer", "collector"])
async def test_ledger_policy_must_equal_persisted_exact_descriptors(graph: Any, role: str) -> None:
    _, _, source, binding, reader = await opened(graph, mismatched_role=role)
    with pytest.raises(ValueError, match="^committed_https_material_denied$"):
        await module()._read_committed_https_catalog(source, binding, reader)


@pytest.mark.parametrize("copy_target", ["source", "binding", "reader"])
async def test_catalog_cannot_adopt_equal_copied_component(graph: Any, copy_target: str) -> None:
    _, _, source, binding, reader = await opened(graph)
    args = dict(source=source, binding=binding, reader=reader)
    args[copy_target] = copy(args[copy_target])
    before = graph[0].readonly_reads, graph[4].opens
    with pytest.raises(ValueError, match="^committed_https_material_denied$"):
        await module()._read_committed_https_catalog(
            args["source"], args["binding"], args["reader"]
        )
    assert before == (graph[0].readonly_reads, graph[4].opens)
