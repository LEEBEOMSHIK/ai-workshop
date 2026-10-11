"""Final auth uses six recorded fake-kernel Jobs and protected RAM captures."""

import asyncio
import base64
import importlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr

from ai_workshop.infrastructure.local.control_process_windows import (
    NativeChild,
    WindowsControlProcess,
)
from ai_workshop.labs.rag.indexing.access_epoch_final_auth import FinalAuthCommands
from ai_workshop.labs.rag.indexing.access_epoch_repository import ActionReadback
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ReservedCutoverAction,
    canonical_json,
)
from tests.unit.labs.rag.indexing import test_access_epoch_final_auth as auth
from tests.unit.labs.rag.indexing.test_access_epoch_bootstrap_retirement import (
    bootstrap_case,  # noqa: F401
)
from tests.unit.labs.rag.indexing.test_access_epoch_final_auth_binding import binding_case


def module():
    return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_final_auth_process")


class Kernel:
    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []
        self.buffers = {}
        self.before = None
        self.created = 0
        self.closed = set()

    def _call(self, name, *values):
        self.calls.append((name, *values))
        if self.before:
            self.before(name)

    def thread_id(self):
        return 9

    def create(self, argv, env, cwd, *, stdin_pipe=False):
        self._call("create", argv, env)
        assert stdin_pipe
        base = 100 + 10 * self.created
        self.buffers[base + 3] = bytearray(self.outputs[self.created])
        self.buffers[base + 4] = bytearray()
        self.created += 1
        return NativeChild(
            base,
            base + 1,
            base + 2,
            base + 3,
            base + 4,
            4000 + self.created,
            str(133700000000000000 + self.created),
            base + 5,
        )

    def resume(self, thread):
        self._call("resume", thread)
        return 1

    def read(self, pipe, limit):
        part = bytes(self.buffers[pipe][:limit])
        del self.buffers[pipe][:limit]
        return part

    def write(self, pipe, data):
        self._call("private_write", pipe, len(data))
        return len(data)

    def poll(self, process):
        self._call("poll", process)
        return process + 5 in self.closed

    def active_processes(self, job):
        return 0

    def exit_code(self, process):
        return 0

    def close(self, handle):
        self._call("close", handle)
        self.closed.add(handle)


@pytest.fixture
async def case(bootstrap_case, monkeypatch):  # noqa: F811
    c = bootstrap_case
    m = module()
    b = await binding_case(c, monkeypatch)
    for role, envelope in b.envelopes.items():
        b.envelopes[role] = replace(
            envelope,
            secret=SecretStr(
                base64.b64encode((envelope.key_id + ":synthetic-private-" + role).encode()).decode()
            ),
        )
    binding = await b.factory.create(b.final)
    monkeypatch.setattr(m, "PROJECT_ROOT", c.journal.root)
    # Synthetic bytes are not evidence until the owned helper's private capture.
    fixture = SimpleNamespace(
        binding=binding, builder=FinalAuthCommands(binding, b.factory), m=auth.module()
    )
    outputs = []
    for role in ("reader", "writer", "collector"):
        command = fixture.builder.authenticate(role)
        raw = auth.response(fixture, auth.auth_value(fixture, role))
        observed = fixture.builder.decode_authenticated(command, raw)
        command = fixture.builder.privileges(observed)
        outputs.extend(
            [raw.stdout, auth.response(fixture, auth.privilege_value(fixture, command)).stdout]
        )
    kernel = Kernel(outputs)
    native = WindowsControlProcess(native=kernel)

    def make(**changes):
        args = dict(
            factory=b.factory,
            binding=binding,
            deployment=c.builder,
            final=b.final,
            repository=c.repo,
            journal=c.journal,
            native=native,
        )
        args.update(changes)
        return m.RecordedFinalAuthentication(**args)

    return SimpleNamespace(
        base=c,
        factory=b.factory,
        binding=binding,
        final=b.final,
        repo=c.repo,
        journal=c.journal,
        memory=c.journal.files,
        kernel=kernel,
        native=native,
        make=make,
        runner=make(),
    )


