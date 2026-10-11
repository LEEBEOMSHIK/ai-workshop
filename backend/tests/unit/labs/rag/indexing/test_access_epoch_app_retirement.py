"""Recorded app retirement with issued allowlists, RAM journal and fake kernel."""

import asyncio
import importlib
import json
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ai_workshop.infrastructure.local.cutover_control_windows import WindowsControlLock
from ai_workshop.infrastructure.local.process_retirement_windows import (
    ProcessLifetime,
    WindowsProcessRetirement,
)
from ai_workshop.labs.rag.indexing.access_epoch_repository import (
    AccessEpochReadback,
    ActionReadback,
)
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    ReservedCutoverAction,
    canonical_json,
)
from tests.unit.labs.rag.indexing import test_access_epoch_deployment as df
from tests.unit.labs.rag.indexing.test_access_epoch_process import Repo
from tests.unit.labs.rag.indexing.test_access_epoch_submission import Kernel, PrivateMemory


def module():
    return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_app_retirement")


class ProcessKernel:
    def __init__(self, targets):
        self.targets = {value.pid: value for _, value in targets}
        self.calls = []
        self.handle_pid = {}
        self.before = None
        self.wait_result = 0

    def call(self, name, *args):
        self.calls.append((name, *args))
        if self.before:
            self.before(name)

    def thread_id(self):
        return 9

    def open_process(self, pid):
        self.call("open", pid)
        handle = pid + 500000
        self.handle_pid[handle] = pid
        return handle

    def identity(self, handle):
        self.call("identity", handle)
        return self.targets[self.handle_pid[handle]]

    def terminate(self, handle, code):
        self.call("terminate", handle, code)

    def wait(self, handle, timeout):
        self.call("wait", handle, timeout)
        return 258 if timeout == 0 else self.wait_result

    def exit_code(self, handle):
        self.call("exit", handle)
        return 1

    def close(self, handle):
        self.call("close", handle)


class Issuer:
    def __init__(self, value):
        self.value = value
        self.issued = {value}
        self.revoked = False
        self.reads = 0
        self.asserts = 0

    async def read_current(self):
        self.reads += 1
        return self.value

    def assert_issued(self, value):
        self.asserts += 1
        if self.revoked or value not in self.issued:
            raise ValueError("private-registry-detail")


@pytest.fixture
def app_case():
    m = module()
    _, epoch, *_ = df.setup()
    lock = WindowsControlLock(epoch.original.daemon_sha256, "ai-workshop", native=Kernel())
    owner = lock.acquire(UUID(epoch.binding.execution_id), str(uuid4()))
    memory = PrivateMemory()
    journal = ProtectedControlJournal(
        m.PROJECT_ROOT, memory, memory, lock, owner, lock.scope_sha256
    )
    repo = Repo(
        AccessEpochReadback(
            epoch, "prepared", (), "open", "frozen", None, None, owner.executor_generation
        )
    )
    targets = (
        ("api", ProcessLifetime(12001, "133700000000000003", Path("C:/synthetic/python.exe"))),
        (
            "api_launcher",
            ProcessLifetime(12002, "133700000000000002", Path("C:/synthetic/venv/python.exe")),
        ),
        (
            "api_supervisor",
            ProcessLifetime(12003, "133700000000000001", Path("C:/synthetic/powershell.exe")),
        ),
    )
    allowlist = m.AppRetirementAllowlist(uuid4(), uuid4(), targets, ("worker", "beat"))
    issuer = Issuer(allowlist)
    kernel = ProcessKernel(targets)
    native = WindowsProcessRetirement(kernel)

    def make():
        return m.RecordedAppRetirement(epoch, repo, journal, issuer, native)

    c = SimpleNamespace(
        epoch=epoch,
        repo=repo,
        journal=journal,
        memory=memory,
        lock=lock,
        owner=owner,
        issuer=issuer,
        allowlist=allowlist,
        kernel=kernel,
        native=native,
        make=make,
        runner=make(),
    )
    try:
        yield c
    finally:
        with suppress(Exception):
            lock.close(owner)


