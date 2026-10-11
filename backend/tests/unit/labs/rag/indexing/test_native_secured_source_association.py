"""Actual fixed assembly association only; no SQL/material/original I/O."""

from copy import copy
from typing import Any

import pytest

import ai_workshop.labs.rag.indexing.access_epoch_secured_read as secured
from ai_workshop.labs.rag.indexing.access_epoch_secured_read import NativeSecuredReadSource

pytest_plugins = ["tests.unit.labs.rag.indexing.test_access_epoch_secured_read_assembly"]


@pytest.mark.asyncio
async def test_actual_committed_graph_is_retained_and_close_consumes(factory: Any) -> None:
    assembly = await factory()
    dependencies = assembly.bind_committed()
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, dependencies)
    source._assert_committed_dependencies()
    assert source._repository is dependencies.repository
    await assembly.close()
    with pytest.raises(ValueError):
        source._assert_committed_dependencies()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "copied_cap",
        "copied_source",
        "copied_guard",
        "transferred_record",
        "foreign_assembly",
        "native",
        "maker",
        "association_lost",
    ],
)
async def test_foreign_copied_or_changed_dependencies_deny(factory: Any, change: str) -> None:
    assembly = await factory()
    dependencies = assembly.bind_committed()
    if change == "copied_cap":
        with pytest.raises(ValueError):
            NativeSecuredReadSource._from_committed_dependencies(assembly, copy(dependencies))
        return
    if change == "foreign_assembly":
        other = await factory()
        with pytest.raises(ValueError):
            NativeSecuredReadSource._from_committed_dependencies(other, dependencies)
        return
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, dependencies)
    if change in {"copied_source", "copied_guard", "transferred_record"}:
        original = source
        source = copy(source)
        if change == "transferred_record":
            secured._ASSOCIATIONS[source] = secured._ASSOCIATIONS[original]
            secured._NATIVE_SOURCES.add(source)
    elif change == "native":
        dependencies.private.owner = "S-1-5-21-other"
    elif change == "association_lost":
        secured._ASSOCIATIONS.pop(source)
    else:
        dependencies.repository.sessions.kw["expire_on_commit"] = True
    with pytest.raises(ValueError):
        if change in {"association_lost", "copied_guard", "transferred_record"}:
            source._guard()
        else:
            source._assert_committed_dependencies()