async def reserve(c):
    ticket = await c.runner.prepare()
    action = ReservedCutoverAction(
        uuid4(),
        ticket.execution_id,
        ticket.sequence,
        ticket.kind,
        ticket.expected,
        ticket.executor_generation,
    )
    c.repo.state = replace(
        c.repo.state,
        actions=(
            *c.repo.state.actions,
            ActionReadback(
                action, "pending", None, c.repo.state.actions[-1].observed_at, action.sequence
            ),
        ),
    )
    return action, ticket


def packet(c, path):
    return json.loads(c.memory.unprotect(c.memory.files[str(path)]))


async def test_six_native_jobs_intent_before_launch_and_private_capture_before_settlement(
    case, monkeypatch
):
    c = case
    action, ticket = await reserve(c)
    monkeypatch.setenv("SYNTHETIC_PRIVATE_CREDENTIAL", "never-forward")

    def check(name):
        if name == "create":
            catalog = packet(c, c.runner._catalog_path(action))
            assert len(catalog["steps"]) == 6
            assert any(
                packet(c, path).get("state") == "intent"
                for path in c.memory.files
                if path.endswith(".dpapi") and "final-auth" not in Path(path).name
            )

    c.kernel.before = check
    observed = await c.runner.run(action, ticket)
    assert c.runner.assert_issued(observed) is None
    assert c.kernel.created == 6
    assert len([x for x in c.kernel.calls if x[0] == "resume"]) == 6
    assert len([x for x in c.kernel.calls if x[0] == "private_write"]) >= 6
    assert all(
        "SYNTHETIC_PRIVATE_CREDENTIAL" not in x[2] for x in c.kernel.calls if x[0] == "create"
    )
    assert c.repo.state.actions[-1].outcome == "pending"
    catalog = packet(c, c.runner._catalog_path(action))
    assert all(step["complete"] is True for step in catalog["steps"])
    assert len(c.memory.files) == 13
    for key in c.binding.keys:
        assert key.encoded.get_secret_value() not in observed.manifest_json
    assert "Authorization" not in observed.manifest_json
    with pytest.raises(ValueError):
        c.runner.assert_issued(replace(observed))
    before_calls, before_files = list(c.kernel.calls), dict(c.memory.files)
    c.repo.state = replace(
        c.repo.state,
        actions=(
            *c.repo.state.actions[:-1],
            replace(
                c.repo.state.actions[-1], outcome="unknown", event_sequence=action.sequence + 1
            ),
        ),
    )
    recovered = await c.make().run(action)
    assert recovered.manifest_json == observed.manifest_json
    assert c.kernel.calls == before_calls and c.memory.files == before_files


@pytest.mark.parametrize(
    "change",
    [
        "fake_factory",
        "copy_binding",
        "other_repository",
        "other_journal",
        "copy_final",
        "wrong_root",
    ],
)
async def test_only_concrete_factory_and_exact_composed_dependencies(case, change):
    c = case
    args = {}
    if change == "fake_factory":
        args["factory"] = SimpleNamespace(assert_issued=lambda x: None)
    elif change == "copy_binding":
        args["binding"] = replace(c.binding)
    elif change == "other_repository":
        args["repository"] = SimpleNamespace(readback=lambda x: c.repo.state)
    elif change == "other_journal":
        args["journal"] = SimpleNamespace(owner=c.journal.owner)
    elif change == "copy_final":
        args["final"] = replace(c.final)
    else:
        c.journal.root = c.journal.root / "wrong"
    with pytest.raises(ValueError, match="final_auth_process_denied"):
        c.make(**args)
    assert c.kernel.calls == []