async def reserve(c):
    ticket = await c.runner.prepare()
    action = ReservedCutoverAction(
        uuid4(),
        ticket.execution_id,
        ticket.sequence,
        CutoverActionKind.STOP_REGISTERED_APPS,
        ticket.expected,
        ticket.executor_generation,
    )
    c.repo.state = replace(
        c.repo.state,
        actions=(ActionReadback(action, "pending", None, datetime.now(UTC), action.sequence),),
    )
    return action, ticket


def packets(c):
    return [json.loads(c.memory.unprotect(value)) for value in c.memory.files.values()]


async def test_exact_parent_and_per_target_intent_precede_all_native_calls(app_case):
    c = app_case
    action, ticket = await reserve(c)

    def order(name):
        if name in {"open", "terminate"}:
            values = packets(c)
            assert any(p["record_type"] == "registered_app_parent" for p in values)
            assert any(
                p["record_type"] == "registered_app_target" and p["state"] == "intent"
                for p in values
            )

    c.kernel.before = order
    result = await c.runner.run(action, ticket)
    assert c.runner.assert_issued(result) is None
    with pytest.raises(ValueError):
        c.runner.assert_issued(replace(result))
    manifest = json.loads(result.manifest_json)
    assert manifest["target_count"] == 3
    assert [x["role"] for x in manifest["targets"]] == ["api_supervisor", "api_launcher", "api"]
    assert all(x["exit_code"] == 1 for x in manifest["targets"])
    assert c.repo.state.actions[0].outcome == "pending"
    assert [x[1] for x in c.kernel.calls if x[0] == "open"] == [12003, 12002, 12001]
    assert len([x for x in c.kernel.calls if x[0] == "terminate"]) == 3
    assert len(c.memory.files) == 4
    assert all("submission_id" not in p and "job_id" not in p for p in packets(c))
    assert "synthetic" not in repr(c.allowlist) and "synthetic" not in result.manifest_json
    assert c.repo.calls >= 9 and c.issuer.asserts >= 9
    calls = len(c.kernel.calls)
    with pytest.raises(ValueError):
        await c.runner.run(action, ticket)
    assert len(c.kernel.calls) == calls


async def test_all_off_requires_issued_complete_observation_and_durable_capture(app_case):
    c = app_case
    allowlist = module().AppRetirementAllowlist(
        uuid4(), uuid4(), (), ("api", "api_launcher", "api_supervisor", "worker", "beat")
    )
    c.issuer.value = allowlist
    c.issuer.issued.add(allowlist)
    action, ticket = await reserve(c)
    result = await c.runner.run(action, ticket)
    assert json.loads(result.manifest_json)["target_count"] == 0
    assert len(c.memory.files) == 1 and c.kernel.calls == []
    assert (await c.make().recover(action, allowlist)).manifest_json == result.manifest_json


@pytest.mark.parametrize(
    "change",
    [
        "copied_allowlist",
        "boolean",
        "worker_target",
        "missing_off",
        "partial_api",
        "duplicate_pid",
        "forbidden_frontend",
        "wrong_root",
        "revoked",
    ],
)
async def test_unissued_or_out_of_scope_targets_cannot_prepare(app_case, change):
    c = app_case
    value = c.allowlist
    if change == "copied_allowlist":
        value = replace(value)
    elif change == "boolean":
        value = True
    elif change == "worker_target":
        value = replace(
            value,
            targets=(
                *value.targets,
                (
                    "worker",
                    ProcessLifetime(12004, "133700000000000004", Path("C:/synthetic/python.exe")),
                ),
            ),
        )
    elif change == "missing_off":
        value = replace(value, off_roles=("worker",))
    elif change == "partial_api":
        value = replace(value, targets=value.targets[:-1])
    elif change == "duplicate_pid":
        value = replace(
            value,
            targets=(value.targets[0], ("api_launcher", value.targets[0][1]), value.targets[2]),
        )
    elif change == "forbidden_frontend":
        value = replace(
            value,
            targets=(
                *value.targets,
                (
                    "frontend",
                    ProcessLifetime(12004, "133700000000000004", Path("C:/synthetic/node.exe")),
                ),
            ),
        )
    elif change == "wrong_root":
        c.journal.root = c.journal.root / "other"
    elif change == "revoked":
        c.issuer.revoked = True
    c.issuer.value = value
    if change not in {"copied_allowlist", "boolean"}:
        c.issuer.issued.add(value)
    with pytest.raises(ValueError, match="app_retirement_denied"):
        await c.runner.prepare()
    assert c.kernel.calls == [] and c.memory.files == {}


