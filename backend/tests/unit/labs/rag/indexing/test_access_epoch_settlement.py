"""Actual settlement validator with fake read-only Docker and private storage."""

import json
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.infrastructure.local.cutover_control_windows import WindowsControlLock
from ai_workshop.labs.rag.indexing.access_epoch_repository import (
    AccessEpochReadback,
    ActionReadback,
)
from ai_workshop.labs.rag.indexing.access_epoch_submission import (
    ControlProcessIdentity,
    ProtectedControlJournal,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    AccessEpochBinding,
    CutoverActionKind,
    OriginalDeploymentIdentity,
    PreparedAccessEpoch,
    ReservedCutoverAction,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import CONTAINER, ORIGINAL_IMAGE_ID
from tests.unit.labs.rag.indexing.access_epoch_fixtures import case
from tests.unit.labs.rag.indexing.test_access_epoch_process import Repo
from tests.unit.labs.rag.indexing.test_access_epoch_submission import Kernel, PrivateMemory


@pytest.fixture
def settlement_case(tmp_path, monkeypatch):
    from ai_workshop.labs.rag.indexing.access_epoch_settlement import (
        OriginalDaemonSettlement,
        original_daemon_sha256,
    )

    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_process._binary_sha", lambda: "c" * 64
    )

    claim = case().claim
    execution, generation = uuid4(), str(uuid4())
    daemon = original_daemon_sha256()
    lock = WindowsControlLock(daemon, "ai-workshop", native=Kernel())
    owner = lock.acquire(execution, generation)
    memory = PrivateMemory()
    journal = ProtectedControlJournal(tmp_path, memory, memory, lock, owner, lock.scope_sha256)
    original = OriginalDeploymentIdentity(
        daemon,
        CONTAINER,
        "cluster",
        "stable",
        "old",
        *(["b" * 64] * 5),
        datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
    )
    epoch = PreparedAccessEpoch(
        AccessEpochBinding(claim, str(uuid4()), str(execution), 1), original
    )
    state = AccessEpochReadback(epoch, "prepared", (), "open", "frozen", None, None, generation)
    repo = Repo(state)

    class Docker:
        def __init__(self):
            self.commands = []
            self.fail = False
            self.ids = ""
            self.metadata = {
                "container_id": CONTAINER,
                "image_id": ORIGINAL_IMAGE_ID,
                "running": False,
                "restarting": False,
                "dead": False,
                "pid": 0,
                "started_at": "2026-01-01T00:00:00.000000000Z",
                "finished_at": "2026-01-02T00:00:00.000000000Z",
            }

        async def run(self, command):
            from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
                DAEMON,
                FixedCommand,
            )

            self.commands.append(command)
            if self.fail:
                raise OSError("private-error-marker")
            if command == FixedCommand.ORIGINAL_DAEMON_ID:
                return json.dumps({"id": DAEMON, "os": "linux"})
            if command == FixedCommand.ORIGINAL_STOP_METADATA:
                return json.dumps(self.metadata)
            if command == FixedCommand.ORIGINAL_ALL_IDS:
                return self.ids
            raise AssertionError("unexpected command")

    docker = Docker()
    probe = OriginalDaemonSettlement(
        epoch, repo, journal, docker, clock=lambda: datetime(2026, 1, 3, tzinfo=UTC)
    )
    yield SimpleNamespace(
        probe=probe, repo=repo, journal=journal, lock=lock, owner=owner, epoch=epoch, docker=docker
    )
    with suppress(Exception):
        lock.close(owner)


def reserved(c, kind):
    from ai_workshop.labs.rag.indexing.access_epoch_process import original_control_target

    sequence = max([0, *[x.event_sequence for x in c.repo.state.actions]])
    ticket = c.journal.prepare_expected(kind, sequence, original_control_target(c.epoch, kind))
    action = ReservedCutoverAction(
        uuid4(),
        ticket.execution_id,
        ticket.sequence,
        kind,
        ticket.expected,
        ticket.executor_generation,
    )
    item = ActionReadback(
        action, "pending", None, datetime(2026, 1, 1, tzinfo=UTC), action.sequence
    )
    c.repo.state = replace(c.repo.state, actions=(*c.repo.state.actions, item))
    record = c.journal.begin(action, ticket)
    child = ControlProcessIdentity(500, "133700000000000001", uuid4())
    record = c.journal.process_created(record, child)
    c.journal.process_finished(record, child, 0)
    return action


async def test_stop_combines_exact_successful_child_and_daemon_terminal_readback(settlement_case):
    c = settlement_case
    action = reserved(c, CutoverActionKind.STOP_OLD)
    result = await c.probe.observe(action)
    assert result.outcome == "settled"
    assert json.loads(result.manifest_json)["finished_at"] == "2026-01-02T00:00:00.000000+00:00"
    assert result.action_id == action.action_id
    assert "stdout" not in result.manifest_json
    assert len(c.docker.commands) == 2


