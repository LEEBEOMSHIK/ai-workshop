"""Committed reservation bridge; native commands and DB are faked, never submitted."""

import asyncio
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.infrastructure.local.cutover_control_windows import WindowsControlLock
from ai_workshop.labs.rag.indexing.access_epoch_process import (
    RecordedOriginalControlProcess,
    RecordedProcessError,
)
from ai_workshop.labs.rag.indexing.access_epoch_repository import (
    AccessEpochReadback,
    ActionReadback,
)
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    AccessEpochBinding,
    ControlExpectedIdentity,
    CutoverActionKind,
    OriginalDeploymentIdentity,
    PreparedAccessEpoch,
    ReservedCutoverAction,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import CONTAINER, DOCKER_EXE
from tests.unit.labs.rag.indexing.access_epoch_fixtures import case
from tests.unit.labs.rag.indexing.test_access_epoch_submission import Kernel, PrivateMemory


class Process:
    def __init__(self):
        self.calls = []
        self.fail = None
        self.before = None
        self.child = SimpleNamespace(pid=1002, creation_time="133700000000000001", job_id=uuid4())
        self.token = SimpleNamespace(child=self.child)

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if self.before:
            self.before(name)
        if self.fail == name:
            raise OSError("private-native-error")

    def create_suspended(self, argv, env, cwd):
        self._call("create", argv, env, cwd)
        return self.token

    def resume(self, token):
        assert token is self.token
        self._call("resume")

    def wait(self, token, timeout_ms):
        assert token is self.token
        self._call("wait", timeout_ms)
        return SimpleNamespace(child=self.child, exit_code=0, stdout=b"private-out", stderr=b"err")

    def close(self, token):
        assert token is self.token
        self._call("close")


class Repo:
    def __init__(self, state):
        self.state = state
        self.calls = 0
        self.fail = False
        self.before = None

    async def readback(self, claim):
        self.calls += 1
        if self.before:
            self.before()
        if self.fail:
            raise OSError("private-db-error")
        return self.state


@pytest.fixture
def process_case(monkeypatch, tmp_path):
    c = case()
    execution, generation = uuid4(), str(uuid4())
    lock = WindowsControlLock("a" * 64, "ai-workshop", native=Kernel())
    owner = lock.acquire(execution, generation)
    storage = PrivateMemory()
    journal = ProtectedControlJournal(tmp_path, storage, storage, lock, owner, lock.scope_sha256)
    original = OriginalDeploymentIdentity(
        "a" * 64,
        CONTAINER,
        "cluster",
        "stable",
        "old",
        *(["b" * 64] * 5),
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    epoch = PreparedAccessEpoch(
        AccessEpochBinding(c.claim, str(uuid4()), str(execution), 1), original
    )
    previous = ReservedCutoverAction(
        uuid4(),
        execution,
        1,
        CutoverActionKind.STOP_REGISTERED_APPS,
        ControlExpectedIdentity("{}", 0),
        generation,
    )
    settled = ActionReadback(previous, "settled", "{}", datetime.now(UTC), 2)
    state = AccessEpochReadback(
        epoch, "apps_stopped", (settled,), "open", "frozen", None, None, generation
    )
    repo, native = Repo(state), Process()
    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_process._binary_sha", lambda: "c" * 64
    )
    runner = RecordedOriginalControlProcess(epoch, repo, journal, native, tmp_path)
    yield SimpleNamespace(
        runner=runner,
        repo=repo,
        journal=journal,
        storage=storage,
        native=native,
        lock=lock,
        owner=owner,
        epoch=epoch,
    )
    with suppress(Exception):
        lock.close(owner)


async def reserve(c, kind=CutoverActionKind.STOP_OLD):
    ticket = await c.runner.prepare(kind)
    action = ReservedCutoverAction(
        uuid4(),
        ticket.execution_id,
        ticket.sequence,
        kind,
        ticket.expected,
        ticket.executor_generation,
    )
    item = ActionReadback(action, "pending", None, datetime.now(UTC), action.sequence)
    c.repo.state = replace(c.repo.state, actions=(*c.repo.state.actions, item))
    return action, ticket