@pytest.mark.parametrize(
    "change",
    ["uncommitted", "unknown", "prior_action", "generation", "claim", "open_gate", "copy_ticket"],
)
async def test_fresh_committed_parent_is_required_before_catalog_or_handles(app_case, change):
    c = app_case
    action, ticket = await reserve(c)
    if change == "uncommitted":
        c.repo.state = replace(c.repo.state, actions=())
    elif change == "unknown":
        c.repo.state = replace(
            c.repo.state, actions=(replace(c.repo.state.actions[0], outcome="unknown"),)
        )
    elif change == "prior_action":
        c.repo.state = replace(
            c.repo.state, actions=(*c.repo.state.actions, c.repo.state.actions[0])
        )
    elif change == "generation":
        c.repo.state = replace(c.repo.state, executor_generation=str(uuid4()))
    elif change == "claim":
        c.repo.state = replace(c.repo.state, prepared=None)
    elif change == "open_gate":
        c.repo.state = replace(c.repo.state, gate_state="open")
    elif change == "copy_ticket":
        ticket = replace(ticket)
    with pytest.raises(ValueError):
        await c.runner.run(action, ticket)
    assert c.kernel.calls == [] and c.memory.files == {}


@pytest.mark.parametrize("failure", ["timeout", "cancel", "owner_loss", "db_loss", "issuer_loss"])
async def test_unfinished_target_never_reopens_or_retries(app_case, failure):
    c = app_case
    action, ticket = await reserve(c)
    if failure == "timeout":
        c.kernel.wait_result = 258

    def fault(name):
        if name == "open":
            if failure == "owner_loss":
                c.lock.close(c.owner)
            elif failure == "db_loss":
                c.repo.state = replace(c.repo.state, gate_state="open")
            elif failure == "issuer_loss":
                c.issuer.revoked = True
        if failure == "cancel" and name == "terminate":
            raise asyncio.CancelledError()

    c.kernel.before = fault
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError):
        await c.runner.run(action, ticket)
    calls = len(c.kernel.calls)
    c.kernel.before = None
    if failure == "owner_loss":
        return
    with pytest.raises(ValueError):
        await c.make().recover(action, c.allowlist)
    with pytest.raises(ValueError):
        await c.make().run(action, ticket)
    assert len(c.kernel.calls) == calls
    assert len([x for x in c.kernel.calls if x[0] == "open"]) == 1
    assert c.kernel.calls[-1][0] == "close"


