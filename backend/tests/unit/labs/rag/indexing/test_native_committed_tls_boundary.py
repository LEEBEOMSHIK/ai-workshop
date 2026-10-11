"""Independent H-only TLS probes; no original transports or candidate edits."""

import asyncio
import importlib
import io
from copy import copy
from typing import Any, BinaryIO

import pytest

from ai_workshop.infrastructure.local.windows_private_state import (
    NativeWindowsPrivateState,
)

pytest_plugins = ["tests.unit.labs.rag.indexing.native_secured_read_graph_support"]
pytestmark = pytest.mark.asyncio
support = importlib.import_module("tests.unit.labs.rag.indexing.test_native_committed_tls")
DENIED = "^committed_tls_read_denied$"


@pytest.fixture
def graph(material_graph: Any) -> Any:
    return material_graph


async def test_associations_and_native_content_before_io(graph: Any, monkeypatch: Any) -> None:
    _, source, binding, reader = await support.opened(graph)
    obs = await reader.observe()
    store, _, deps, _, material = graph
    before = (store.readonly_reads, material.opens, material.dpapi_reads)
    for attribute, replacement in (
        ("_source", copy(source)),
        ("_binding", copy(binding)),
        ("_native", copy(deps.private)),
        ("_root", reader._root + "/other"),
    ):
        prior = getattr(reader, attribute)
        setattr(reader, attribute, replacement)
        with pytest.raises(ValueError, match=DENIED):
            reader.assert_observed(obs)
        setattr(reader, attribute, prior)
    reader.assert_observed(obs)
    assert before == (store.readonly_reads, material.opens, material.dpapi_reads)

    def replacement_require(*args: Any) -> None:
        pass

    with monkeypatch.context() as change:
        change.setattr(NativeWindowsPrivateState._require, "__code__", replacement_require.__code__)
        with pytest.raises(ValueError, match=DENIED):
            await reader.observe()
    assert before == (store.readonly_reads, material.opens, material.dpapi_reads)
    with pytest.raises(ValueError, match=DENIED):
        reader.assert_observed(obs)
    source.assert_bound(binding)
    assert not material.retained and store.dml_count == store.commit_count == 0


@pytest.mark.parametrize("mode", ["cancel_close_error", "close_binding_change"])
async def test_close_boundary_retires_existing_observation(
    graph: Any, monkeypatch: Any, mode: str
) -> None:
    recipe, source, binding, reader = await support.opened(graph)
    obs = await reader.observe()
    original_open = io.open
    closes: list[bool] = []

    class WrappedRead:
        def __init__(self, handle: BinaryIO) -> None:
            self.handle = handle

        def fileno(self) -> int:
            return self.handle.fileno()

        def read(self, size: int) -> bytes:
            if mode == "cancel_close_error":
                raise asyncio.CancelledError()
            return self.handle.read(size)

        def close(self) -> None:
            self.handle.close()
            closes.append(True)
            if mode == "cancel_close_error":
                raise OSError("synthetic_close_failure")
            reader._binding = copy(binding)

    def opened(path: Any, *args: Any, **kwargs: Any) -> Any:
        handle = original_open(path, *args, **kwargs)
        return WrappedRead(handle) if str(path) == recipe.fixed_paths[0] else handle

    with monkeypatch.context() as change:
        change.setattr(io, "open", opened)
        if mode == "cancel_close_error":
            with pytest.raises(asyncio.CancelledError):
                await reader.observe()
        else:
            with pytest.raises(ValueError, match=DENIED):
                await reader.observe()
    reader._binding = binding
    assert closes == [True]
    with pytest.raises(ValueError, match=DENIED):
        reader.assert_observed(obs)
    with pytest.raises(ValueError, match=DENIED):
        await reader.observe()
    source.assert_bound(binding)
    assert not graph[4].retained and graph[0].dml_count == graph[0].commit_count == 0


async def test_memory_assert_rejects_equal_copied_source_settings(graph: Any) -> None:
    _, source, _, reader = await support.opened(graph)
    obs = await reader.observe()
    store, _, _, _, material = graph
    before = (store.readonly_reads, material.opens, material.dpapi_reads)
    prior = source._settings
    source._settings = copy(prior)
    try:
        with pytest.raises(ValueError, match=DENIED):
            reader.assert_observed(obs)
    finally:
        source._settings = prior
    assert before == (store.readonly_reads, material.opens, material.dpapi_reads)


async def test_close_after_association_loss_cannot_restore_old_observation(
    graph: Any,
) -> None:
    _, source, _, reader = await support.opened(graph)
    obs = await reader.observe()
    prior = reader._source
    reader._source = copy(source)
    with pytest.raises(ValueError, match=DENIED):
        reader.close()
    reader._source = prior
    with pytest.raises(ValueError, match=DENIED):
        reader.assert_observed(obs)


async def test_memory_assert_keeps_source_retained_root_and_port_contract(graph: Any) -> None:
    _, source, _, reader = await support.opened(graph)
    obs = await reader.observe()
    for name, replacement in (
        ("_root_text", source._root_text + "/other"),
        ("_ports", (copy(source._ports[0]), source._ports[1])),
    ):
        prior = getattr(source, name)
        setattr(source, name, replacement)
        try:
            with pytest.raises(ValueError):
                type(source)._guard(source)
            with pytest.raises(ValueError, match=DENIED):
                reader.assert_observed(obs)
        finally:
            setattr(source, name, prior)