async def test_exact_committed_intent_child_then_resume_and_private_result(process_case):
    c = process_case
    action, ticket = await reserve(c)

    def ordering(name):
        record = c.journal.read(action)
        if name == "create":
            assert record.state == "intent"
        elif name in {"resume", "wait"}:
            assert record.state == "process_created" and record.child.pid == 1002

    c.native.before = ordering
    result = await c.runner.run(action, ticket)
    assert result.state == "process_finished" and result.exit_code == 0
    assert not hasattr(result, "daemon_settled")
    names = [x[0] for x in c.native.calls]
    assert names == ["create", "resume", "wait", "close"]
    argv, env, _ = c.native.calls[0][1:]
    assert argv == (
        DOCKER_EXE,
        "--host",
        "npipe:////./pipe/dockerDesktopLinuxEngine",
        "stop",
        "--time",
        "30",
        CONTAINER,
    )
    assert all(not k.upper().startswith(("DOCKER_", "AI_WORKSHOP_")) for k in env)
    output_files = [p for p in c.storage.files if p.endswith(".output.dpapi")]
    assert len(output_files) == 1
    assert b"private-out" not in repr(result).encode()
    assert all(b"private-out" not in blob for blob in c.storage.files.values())
    with pytest.raises(RecordedProcessError):
        await c.runner.run(action, ticket)
    assert names == [x[0] for x in c.native.calls]


async def test_uncommitted_action_never_writes_or_creates(process_case):
    c = process_case
    action, ticket = await reserve(c)
    c.repo.state = replace(c.repo.state, actions=())
    with pytest.raises(RecordedProcessError, match="cutover_recorded_process_denied"):
        await c.runner.run(action, ticket)
    assert c.storage.writes == 0 and c.native.calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation_state", "closed"),
        ("gate_state", "open"),
        ("phase", "verified"),
        ("executor_generation", str(uuid4())),
        ("prepared", None),
    ],
)
async def test_fresh_db_conflict_prevents_submission(process_case, field, value):
    c = process_case
    action, ticket = await reserve(c)
    c.repo.state = replace(c.repo.state, **{field: value})
    with pytest.raises(RecordedProcessError):
        await c.runner.run(action, ticket)
    assert c.storage.writes == 0 and c.native.calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("outcome", "unknown"),
        ("outcome", "settled"),
        ("manifest_json", "{}"),
        ("event_sequence", 99),
    ],
)
async def test_old_pending_or_result_cannot_be_replayed(process_case, field, value):
    c = process_case
    action, ticket = await reserve(c)
    item = replace(c.repo.state.actions[-1], **{field: value})
    c.repo.state = replace(c.repo.state, actions=(item,))
    with pytest.raises(RecordedProcessError):
        await c.runner.run(action, ticket)
    assert c.storage.writes == 0 and c.native.calls == []


async def test_repository_error_consumes_ticket_without_native_retry(process_case):
    c = process_case
    action, ticket = await reserve(c)
    c.repo.fail = True
    with pytest.raises(RecordedProcessError) as exc:
        await c.runner.run(action, ticket)
    assert "private" not in str(exc.value)
    c.repo.fail = False
    with pytest.raises(RecordedProcessError):
        await c.runner.run(action, ticket)
    assert c.storage.writes == 0 and c.native.calls == []


@pytest.mark.parametrize("stage", ["create", "resume", "wait", "close"])
async def test_native_uncertainty_is_not_reissued_and_only_own_child_is_closed(process_case, stage):
    c = process_case
    action, ticket = await reserve(c)
    c.native.fail = stage
    with pytest.raises(RecordedProcessError):
        await c.runner.run(action, ticket)
    record = c.journal.read(action)
    assert record.state == ("process_finished" if stage == "close" else "unknown")
    calls = list(c.native.calls)
    c.native.fail = None
    with pytest.raises(RecordedProcessError):
        await c.runner.run(action, ticket)
    assert c.native.calls == calls
    if stage != "create":
        assert [x[0] for x in calls].count("close") == 1