@pytest.mark.parametrize(
    "stage", ["parent_intent", "target_intent", "target_complete", "parent_complete"]
)
async def test_lost_private_write_ack_never_authorizes_retry(app_case, stage):
    c = app_case
    action, ticket = await reserve(c)
    write = c.memory.write

    def lost(path, content):
        write(path, content)
        packet = json.loads(c.memory.unprotect(content))
        key = (
            ("parent" if packet["record_type"] == "registered_app_parent" else "target")
            + "_"
            + ("complete" if packet["state"] == "completed" else "intent")
        )
        if key == stage:
            raise OSError("private-lost-ack")

    c.memory.write = lost
    with pytest.raises(ValueError):
        await c.runner.run(action, ticket)
    c.memory.write = write
    calls = len(c.kernel.calls)
    if stage == "parent_complete":
        assert (
            json.loads((await c.make().recover(action, c.allowlist)).manifest_json)["target_count"]
            == 3
        )
    else:
        with pytest.raises(ValueError):
            await c.make().recover(action, c.allowlist)
    with pytest.raises(ValueError):
        await c.make().run(action, ticket)
    assert len(c.kernel.calls) == calls


@pytest.mark.parametrize(
    "change",
    [
        "missing_target",
        "different_target",
        "new_all_off",
        "copied_allowlist",
        "changed_parent",
        "new_generation",
    ],
)
async def test_readonly_recovery_needs_entire_original_bound_capture(app_case, change):
    c = app_case
    action, ticket = await reserve(c)
    result = await c.runner.run(action, ticket)
    assert (await c.make().recover(action, c.allowlist)).manifest_json == result.manifest_json
    allowlist = c.allowlist
    if change == "missing_target":
        path = next(path for path in c.memory.files if "api_supervisor" in path)
        del c.memory.files[path]
    elif change == "different_target":
        path = next(path for path in c.memory.files if "api_supervisor" in path)
        packet = json.loads(c.memory.unprotect(c.memory.files[path]))
        packet["target"]["pid"] += 1
        c.memory.files[path] = c.memory.protect(canonical_json(packet).encode())
    elif change == "new_all_off":
        allowlist = module().AppRetirementAllowlist(
            uuid4(), uuid4(), (), ("api", "api_launcher", "api_supervisor", "worker", "beat")
        )
        c.issuer.issued.add(allowlist)
    elif change == "copied_allowlist":
        allowlist = replace(allowlist)
    elif change == "changed_parent":
        action = replace(action, action_id=uuid4())
    elif change == "new_generation":
        c.repo.state = replace(c.repo.state, executor_generation=str(uuid4()))
    calls = len(c.kernel.calls)
    with pytest.raises(ValueError):
        await c.make().recover(action, allowlist)
    assert len(c.kernel.calls) == calls


@pytest.mark.parametrize("change", ["boolean_preceding_sequence", "journal_scope"])
async def test_bound_metadata_has_strict_types_and_exact_scope(app_case, change):
    c = app_case
    action, ticket = await reserve(c)
    if change == "boolean_preceding_sequence":
        action = replace(action, expected=replace(action.expected, preceding_sequence=False))
        c.repo.state = replace(
            c.repo.state, actions=(replace(c.repo.state.actions[0], action=action),)
        )
    else:
        c.journal.scope = "0" * 64
    with pytest.raises(ValueError, match="app_retirement_denied"):
        await c.runner.run(action, ticket)
    assert c.kernel.calls == [] and c.memory.files == {}


async def test_same_generation_reacquisition_only_reads_completed_capture(app_case):
    c = app_case
    action, ticket = await reserve(c)
    result = await c.runner.run(action, ticket)
    c.lock.close(c.owner)
    lock = WindowsControlLock(c.epoch.original.daemon_sha256, "ai-workshop", native=Kernel())
    owner = lock.acquire(c.owner.execution_id, c.owner.executor_generation)
    assert owner.session_id != c.owner.session_id
    c.journal.lock = lock
    c.journal.owner = owner
    c.repo.state = replace(
        c.repo.state,
        actions=(replace(c.repo.state.actions[0], outcome="unknown", event_sequence=2),),
    )
    before_files = dict(c.memory.files)
    before_calls = list(c.kernel.calls)
    recovered = await c.make().recover(action, c.allowlist)
    assert recovered.manifest_json == result.manifest_json
    assert c.memory.files == before_files and c.kernel.calls == before_calls
    lock.close(owner)
