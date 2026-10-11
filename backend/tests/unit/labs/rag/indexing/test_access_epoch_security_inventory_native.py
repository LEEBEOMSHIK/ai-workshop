"""Actual source guards and bootstrap composition; external source ports fake."""

import importlib
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from tests.unit.labs.rag.indexing.test_access_epoch_control_native import (
    assembly as _assembly,
)
from tests.unit.labs.rag.indexing.test_access_epoch_control_native import (
    preflight_boundary as _preflight_boundary,
)
from tests.unit.labs.rag.indexing.test_access_epoch_control_native import (
    source_case as _source_case,
)

assembly = _assembly
preflight_boundary = _preflight_boundary
source_case = _source_case


def module() -> Any:
    return importlib.import_module(
        "ai_workshop.labs.rag.indexing.access_epoch_security_inventory_native"
    )


async def prepared(assembly: Any) -> Any:
    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext

    context = NativeControlContext(**assembly.args)
    await context.prepare_sources()
    return context


def parent() -> Any:
    from ai_workshop.labs.rag.indexing.access_epoch_types import (
        ControlExpectedIdentity,
        CutoverActionKind,
        ReservedCutoverAction,
    )

    return ReservedCutoverAction(
        uuid4(),
        uuid4(),
        9,
        CutoverActionKind.STOP_BOOTSTRAP,
        ControlExpectedIdentity("{}", 8),
        "synthetic-generation",
    )


def test_no_lookalike_context() -> None:
    with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
        module().NativeSecurityInventory(SimpleNamespace())


async def test_actual_unprepared_context_has_no_descriptor_authority(assembly: Any) -> None:
    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext

    context = NativeControlContext(**assembly.args)
    with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
        module().NativeSecurityInventory(context)
    assert assembly.db.statements == []


