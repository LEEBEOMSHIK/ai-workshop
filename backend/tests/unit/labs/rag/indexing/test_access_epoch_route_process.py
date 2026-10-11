"""Recorded route admission does not accept caller attestations."""

import importlib
from types import SimpleNamespace

import pytest

from tests.unit.labs.rag.indexing.test_access_epoch_bootstrap_retirement import (
    bootstrap_case as _bootstrap_case,
)
from tests.unit.labs.rag.indexing.test_access_epoch_control_native import assembly as _assembly
from tests.unit.labs.rag.indexing.test_access_epoch_control_native import (
    source_case as _source_case,
)

assembly = _assembly
source_case = _source_case

bootstrap_case = _bootstrap_case


def module():
    return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_route_process")


def test_recorded_route_source_module_exists():
    assert module().RecordedNativeRoutes is not None


@pytest.mark.parametrize("position", ["context", "commands"])
async def test_recorded_source_refuses_caller_lookalike(assembly, position):
    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext
    from ai_workshop.labs.rag.indexing.access_epoch_route_commands import NativeRouteCommands

    context = NativeControlContext(**assembly.args)
    commands = NativeRouteCommands(context)
    with pytest.raises(ValueError, match="^native_route_process_unverified$"):
        module().RecordedNativeRoutes(
            SimpleNamespace() if position == "context" else context,
            SimpleNamespace() if position == "commands" else commands,
        )
    assert assembly.db.statements == []


async def test_recorded_source_refuses_commands_from_different_context(assembly):
    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext
    from ai_workshop.labs.rag.indexing.access_epoch_route_commands import NativeRouteCommands

    one, two = (NativeControlContext(**assembly.args) for _ in range(2))
    with pytest.raises(ValueError, match="^native_route_process_unverified$"):
        module().RecordedNativeRoutes(one, NativeRouteCommands(two))
    assert assembly.db.statements == []


@pytest.mark.parametrize(
    "field,value", [("pid", True), ("creation_time", 123), ("job_id", None), ("pid", "1")]
)
def test_protected_capture_cannot_coerce_child_binding(field, value):
    expected = {"child": {"pid": 1, "creation_time": "123", "job_id": "job"}}
    packet = {
        "binding": {"child": {**expected["child"], field: value}},
        "exit_code": 0,
        "stdout": "eA==",
        "stderr": "",
        "captured_at": "2026-10-08T00:00:00.000000+00:00",
    }
    with pytest.raises(ValueError, match="^native_route_process_unverified$"):
        module()._capture_response(packet, expected)


@pytest.mark.parametrize(
    "change", ["missing", "extra", "exit_bool", "exit_failed", "base64_noncanonical", "oversized"]
)
def test_private_capture_is_complete_closed_and_bounded(change):
    import base64

    expected = {"child": {"pid": 1, "creation_time": "123", "job_id": "job"}}
    packet = {
        "binding": expected,
        "exit_code": 0,
        "stdout": "eA==",
        "stderr": "",
        "captured_at": "2026-10-08T00:00:00.000000+00:00",
    }
    if change == "missing":
        del packet["stderr"]
    elif change == "extra":
        packet["caller_fresh"] = True
    elif change == "exit_bool":
        packet["exit_code"] = False
    elif change == "exit_failed":
        packet["exit_code"] = 1
    elif change == "base64_noncanonical":
        packet["stdout"] += "\n"
    else:
        packet["stdout"] = base64.b64encode(b"x" * (1024 * 1024 + 1)).decode()
    with pytest.raises(ValueError, match="^native_route_process_unverified$"):
        module()._capture_response(packet, expected)


def test_private_capture_parser_returns_bytes_without_issued_authority():
    expected = {"child": {"pid": 1, "creation_time": "123", "job_id": "job"}}
    response, sample_at = module()._capture_response(
        {
            "binding": expected,
            "exit_code": 0,
            "stdout": "eA==",
            "stderr": "",
            "captured_at": "2026-10-08T00:00:00.000000+00:00",
        },
        expected,
    )
    assert response.stdout == b"x"
    assert not isinstance(response, module().VerifiedNativeRoutes)
    assert sample_at.isoformat(timespec="microseconds") == "2026-10-08T00:00:00.000000+00:00"


