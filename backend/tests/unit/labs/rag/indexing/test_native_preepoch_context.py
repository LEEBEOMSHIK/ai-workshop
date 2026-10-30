"""Actual fixed assembly and original issuers; no held context is fabricated."""

from copy import copy
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.infrastructure.local.control_process_windows import (
    NativeWindowsProcess,
    WindowsControlProcess,
)
from ai_workshop.labs.rag.indexing.access_epoch_control_native import (
    ConcreteNativeCutoverControl,
    NativeControlContext,
)
from ai_workshop.labs.rag.indexing.access_epoch_route_commands import NativeRouteCommands
from ai_workshop.labs.rag.indexing.access_epoch_security_descriptor_source import (
    OriginalSecurityDescriptorSource,
)

pytest_plugins = ["tests.unit.labs.rag.indexing.native_preepoch_context_fixture_support"]


async def test_actual_original_namespace_absence_issue_same_assembly_context(
    preepoch_graph: Any,
) -> None:
    graph, context = preepoch_graph, preepoch_graph.context
    assert type(context) is NativeControlContext
    assert context.settings is graph.assembly._settings
    assert context.repository is graph.assembly.control_repository
    assert context.repository.sessions.class_ is AsyncSession
    assert context.repository.sessions is graph.assembly._sessions
    context.assert_sources()
    graph.namespace_source.assert_issued(graph.namespace)
    graph.namespace_source.assert_unmanaged_issued(context.unmanaged)
    assert len(graph.namespace.permissions.namespaces) == 1
    assert graph.store.selected_tables.count("rag_profiles") >= 2
    assert context.epoch is None and context.held_owner is None
    assert context.security_descriptor is None and graph.kernel.created == []
    assert not graph.store.tables["rag_access_epochs"]
    assert not graph.store.tables["rag_access_epoch_executions"]
    assert graph.store.tables == graph.after_construction
    with pytest.raises(ValueError):
        graph.assembly.bind_context(context)
    with pytest.raises(ValueError):
        graph.assembly.bind_context(copy(context))


async def test_actual_prepare_sources_preserves_fixed_pins_without_epoch_acquire(
    preepoch_graph: Any,
) -> None:
    graph, context = preepoch_graph, preepoch_graph.context
    await context.prepare_sources()
    context.assert_preflight_sources()
    descriptor = context.descriptor_source
    assert type(descriptor) is OriginalSecurityDescriptorSource
    assert descriptor.settings is context.settings
    assert descriptor.original is context.original
    descriptor.assert_issued(context.security_descriptor)
    assert type(descriptor.process) is WindowsControlProcess
    assert type(descriptor.process._native) is NativeWindowsProcess
    assert len(graph.kernel.created) == 5 and not graph.kernel.bodies
    assert all(child.state == "closed" for child in descriptor.process._children.values())
    assert type(context.route_commands) is NativeRouteCommands
    context.route_commands.assert_supported()
    assert context.route_commands.context is context
    assert graph.jdk_calls == 1
    assert context.epoch is None and context.held_owner is None
    assert graph.store.tables == graph.after_construction
    assert graph.store.dml_count == graph.before_dml
    assert graph.store.commit_count == graph.before_commit
    assert not graph.store.tables["rag_access_epochs"]
    assert not graph.store.tables["rag_access_epoch_executions"]
    with pytest.raises(ValueError, match="^native_control_unsupported$"):
        ConcreteNativeCutoverControl(context).assert_supported()