@pytest.mark.parametrize(
    "change",
    [
        "uncommitted",
        "previous_pending",
        "wrong_generation",
        "wrong_claim",
        "wrong_order",
        "bool_sequence",
        "bool_preceding",
        "unknown_fresh",
        "copied_ticket",
    ],
)
async def test_fresh_parent_and_all_settled_preceding_actions_before_any_io(case, change):
    c = case
    action, ticket = await reserve(c)
    rows = list(c.repo.state.actions)
    if change == "uncommitted":
        rows.pop()
    elif change == "previous_pending":
        rows[0] = replace(rows[0], outcome="pending")
    elif change == "wrong_generation":
        c.repo.state = replace(c.repo.state, executor_generation=str(uuid4()))
    elif change == "wrong_claim":
        c.repo.state = replace(c.repo.state, prepared=None)
    elif change == "wrong_order":
        rows[0], rows[1] = rows[1], rows[0]
    elif change == "bool_sequence":
        rows[0] = replace(rows[0], action=replace(rows[0].action, sequence=True))
    elif change == "bool_preceding":
        action = replace(action, expected=replace(action.expected, preceding_sequence=False))
        rows[-1] = replace(rows[-1], action=action)
    elif change == "unknown_fresh":
        rows[-1] = replace(rows[-1], outcome="unknown", event_sequence=action.sequence + 1)
    else:
        ticket = replace(ticket)
    c.repo.state = replace(c.repo.state, actions=tuple(rows))
    with pytest.raises(ValueError):
        await c.runner.run(action, ticket)
    assert c.kernel.calls == [] and c.memory.files == {}


@pytest.mark.parametrize(
    "failure",
    [
        "resume_ack",
        "owner_after_resume",
        "db_after_resume",
        "wait_failure",
        "cancel",
        "invalid_http",
        "wrong_child",
    ],
)
async def test_unknown_first_helper_blocks_all_further_helpers_and_replay(case, failure, request):
    c = case
    action, ticket = await reserve(c)
    owned = c.journal.lock.assert_owned
    request.addfinalizer(lambda: setattr(c.journal.lock, "assert_owned", owned))

    def lost_owner(token):
        raise ValueError("synthetic-owner-loss")

    def fault(name):
        if name == "resume":
            if failure == "resume_ack":
                raise OSError("private-ack")
            if failure == "owner_after_resume":
                c.journal.lock.assert_owned = lost_owner
            if failure == "db_after_resume":
                c.repo.state = replace(c.repo.state, gate_state="open")
            if failure == "cancel":
                raise asyncio.CancelledError()
        if name == "poll" and failure == "wait_failure":
            raise TimeoutError("private")

    c.kernel.before = fault
    if failure == "invalid_http":
        c.kernel.outputs[0] = b'{"error":"private"}\n401'
    if failure == "wrong_child":
        original = c.native.wait

        def wait(token, timeout):
            result = original(token, timeout)
            return replace(result, child=replace(result.child, pid=result.child.pid + 1))

        c.native.wait = wait
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError):
        await c.runner.run(action, ticket)
    assert c.kernel.created == 1
    if failure in {"resume_ack", "owner_after_resume", "db_after_resume", "cancel"}:
        assert not any(x[0] == "private_write" for x in c.kernel.calls)
    calls = list(c.kernel.calls)
    c.kernel.before = None
    with pytest.raises(ValueError):
        await c.runner.run(action)
    with pytest.raises(ValueError):
        await c.runner.run(action, ticket)
    assert c.kernel.calls == calls


@pytest.mark.parametrize(
    "change",
    [
        "missing_capture",
        "wrong_child",
        "wrong_role",
        "wrong_parent",
        "bad_response",
        "unknown_journal",
        "missing_catalog",
        "partial_catalog",
    ],
)
async def test_recovery_requires_all_six_exact_protected_native_captures(case, change):
    c = case
    action, ticket = await reserve(c)
    await c.runner.run(action, ticket)
    path = c.runner._catalog_path(action)
    catalog = packet(c, path)
    step = catalog["steps"][3]
    output_path = c.runner._output_path(action, step["action_id"])
    if change == "missing_capture":
        del c.memory.files[output_path]
    elif change == "missing_catalog":
        del c.memory.files[path]
    elif change == "partial_catalog":
        catalog["steps"][3]["complete"] = False
        c.memory.files[path] = c.memory.protect(canonical_json(catalog).encode())
    elif change == "unknown_journal":
        journal_path = str(
            c.journal.root
            / ".local-data/access-epoch/private/control"
            / str(action.execution_id)
            / (step["action_id"] + ".dpapi")
        )
        value = packet(c, journal_path)
        value["state"] = "unknown"
        value["exit_code"] = None
        c.memory.files[journal_path] = c.memory.protect(canonical_json(value).encode())
    else:
        value = packet(c, output_path)
        if change == "wrong_child":
            value["binding"]["child"]["pid"] += 1
        elif change == "wrong_role":
            value["binding"]["role"] = "reader"
        elif change == "wrong_parent":
            value["binding"]["parent_action_id"] = str(uuid4())
        else:
            value["stdout"] = base64.b64encode(b"{}\n200").decode()
        c.memory.files[output_path] = c.memory.protect(canonical_json(value).encode())
    calls = list(c.kernel.calls)
    with pytest.raises(ValueError):
        await c.make().run(action)
    assert c.kernel.calls == calls