@pytest.mark.parametrize(
    "value", [True, None, "2026-10-08T09:00:00.000000+09:00", "2026-10-08T00:00:00Z", "2026-10-08"]
)
def test_capture_time_is_exact_utc_without_coercion(value):
    expected = {"child": {"pid": 1, "creation_time": "123", "job_id": "job"}}
    packet = {
        "binding": expected,
        "exit_code": 0,
        "stdout": "eA==",
        "stderr": "",
        "captured_at": value,
    }
    with pytest.raises(ValueError, match="^native_route_process_unverified$"):
        module()._capture_response(packet, expected)


async def test_recorded_constructor_is_static_but_support_only_cannot_launch(assembly):
    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext
    from ai_workshop.labs.rag.indexing.access_epoch_route_commands import NativeRouteCommands

    c = NativeControlContext(**assembly.args)
    runner = module().RecordedNativeRoutes(c, NativeRouteCommands(c))
    assert c.epoch is None and c.journal is None
    with pytest.raises(ValueError, match="^native_route_process_unverified$"):
        await runner.observe(SimpleNamespace(kind="verify_access"))
    assert not runner._running and assembly.db.statements == []
    with pytest.raises(ValueError, match="^native_route_process_unverified$"):
        runner.assert_issued(SimpleNamespace())


@pytest.fixture
async def guarded_state_case(assembly, bootstrap_case, monkeypatch):
    """Isolated DB/owner branch, never a route capability or full late context.

    Actual final binding factory, protected journal and held mutex are exercised;
    external SQL/key/store/TLS-read ports are synthetic. The incomplete context
    assembly is explicitly bypassed solely to test parent/state checks.
    """
    from dataclasses import replace
    from uuid import uuid4

    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext
    from ai_workshop.labs.rag.indexing.access_epoch_repository import ActionReadback
    from ai_workshop.labs.rag.indexing.access_epoch_route_commands import NativeRouteCommands
    from ai_workshop.labs.rag.indexing.access_epoch_types import (
        ControlExpectedIdentity,
        CutoverActionKind,
    )
    from tests.unit.labs.rag.indexing.test_access_epoch_final_auth_binding import binding_case

    ports = bootstrap_case
    issued = await binding_case(ports, monkeypatch)
    binding = await issued.factory.create(issued.final)
    last = ports.repo.state.actions[-1]
    action = replace(
        last.action,
        action_id=uuid4(),
        kind=CutoverActionKind.VERIFY_ACCESS,
        sequence=last.event_sequence + 1,
        expected=ControlExpectedIdentity("{}", last.event_sequence),
    )
    ports.repo.state = replace(
        ports.repo.state,
        actions=(
            *ports.repo.state.actions,
            ActionReadback(action, "pending", None, last.observed_at, action.sequence),
        ),
    )
    context = NativeControlContext(**assembly.args)
    context._owner = ports.journal.owner
    context._deployment = ports.builder
    context._final_auth_factory = issued.factory
    monkeypatch.setattr(context, "assert_owned", ports.journal._owned)
    context._retain("final", issued.final)
    commands = NativeRouteCommands(context)
    monkeypatch.setattr(commands, "_runtime", lambda: binding)
    runner = module().RecordedNativeRoutes(context, commands)
    monkeypatch.setattr(runner, "_guard", ports.journal._owned)

    async def revalidate():
        ports.journal._owned()
        return await ports.repo.readback(ports.epoch.binding.claim)

    monkeypatch.setattr(context, "revalidate", revalidate)
    return SimpleNamespace(runner=runner, action=action, ports=ports, issued=issued)


async def test_actual_factory_fresh_guard_accepts_exact_pending_parent_only(guarded_state_case):
    c = guarded_state_case
    assert await c.runner._state(c.action) == c.ports.repo.state
    assert not c.runner._issued


@pytest.mark.parametrize(
    "field,value", [("executor_generation", True), ("kind", "verify_access"), ("sequence", True)]
)
async def test_db_parent_comparison_rejects_caller_coercions(guarded_state_case, field, value):
    from dataclasses import replace

    c = guarded_state_case
    altered = replace(c.action, **{field: value})
    with pytest.raises(ValueError, match="^native_route_process_unverified$"):
        await c.runner._state(altered)


async def test_db_state_change_during_actual_private_binding_read_is_refused(
    guarded_state_case, monkeypatch
):
    from dataclasses import replace

    c = guarded_state_case
    store = c.issued.factory.store
    read = store.read_prepared

    def changed(*args):
        c.ports.repo.state = replace(c.ports.repo.state, phase="credentials_issued")
        return read(*args)

    monkeypatch.setattr(store, "read_prepared", changed)
    with pytest.raises(ValueError):
        await c.runner._state(c.action)
    assert not c.runner._issued