async def test_lost_intent_ack_never_creates(process_case):
    c = process_case
    action, ticket = await reserve(c)
    c.storage.lost_ack = True
    with pytest.raises(RecordedProcessError):
        await c.runner.run(action, ticket)
    assert c.native.calls == []


async def test_lost_child_record_ack_closes_suspended_child_without_resume(process_case):
    c = process_case
    action, ticket = await reserve(c)
    c.native.before = lambda name: (
        setattr(c.storage, "lost_ack", True) if name == "create" else None
    )
    with pytest.raises(RecordedProcessError):
        await c.runner.run(action, ticket)
    assert [x[0] for x in c.native.calls] == ["create", "close"]


async def test_ownership_loss_after_db_readback_prevents_intent(process_case):
    c = process_case
    action, ticket = await reserve(c)
    c.repo.before = lambda: c.lock.close(c.owner)
    with pytest.raises(RecordedProcessError):
        await c.runner.run(action, ticket)
    assert c.storage.writes == 0 and c.native.calls == []


async def test_binary_change_after_prepare_prevents_command(process_case, monkeypatch):
    c = process_case
    action, ticket = await reserve(c)
    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_process._binary_sha", lambda: "d" * 64
    )
    with pytest.raises(RecordedProcessError):
        await c.runner.run(action, ticket)
    assert c.storage.writes == 0 and c.native.calls == []


async def test_wrong_daemon_lock_scope_prevents_submission(process_case):
    c = process_case
    c.runner.epoch = replace(c.epoch, original=replace(c.epoch.original, daemon_sha256="d" * 64))
    c.repo.state = replace(c.repo.state, prepared=c.runner.epoch)
    with pytest.raises(RecordedProcessError):
        await c.runner.prepare(CutoverActionKind.STOP_OLD)
    assert c.storage.writes == 0 and c.native.calls == []


async def test_capture_root_cannot_escape_journal_root(process_case):
    c = process_case
    c.runner.root = c.runner.root.parent
    with pytest.raises(RecordedProcessError):
        await c.runner.prepare(CutoverActionKind.STOP_OLD)
    assert c.storage.writes == 0 and c.native.calls == []


async def test_retire_has_no_force_or_volume_delete(process_case):
    c = process_case
    old = c.repo.state.actions[0].action
    stopped = replace(
        old,
        action_id=uuid4(),
        kind=CutoverActionKind.STOP_OLD,
        sequence=3,
        expected=ControlExpectedIdentity("{}", 2),
    )
    c.repo.state = replace(
        c.repo.state,
        phase="old_stopped",
        actions=(
            *c.repo.state.actions,
            ActionReadback(stopped, "settled", "{}", datetime.now(UTC), 4),
        ),
        old_server_stopped_at=datetime.now(UTC),
    )
    action, ticket = await reserve(c, CutoverActionKind.RETIRE_OLD)
    await c.runner.run(action, ticket)
    assert c.native.calls[0][1][-2:] == ("rm", CONTAINER)


@pytest.mark.parametrize(
    "kind", [CutoverActionKind.START_SECURED, CutoverActionKind.PREPARE_TLS, "stop_old"]
)
async def test_unsupported_kind_never_issues_ticket_or_command(process_case, kind):
    c = process_case
    with pytest.raises(RecordedProcessError):
        await c.runner.prepare(kind)
    assert c.storage.writes == 0 and c.native.calls == []


@pytest.mark.parametrize("stage", ["resume", "wait"])
async def test_cancellation_preserves_unknown_and_closes_owned_job_once(process_case, stage):
    c = process_case
    action, ticket = await reserve(c)

    def cancel(name):
        if name == stage:
            raise asyncio.CancelledError

    c.native.before = cancel
    with pytest.raises(asyncio.CancelledError):
        await c.runner.run(action, ticket)
    assert c.journal.read(action).state == "unknown"
    calls = list(c.native.calls)
    assert [x[0] for x in calls].count("close") == 1
    c.native.before = None
    with pytest.raises(RecordedProcessError):
        await c.runner.run(action, ticket)
    assert c.native.calls == calls