async def test_prepared_constructor_has_no_new_native_or_binary_reads(
    assembly: Any, preflight_boundary: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = await prepared(assembly)
    calls = len(preflight_boundary.calls), len(preflight_boundary.kernel.calls)

    def forbidden() -> str:
        raise AssertionError("constructor must not read binary bytes")

    monkeypatch.setattr(preflight_boundary.routes, "_binary_sha", forbidden)
    issuer = module().NativeSecurityInventory(context)
    assert issuer.context is context
    assert calls == (len(preflight_boundary.calls), len(preflight_boundary.kernel.calls))
    assert context.epoch is None and assembly.db.statements == []


async def test_static_values_are_pure_retained_pins(
    assembly: Any, preflight_boundary: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    issuer = module().NativeSecurityInventory(await prepared(assembly))
    expected = issuer._static_values()

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("primitive pins cannot read local files")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    assert issuer._static_values() == expected
    # The runtime source guard still reads and refuses unavailable inputs.
    with pytest.raises(ValueError):
        issuer._static()


@pytest.mark.parametrize("changed_input", ["file", "environment"])
async def test_pure_pins_do_not_replace_fresh_configuration_guard(
    assembly: Any, preflight_boundary: Any, monkeypatch: pytest.MonkeyPatch, changed_input: str
) -> None:
    import os

    source = assembly.source
    path = source.source.PROJECT_ROOT / ".env"
    original = path.read_bytes()

    def load(**kwargs: Any) -> Any:
        changed = path.read_bytes() != original or os.environ.get("SYNTHETIC_SECURITY_DRIFT")
        return source.settings.model_copy(
            update={"rag_index_store_id": "changed"} if changed else {}, deep=True
        )

    monkeypatch.setattr(source.source, "Settings", load)
    issuer = module().NativeSecurityInventory(await prepared(assembly))
    expected = issuer._static_values()
    if changed_input == "file":
        path.write_bytes(original + b"# synthetic drift\n")
    else:
        monkeypatch.setenv("SYNTHETIC_SECURITY_DRIFT", "1")
    assert issuer._static_values() == expected
    for _ in range(2):
        with pytest.raises(ValueError):
            issuer._static()


@pytest.mark.parametrize("field", ["namespace", "descriptor", "commands"])
async def test_prepared_source_substitution_denied(
    assembly: Any, preflight_boundary: Any, field: str
) -> None:
    context = await prepared(assembly)
    issuer = module().NativeSecurityInventory(context)
    if field == "namespace":
        context._namespace = replace(context.namespace)
    elif field == "descriptor":
        object.__setattr__(
            context._preflight_sources, "descriptor", replace(context.security_descriptor)
        )
    else:
        object.__setattr__(context._preflight_sources, "commands", SimpleNamespace())
    with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
        _ = issuer.context


async def test_no_held_runtime_cannot_issue_and_attempt_is_closed(
    assembly: Any, preflight_boundary: Any
) -> None:
    context = await prepared(assembly)
    issuer, action = module().NativeSecurityInventory(context), parent()
    with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
        await issuer.observe(action, SimpleNamespace(), SimpleNamespace())
    assert str(action.action_id) in issuer._attempted
    assert issuer._issued == {}
    with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
        await issuer.observe(action, SimpleNamespace(), SimpleNamespace())
    assert assembly.db.statements == []


@pytest.mark.parametrize("fault", ["dict", "string_kind", "bool_sequence", "copied_id_type"])
async def test_malformed_parent_never_gets_runtime_authority(
    assembly: Any, preflight_boundary: Any, fault: str
) -> None:
    context = await prepared(assembly)
    issuer, action = module().NativeSecurityInventory(context), parent()
    if fault == "dict":
        action = {"action_id": str(action.action_id)}
    elif fault == "string_kind":
        action = replace(action, kind="stop_bootstrap")
    elif fault == "bool_sequence":
        action = replace(action, sequence=True)
    else:
        action = replace(action, action_id=str(action.action_id))
    with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
        await issuer.observe(action, SimpleNamespace(), SimpleNamespace())
    assert issuer._issued == {} and assembly.db.statements == []


async def test_capability_constructor_is_not_authority(
    assembly: Any, preflight_boundary: Any
) -> None:
    issuer = module().NativeSecurityInventory(await prepared(assembly))
    with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
        issuer.assert_issued(SimpleNamespace())


async def test_copied_issuer_cannot_inherit_source_identity(
    assembly: Any, preflight_boundary: Any
) -> None:
    from copy import copy

    issuer = module().NativeSecurityInventory(await prepared(assembly))
    copied = copy(issuer)
    with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
        _ = copied.context


async def test_cancelled_support_recheck_poison_preserves_primary(
    assembly: Any, preflight_boundary: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from ai_workshop.labs.rag.indexing.access_epoch_inventory_collection import (
        CapturedPhysicalInventory,
        RecordedInventoryCollector,
    )

    issuer = module().NativeSecurityInventory(await prepared(assembly))
    action = parent()
    # These unissued instances exercise only a refusal before any runtime access.
    collector = object.__new__(RecordedInventoryCollector)
    physical = object.__new__(CapturedPhysicalInventory)
    reads: list[int] = []

    def interrupted() -> str:
        reads.append(1)
        raise asyncio.CancelledError()

    monkeypatch.setattr(preflight_boundary.routes, "_binary_sha", interrupted)
    with pytest.raises(asyncio.CancelledError):
        await issuer.observe(action, collector, physical)
    with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
        await issuer.observe(action, collector, physical)
    assert len(reads) == 1 and issuer._issued == {} and assembly.db.statements == []


@pytest.mark.parametrize(
    "fault", [None, "missing_unmanaged", "overlap", "bool_docs", "extra_system"]
)
async def test_complete_private_category_join_is_structural_only(
    assembly: Any, preflight_boundary: Any, fault: str | None
) -> None:
    from ai_workshop.labs.rag.indexing.access_epoch_index_inventory import _canonical
    from tests.unit.labs.rag.indexing import test_access_epoch_foreign_inventory as foreign
    from tests.unit.labs.rag.indexing import test_access_epoch_index_inventory as rag
    from tests.unit.labs.rag.indexing import test_access_epoch_security_inventory as wire

    context = await prepared(assembly)
    issuer = module().NativeSecurityInventory(context)
    state, stats, _ = wire.sample()
    state["metadata"]["indices"][wire.NAME]["settings"].update(
        {"index.creation_date": "1700000000000", "index.version.created": "9050299"}
    )
    unmanaged: tuple[str, ...] = (rag.LEGACY_NAME,)
    managed: tuple[str, ...] = ()
    if fault == "missing_unmanaged":
        unmanaged = ()
    elif fault == "overlap":
        managed = unmanaged
    elif fault == "bool_docs":
        stats["nodes"][foreign.NODE]["indices"]["indices"][wire.NAME]["docs"]["count"] = True
    elif fault == "extra_system":
        state["metadata"]["indices"][foreign.FOREIGN]["system"] = True
    args = (
        _canonical(state),
        _canonical(stats),
        foreign.CLUSTER,
        "original",
        foreign.NODE,
        context.security_descriptor,
        managed,
        unmanaged,
    )
    if fault:
        with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
            module()._decode_categories(*args)
    else:
        opaque, main = module()._decode_categories(*args)
        assert len(opaque.entries) == 2 and main.count == 8
        assert opaque.private_physical_inventory == main.private_physical_inventory
        assert issuer._issued == {}  # Pure decoding cannot publish a capability.


@pytest.mark.parametrize("fault", [None, "count", "private_metadata", "missing", "bool_count"])
def test_ordinary_foreign_tuple_check_is_not_a_reduced_dto_comparator(fault: str | None) -> None:
    from ai_workshop.labs.rag.indexing.access_epoch_foreign_inventory import (
        decode_foreign_inventory,
    )
    from ai_workshop.labs.rag.indexing.access_epoch_index_inventory import _canonical
    from tests.unit.labs.rag.indexing import test_access_epoch_foreign_inventory as wire

    state, stats = wire.fixtures()
    original = decode_foreign_inventory(
        _canonical(state),
        _canonical(stats),
        cluster_uuid=wire.CLUSTER,
        cluster_name="original",
        stable_node_id=wire.NODE,
        foreign_names=(wire.FOREIGN,),
    )
    # A different complete physical map is checked by the separate whole-map
    # transition, not hidden by manufacturing a DTO for the generic comparator.
    after = replace(original, private_physical_inventory=b"different full map")
    if fault == "count":
        entry = after.entries[0]
        after = replace(
            after, entries=(replace(entry, observation=replace(entry.observation, count=8)),)
        )
    elif fault == "private_metadata":
        after = replace(after, entries=(replace(after.entries[0], private_metadata=b"changed"),))
    elif fault == "missing":
        after = replace(after, entries=())
    elif fault == "bool_count":
        entry = after.entries[0]
        after = replace(
            after, entries=(replace(entry, observation=replace(entry.observation, count=True)),)
        )
    if fault:
        with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
            module()._same_foreign_entries(original, after)
    else:
        assert module()._same_foreign_entries(original, after) is None


async def test_actual_bootstrap_completion_preserves_issued_inventory_origins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from tests.unit.labs.rag.indexing.access_epoch_native_fixture import build_native_fixture

    fixture = await build_native_fixture(monkeypatch, tmp_path)
    try:
        await fixture.prepare_history_and_apps(monkeypatch)
        await fixture.capture_original()
        await fixture.retire_original_and_prepare_tls()
        await fixture.start_bootstrap()
        await fixture.prepare_bootstrap_security_and_keys()
        action, collector, physical = await fixture.capture_bootstrap()
        context = fixture.context
        issuer = context.security_inventory_issuer
        assert issuer is not None
        native_before = len(fixture.kernel.calls)
        cap = await issuer.observe(action, collector, physical)
        issuer.assert_issued(cap)
        completed = await collector.complete_secure(action, physical, issuer, cap)
        assert collector.assert_issued(completed) is None
        assert len(fixture.kernel.calls) == native_before
        assert cap.original is context.original_inventory
        assert completed.physical is physical and completed.foreign is cap.foreign

        def rejected() -> None:
            with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
                issuer.assert_issued(cap)

        original = cap.original
        assert original.physical is not None
        original_physical = original.physical
        object.__setattr__(original, "physical", replace(original_physical))
        rejected()
        object.__setattr__(original, "physical", original_physical)

        namespace_source = original_physical.namespace_source
        object.__setattr__(original_physical, "namespace_source", SimpleNamespace())
        rejected()
        object.__setattr__(original_physical, "namespace_source", namespace_source)

        nonce = original_physical.nonce
        object.__setattr__(original_physical, "nonce", str(nonce))
        rejected()
        object.__setattr__(original_physical, "nonce", nonce)

        row = original_physical.rag_entries[0].observation
        count = row.count
        object.__setattr__(row, "count", True)
        rejected()
        object.__setattr__(row, "count", count)

        origin = cap.source_origin
        object.__setattr__(cap, "source_origin", replace(origin))
        rejected()
        object.__setattr__(cap, "source_origin", origin)

        objects = origin.objects
        object.__setattr__(origin, "objects", (*objects, SimpleNamespace()))
        rejected()
        object.__setattr__(origin, "objects", objects)
        issuer.assert_issued(cap)
        assert collector.assert_issued(completed) is None
        assert len(fixture.kernel.calls) == native_before
    finally:
        fixture.close()


async def test_actual_objects_use_once_locals_and_refuse_late_nested_switches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    import inspect
    from copy import copy

    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext
    from tests.unit.labs.rag.indexing.access_epoch_native_fixture import build_native_fixture

    fixture = await build_native_fixture(monkeypatch, tmp_path)
    try:
        await fixture.prepare_history_and_apps(monkeypatch)
        await fixture.capture_original()
        await fixture.retire_original_and_prepare_tls()
        await fixture.start_bootstrap()
        await fixture.prepare_bootstrap_security_and_keys()
        _, boot_collector, _ = await fixture.capture_bootstrap()
        c = fixture.context
        issuer = c.security_inventory_issuer
        assert issuer is not None
        uncaught_values: list[str] = []
        common = (
            "security_inventory_issuer",
            "epoch",
            "held_owner",
            "repository",
            "journal",
            "native",
            "namespace_source",
            "namespace",
            "security_source",
            "administrator",
            "apps",
            "bootstrap_commands",
            "audits",
            "bootstrap_factory",
            "deployment",
            "history",
            "keys",
            "tls",
            "store",
            "app_retirement",
            "history_ticket",
            "credential",
            "admin_security",
            "historical_security",
            "tls_assets",
            "original_inventory",
            "original_inventory_issuer",
        )

        def check(phase: str, collector: Any) -> None:
            names = common + (
                ("bootstrap", "bootstrap_inventory_issuer")
                if phase == "bootstrap"
                else (
                    "final",
                    "final_inventory_issuer",
                    "final_auth_factory",
                    "final_authentication",
                    "final_auth",
                    "bootstrap_inventory",
                    "bootstrap_inventory_issuer",
                )
            )
            calls = dict.fromkeys(names, 0)
            with monkeypatch.context() as patch:
                for name in names:
                    getter = getattr(NativeControlContext, name).fget

                    def read(self: Any, getter: Any = getter, name: str = name) -> Any:
                        frame = inspect.currentframe()
                        assert frame is not None and frame.f_back is not None
                        caller = frame.f_back
                        if (
                            self is c
                            and caller.f_code.co_name == "_objects"
                            and caller.f_locals.get("phase") == phase
                        ):
                            calls[name] += 1
                        return getter(self)

                    patch.setattr(NativeControlContext, name, property(read))
                before = issuer._objects(phase, collector)
                first_calls = dict(calls)
                assert first_calls == dict.fromkeys(names, 1)
                factory, reader = collector.reader.factory, collector.reader
                targets = {
                    "administrator_repository": (c._administrator, "repository"),
                    "audits_factory": (c._audits, "factory"),
                    "key_parent": (c._keys, "parent"),
                    "factory_repository": (factory, "repository"),
                    "secure_sources": (factory, "_sources"),
                    "reader_binding": (reader, "binding"),
                    "reader_native": (reader, "native"),
                }
                if phase == "final":
                    targets.update(
                        {
                            "auth_repository": (c._final_authentication, "repository"),
                            "auth_factory": (c._final_authentication, "factory"),
                            "final_factory_keys": (c._final_auth_factory, "keys"),
                        }
                    )
                values = {
                    "original_nodes": (c._caps["original_inventory"], "nodes_bytes"),
                }
                if phase == "final":
                    assert c._final_authentication is not None
                    values.update(
                        {
                            "prior_nodes": (c._caps["bootstrap_inventory"], "nodes_bytes"),
                            "final_auth_manifest": (c._caps["final_auth"], "manifest_json"),
                            "final_binding_nonce": (c._final_authentication.binding, "nonce"),
                        }
                    )
                point = c._collectors["original" if phase == "bootstrap" else "bootstrap"]
                original = point.assert_issued
                fault = "administrator_repository"

                def checked_then_switch(cap: Any) -> None:
                    original(cap)
                    frame = inspect.currentframe()
                    assert frame is not None and frame.f_back is not None
                    caller = frame.f_back
                    if caller.f_code.co_name != "_objects" or caller.f_locals.get("phase") != phase:
                        return
                    if fault == "no_change":
                        return
                    if fault in values:
                        receiver, name = values[fault]
                        old = getattr(receiver, name)
                        changed = (
                            str(old)
                            if fault == "final_binding_nonce"
                            else old + (b"\n" if type(old) is bytes else " ")
                        )
                        object.__setattr__(receiver, name, changed)
                        return
                    if fault in targets:
                        receiver, name = targets[fault]
                        setattr(receiver, name, copy(getattr(receiver, name)))
                    elif fault == "collector":
                        c._collectors[phase] = copy(collector)
                    else:
                        c._caps[fault] = copy(c._caps[fault])

                patch.setattr(point, "assert_issued", checked_then_switch)
                cap_names = (
                    ("admin_security", "tls_assets")
                    if phase == "bootstrap"
                    else (
                        "final_auth",
                        "bootstrap_inventory",
                    )
                )
                created = fixture.kernel.created
                for fault in (*targets, "collector", *cap_names):
                    if fault in targets:
                        receiver, name = targets[fault]
                        retained = getattr(receiver, name)
                    else:
                        retained = collector if fault == "collector" else c._caps[fault]
                    try:
                        with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
                            issuer._objects(phase, collector)
                    finally:
                        if fault in targets:
                            receiver, name = targets[fault]
                            setattr(receiver, name, retained)
                        elif fault == "collector":
                            c._collectors[phase] = retained
                        else:
                            c._caps[fault] = retained
                for fault, (receiver, name) in values.items():
                    retained = getattr(receiver, name)
                    try:
                        issuer._objects(phase, collector)
                    except ValueError as error:
                        assert str(error) == "security_inventory_native_denied"
                    else:
                        uncaught_values.append(f"{phase}:{fault}")
                    finally:
                        object.__setattr__(receiver, name, retained)
                assert fixture.kernel.created == created
                fault = "no_change"
                assert all(
                    a is b for a, b in zip(before, issuer._objects(phase, collector), strict=True)
                )

        check("bootstrap", boot_collector)
        await fixture.complete_bootstrap()
        await fixture.retire_bootstrap()
        await fixture.start_final()
        await fixture.prepare_final_auth()
        _, final_collector, _ = await fixture.capture_final()
        await fixture.complete_final()
        check("final", final_collector)
        assert uncaught_values == []
    finally:
        fixture.close()


def test_primitive_seal_still_refuses_opaque_objects() -> None:
    with pytest.raises(ValueError, match="^security_inventory_native_denied$"):
        module()._seal(SimpleNamespace())