@pytest.mark.parametrize("failure", ["next_create", "catalog_ack", "owner_after_resume", "cancel"])
async def test_recorded_partial_attempt_never_resubmits_or_issues_routes(
    guarded_state_case, monkeypatch, failure
):
    """Actual recorder/journal/kernel-adapter branch with incomplete source guards isolated.

    No successful route authority is fabricated. Only the first raw metadata
    helper can finish; remaining helper uncertainty must poison the attempt.
    """
    import asyncio
    import json

    from ai_workshop.infrastructure.local.control_process_windows import WindowsControlProcess
    from tests.unit.labs.rag.indexing.test_access_epoch_final_auth_process import (
        Kernel as BaseKernel,
    )

    c = guarded_state_case
    context = c.runner.context
    context._epoch = c.ports.epoch
    context._journal = c.ports.journal

    class Files:
        def assert_issued(self, value):
            assert value is c.ports.builder.tls

        def _read(self, path):
            return b"synthetic nonsecret material"

    context._tls = Files()
    context._retain("tls_assets", c.ports.builder.tls)

    class Kernel(BaseKernel):
        def create(self, argv, env, cwd, *, stdin_pipe=False):
            from dataclasses import replace

            child = super().create(argv, env, cwd, stdin_pipe=True)
            return child if stdin_pipe else replace(child, stdin=None)

        def poll(self, process):
            self._call("poll", process)
            return True

    kernel = Kernel([b"{}"] * 27)
    context._native = WindowsControlProcess(native=kernel)
    memory = c.ports.journal.files
    before = kernel.before
    owned = c.runner._guard
    denied = False

    def guard():
        owned()
        if denied:
            raise ValueError("synthetic-owner-loss")

    monkeypatch.setattr(c.runner, "_guard", guard)

    def callback(name):
        nonlocal denied
        if before:
            before(name)
        if name == "create":
            catalog = json.loads(memory.unprotect(memory.read(c.runner._catalog_path(c.action))))
            assert len(catalog["steps"]) == 27
            if failure == "next_create" and kernel.created == 1:
                raise TimeoutError("synthetic native uncertainty")
        if failure == "owner_after_resume" and name == "resume" and kernel.created == 8:
            denied = True
        if failure == "cancel" and name == "poll":
            raise asyncio.CancelledError()

    kernel.before = callback
    if failure == "catalog_ack":
        write = memory.write

        def lost_ack(path, raw):
            write(path, raw)
            if path.endswith(".routes.dpapi"):
                raise OSError("synthetic lost catalog acknowledgement")

        monkeypatch.setattr(memory, "write", lost_ack)
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError):
        await c.runner.observe(c.action)
    created = kernel.created
    with pytest.raises(ValueError, match="^native_route_process_unverified$"):
        await c.runner.observe(c.action)
    assert kernel.created == created and not c.runner._issued
    assert not c.runner._running
    if failure != "owner_after_resume":
        replacement = module().RecordedNativeRoutes(context, c.runner.commands)
        with pytest.raises(ValueError, match="^native_route_process_unverified$"):
            await replacement.observe(c.action)
        assert kernel.created == created
    if failure == "catalog_ack":
        assert created == 0
    elif failure == "owner_after_resume":
        assert not any(call[0] == "private_write" for call in kernel.calls)
        assert created == 8 and ("close", 170) in kernel.calls
    else:
        assert created == 1
        if failure == "cancel":
            assert ("close", 100) in kernel.calls
        else:
            # Capture samples keep their actual terminal timestamp on readback;
            # an altered protected timestamp cannot become a new sample.
            live = module()._LIVE[(context, c.action.action_id)]
            helper = live.plans[0][2]
            path = c.runner._path(c.action, str(helper.action_id) + ".route-output.dpapi")
            capture = json.loads(memory.unprotect(memory.read(path)))
            original_time = capture["captured_at"]
            assert c.runner._read(path)["captured_at"] == original_time
            capture["captured_at"] = "2000-01-01T00:00:00.000000+00:00"
            memory.files[path] = memory.protect(
                json.dumps(capture, sort_keys=True, separators=(",", ":")).encode()
            )
            reached = []
            parse = module()._capture_response

            def parsed(*args):
                reached.append(True)
                return parse(*args)

            monkeypatch.setattr(module(), "_capture_response", parsed)
            with pytest.raises(ValueError):
                await c.runner.observe(c.action)
            assert not reached and kernel.created == created
