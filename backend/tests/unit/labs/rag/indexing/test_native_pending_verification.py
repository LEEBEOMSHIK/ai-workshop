"""Internal pending producer cannot stand in for complete operational support."""

import importlib
from copy import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

MODULE = "ai_workshop.labs.rag.indexing.access_epoch_pending_verification"
pytest_plugins = ["tests.unit.labs.rag.indexing.native_preepoch_context_fixture_support"]


def pending_module() -> Any:
    assert importlib.util.find_spec(MODULE) is not None, "pending producer is not implemented"
    return importlib.import_module(MODULE)


def test_unissued_context_never_constructs_pending_verifier() -> None:
    pending = pending_module()
    with pytest.raises(ValueError, match="^native_pending_denied$"):
        pending.NativePendingVerification(SimpleNamespace())


def test_pending_producer_has_no_operational_support_entry_point() -> None:
    pending = pending_module()
    assert not hasattr(pending.NativePendingVerification, "assert_supported")
    assert (
        importlib.util.find_spec("ai_workshop.labs.rag.indexing.access_epoch_verification_native")
        is None
    )


def _no_read(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("prepared assertion must not read current state")


async def test_prepared_constructor_and_assertion_read_only_retained_sources(
    preepoch_context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = preepoch_context
    pending = pending_module()
    before = (graph.store.select_count, graph.store.dml_count, len(graph.kernel.created))
    with monkeypatch.context() as blocked:
        blocked.setattr(Path, "open", _no_read)
        blocked.setattr(Path, "read_bytes", _no_read)
        verifier = pending.NativePendingVerification(graph.context)
        assert verifier.context is graph.context
        assert verifier.assert_prepared() is None
    assert (graph.store.select_count, graph.store.dml_count, len(graph.kernel.created)) == before
    assert graph.context._epoch is None and graph.context._owner is None
    assert verifier._routes is None and verifier._issued == {}


async def test_prepared_context_cannot_have_second_pending_producer(preepoch_context: Any) -> None:
    pending = pending_module()
    verifier = pending.NativePendingVerification(preepoch_context.context)
    with pytest.raises(ValueError, match="^native_pending_denied$"):
        pending.NativePendingVerification(preepoch_context.context)
    verifier.assert_prepared()


@pytest.mark.parametrize(
    "fault",
    [
        "copy",
        "registry-missing",
        "commands-copy",
        "route-context",
        "route-context-pin",
        "descriptor-native",
        "original-executor",
        "original-reader",
    ],
)
async def test_prepared_producer_loses_authority_on_source_substitution(
    preepoch_context: Any, fault: str
) -> None:
    pending = pending_module()
    context = preepoch_context.context
    verifier = pending.NativePendingVerification(context)
    if fault == "copy":
        verifier = copy(verifier)
    elif fault == "registry-missing":
        pending._LIVE.pop(context)
    elif fault == "commands-copy":
        object.__setattr__(context._preflight_sources, "commands", copy(verifier._commands))
    elif fault == "route-context":
        verifier._commands._context = object()
    elif fault == "route-context-pin":
        verifier._commands._context_pin = object()
    elif fault == "descriptor-native":
        context._preflight_sources.source.process._native = object()
    elif fault == "original-executor":
        context._original.executor = object()
    else:
        context._original.reader = object()
    with pytest.raises(ValueError, match="^native_pending_denied$"):
        verifier.assert_prepared()


async def test_malformed_parent_is_rejected_without_runtime_reads(
    preepoch_context: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    pending = pending_module()
    graph = preepoch_context
    verifier = pending.NativePendingVerification(graph.context)
    before = (graph.store.select_count, graph.store.dml_count, len(graph.kernel.created))
    with monkeypatch.context() as blocked:
        blocked.setattr(Path, "open", _no_read)
        blocked.setattr(Path, "read_bytes", _no_read)
        for _ in range(2):
            with pytest.raises(ValueError, match="^native_pending_denied$"):
                await verifier.verify(graph.context, SimpleNamespace())
    assert (graph.store.select_count, graph.store.dml_count, len(graph.kernel.created)) == before
    assert verifier._routes is None and verifier._issued == {}