@pytest.mark.parametrize("stage", ["catalog", "capture", "last_complete"])
async def test_lost_write_ack_is_nonreplayable_but_full_completion_can_recover(case, stage):
    c = case
    action, ticket = await reserve(c)
    original = c.memory.write

    def write(path, content):
        original(path, content)
        value = json.loads(c.memory.unprotect(content))
        if stage == "catalog" and path == c.runner._catalog_path(action):
            raise OSError("private")
        if stage == "capture" and "stdout" in value:
            raise OSError("private")
        if (
            stage == "last_complete"
            and "steps" in value
            and all(x["complete"] for x in value["steps"])
        ):
            raise OSError("private")

    c.memory.write = write
    with pytest.raises(ValueError):
        await c.runner.run(action, ticket)
    c.memory.write = original
    calls = list(c.kernel.calls)
    if stage == "last_complete":
        assert (await c.make().run(action)).container_id == c.binding.container_id
    else:
        with pytest.raises(ValueError):
            await c.make().run(action)
    assert c.kernel.calls == calls


async def test_new_binding_nonce_cannot_replace_original_capture_authority(case):
    c = case
    action, ticket = await reserve(c)
    await c.runner.run(action, ticket)
    binding = await c.factory.create(c.final)
    assert binding.nonce != c.binding.nonce
    calls = list(c.kernel.calls)
    with pytest.raises(ValueError):
        await c.make(binding=binding).run(action)
    assert c.kernel.calls == calls


async def test_owner_loss_inside_protection_blocks_catalog_write_and_native(case, request):
    c = case
    action, ticket = await reserve(c)
    protect = c.memory.protect
    owned = c.journal.lock.assert_owned
    request.addfinalizer(lambda: setattr(c.journal.lock, "assert_owned", owned))

    def lost_owner(token):
        raise ValueError("synthetic-owner-loss")

    def lose(payload):
        encrypted = protect(payload)
        c.journal.lock.assert_owned = lost_owner
        return encrypted

    c.memory.protect = lose
    with pytest.raises(ValueError):
        await c.runner.run(action, ticket)
    assert c.memory.files == {} and c.kernel.calls == []


@pytest.mark.parametrize("failure", ["close_ack", "wait_ack", "partial_group"])
async def test_uncertain_local_completion_never_advances_or_reissues(case, failure):
    c = case
    action, ticket = await reserve(c)
    if failure == "wait_ack":
        original = c.native.wait

        def wait(token, timeout):
            original(token, timeout)
            raise OSError("private-lost-result")

        c.native.wait = wait
    elif failure == "close_ack":

        def fail(name):
            if name == "close" and c.kernel.calls[-1][1] == 102:
                raise OSError("private-close-ack")

        c.kernel.before = fail
    else:
        c.kernel.outputs[3] = b"{}\n200"
    with pytest.raises(ValueError):
        await c.runner.run(action, ticket)
    calls = list(c.kernel.calls)
    assert c.kernel.created == (4 if failure == "partial_group" else 1)
    c.kernel.before = None
    with pytest.raises(ValueError):
        await c.make().run(action)
    assert c.kernel.calls == calls