async def test_db_unknown_can_be_observed_only_after_recorded_local_end(settlement_case):
    c = settlement_case
    action = reserved(c, CutoverActionKind.STOP_OLD)
    row = c.repo.state.actions[-1]
    c.repo.state = replace(
        c.repo.state,
        actions=(
            replace(
                row, outcome="unknown", manifest_json="{}", event_sequence=row.event_sequence + 1
            ),
        ),
    )
    result = await c.probe.observe(action)
    assert result.outcome == "settled"
    assert c.journal.read(action).state == "process_finished"


@pytest.mark.parametrize(
    "change",
    [
        "running",
        "restarting",
        "dead",
        "pid",
        "container",
        "image",
        "later_start",
        "early_finish",
        "future_finish",
        "extra",
        "missing",
        "bool_pid",
    ],
)
async def test_stop_unsafe_readback_does_not_settle(settlement_case, change):
    c = settlement_case
    action = reserved(c, CutoverActionKind.STOP_OLD)
    metadata = c.docker.metadata
    if change in {"running", "restarting", "dead"}:
        metadata[change] = True
    elif change == "pid":
        metadata["pid"] = 123
    elif change == "bool_pid":
        metadata["pid"] = False
    elif change == "container":
        metadata["container_id"] = "a" * 64
    elif change == "image":
        metadata["image_id"] = "sha256:" + "a" * 64
    elif change == "later_start":
        metadata["started_at"] = "2026-01-01T00:00:02Z"
    elif change == "early_finish":
        metadata["finished_at"] = "2025-12-31T00:00:00Z"
    elif change == "future_finish":
        metadata["finished_at"] = "2026-01-04T00:00:00Z"
    elif change == "extra":
        metadata["private"] = "private-error-marker"
    else:
        del metadata["finished_at"]
    with pytest.raises(ValueError, match="cutover_daemon_settlement_denied") as error:
        await c.probe.observe(action)
    assert "private-error-marker" not in str(error.value)


async def test_retire_requires_previously_committed_stop_and_successful_all_id_read(
    settlement_case,
):
    c = settlement_case
    stop = reserved(c, CutoverActionKind.STOP_OLD)
    result = await c.probe.observe(stop)
    latest = replace(
        c.repo.state.actions[-1],
        outcome="settled",
        manifest_json=result.manifest_json,
        observed_at=result.observed_at,
        event_sequence=stop.sequence + 1,
    )
    c.repo.state = replace(
        c.repo.state,
        actions=(latest,),
        old_server_stopped_at=datetime(2026, 1, 2, tzinfo=UTC),
        phase="old_stopped",
    )
    retire = reserved(c, CutoverActionKind.RETIRE_OLD)
    c.docker.ids = "a" * 64 + "\n" + "b" * 64
    result = await c.probe.observe(retire)
    assert result.outcome == "settled"
    assert json.loads(result.manifest_json)["retired_at"] == "2026-01-03T00:00:00.000000+00:00"


@pytest.mark.parametrize(
    "change",
    [
        "no_stop",
        "failed_read",
        "still_present",
        "malformed_ids",
        "missing_journal",
        "unknown_journal",
        "failed_child",
        "lost_owner",
        "wrong_reservation",
    ],
)
async def test_absence_or_local_exit_alone_does_not_settle(settlement_case, change):
    c = settlement_case
    if change != "no_stop":
        stop = reserved(c, CutoverActionKind.STOP_OLD)
        stopped = await c.probe.observe(stop)
        prior = replace(
            c.repo.state.actions[-1],
            outcome="settled",
            manifest_json=stopped.manifest_json,
            observed_at=stopped.observed_at,
            event_sequence=stop.sequence + 1,
        )
        c.repo.state = replace(
            c.repo.state,
            actions=(prior,),
            phase="old_stopped",
            old_server_stopped_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    action = reserved(c, CutoverActionKind.RETIRE_OLD)
    if change == "failed_read":
        c.docker.fail = True
    elif change == "still_present":
        c.docker.ids = CONTAINER
    elif change == "malformed_ids":
        c.docker.ids = "private-error-marker"
    elif change == "missing_journal":
        c.journal.files.files.pop(c.journal._path(action))
    elif change in {"unknown_journal", "failed_child"}:
        path = c.journal._path(action)
        wire = json.loads(c.journal.protection.unprotect(c.journal.files.read(path)))
        wire["state"] = "unknown" if change == "unknown_journal" else "process_finished"
        wire["exit_code"] = None if change == "unknown_journal" else 1
        c.journal.files.write(path, c.journal.protection.protect(json.dumps(wire).encode()))
    elif change == "lost_owner":
        c.lock.close(c.owner)
    elif change == "wrong_reservation":
        c.repo.state = replace(c.repo.state, actions=())
    with pytest.raises(ValueError, match="cutover_daemon_settlement_denied"):
        await c.probe.observe(action)
