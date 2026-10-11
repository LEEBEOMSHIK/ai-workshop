"""Bootstrap accepting JVM needs its own recorded exact-ID stop and retirement."""

import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.infrastructure.local.cutover_control_windows import WindowsControlLock
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_repository import (
    AccessEpochReadback,
    ActionReadback,
)
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    ReservedCutoverAction,
)
from tests.unit.labs.rag.indexing import test_access_epoch_deployment as fixtures
from tests.unit.labs.rag.indexing.test_access_epoch_process import Process, Repo
from tests.unit.labs.rag.indexing.test_access_epoch_submission import Kernel, PrivateMemory


@pytest.fixture
def bootstrap_case(tmp_path, monkeypatch, request):
    from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_retirement import (
        BootstrapDaemonSettlement,
        RecordedBootstrapRetirement,
    )

    builder, started, _, _, _ = fixtures.build_case()
    bootstrap = fixtures.observation(builder, started)
    epoch = builder.epoch
    lock = WindowsControlLock(epoch.original.daemon_sha256, "ai-workshop", native=Kernel())
    owner = lock.acquire(started.execution_id, started.executor_generation)
    request.addfinalizer(lambda: lock.close(owner))
    memory = PrivateMemory()
    journal = ProtectedControlJournal(tmp_path, memory, memory, lock, owner, lock.scope_sha256)
    actions = []
    for i, kind in enumerate(
        CUTOVER_ORDER[: CUTOVER_ORDER.index(CutoverActionKind.STOP_BOOTSTRAP)]
    ):
        action = replace(
            started,
            action_id=uuid4(),
            sequence=2 * i + 1,
            kind=kind,
            expected=ControlExpectedIdentity("{}", 2 * i),
        )
        if kind == CutoverActionKind.START_BOOTSTRAP:
            action = started
        actions.append(
            ActionReadback(
                action,
                "settled",
                bootstrap.manifest_json if kind == CutoverActionKind.START_BOOTSTRAP else "{}",
                fixtures.NOW,
                2 * i + 2,
            )
        )
    repo = Repo(
        AccessEpochReadback(
            epoch,
            "credentials_issued",
            tuple(actions),
            "open",
            "frozen",
            None,
            None,
            owner.executor_generation,
        )
    )
    native = Process()
    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_process._binary_sha", lambda: "c" * 64
    )
    runner = RecordedBootstrapRetirement(epoch, repo, journal, native, tmp_path, builder, bootstrap)

    class Docker:
        def __init__(self):
            self.present = False
            self.wrong_daemon = False
            self.wrong_start = False

        async def daemon(self):
            return json.dumps(
                {"id": "wrong" if self.wrong_daemon else fixtures.DAEMON, "os": "linux"}
            )

        async def metadata(self):
            return json.dumps(
                {
                    "container_id": bootstrap.container_id,
                    "image_id": fixtures.ORIGINAL_IMAGE_ID,
                    "running": False,
                    "restarting": False,
                    "dead": False,
                    "pid": 0,
                    "started_at": "2000-01-01T00:00:00Z"
                    if self.wrong_start
                    else json.loads(bootstrap.manifest_json)["docker_started_at"],
                    "finished_at": "2026-10-08T08:00:10Z",
                }
            )

        async def all_ids(self):
            return bootstrap.container_id if self.present else ""

    docker = Docker()
    probe = BootstrapDaemonSettlement(
        epoch,
        repo,
        journal,
        builder,
        bootstrap,
        docker,
        clock=lambda: fixtures.NOW + timedelta(seconds=20),
    )
    yield SimpleNamespace(
        builder=builder,
        bootstrap=bootstrap,
        epoch=epoch,
        runner=runner,
        probe=probe,
        repo=repo,
        journal=journal,
        native=native,
        docker=docker,
    )


async def reserve(c, kind):
    ticket = await c.runner.prepare(kind)
    action = ReservedCutoverAction(
        uuid4(),
        ticket.execution_id,
        ticket.sequence,
        kind,
        ticket.expected,
        ticket.executor_generation,
    )
    c.repo.state = replace(
        c.repo.state,
        actions=(
            *c.repo.state.actions,
            ActionReadback(action, "pending", None, fixtures.NOW, action.sequence),
        ),
    )
    await c.runner.run(action, ticket)
    return action


async def test_bootstrap_has_distinct_exact_id_stop_and_committed_retirement(bootstrap_case):
    c = bootstrap_case
    stop = await reserve(c, CutoverActionKind.STOP_BOOTSTRAP)
    ended = await c.probe.observe(stop)
    assert json.loads(ended.manifest_json)["container_id"] == c.bootstrap.container_id
    old = c.repo.state.actions[-1]
    c.repo.state = replace(
        c.repo.state,
        actions=(
            *c.repo.state.actions[:-1],
            replace(
                old,
                outcome="settled",
                manifest_json=ended.manifest_json,
                observed_at=ended.observed_at,
                event_sequence=old.event_sequence + 1,
            ),
        ),
    )
    retire = await reserve(c, CutoverActionKind.RETIRE_BOOTSTRAP)
    result = await c.probe.observe(retire)
    assert json.loads(result.manifest_json)["stopped_action_id"] == str(stop.action_id)
    argv = c.native.calls[0][1]
    assert argv[-1] == c.bootstrap.container_id and fixtures.CONTAINER not in argv
    assert "--time" in argv and "--force" not in argv


async def test_unknown_db_stop_is_observed_without_resubmission(bootstrap_case):
    c = bootstrap_case
    action = await reserve(c, CutoverActionKind.STOP_BOOTSTRAP)
    row = c.repo.state.actions[-1]
    c.repo.state = replace(
        c.repo.state,
        actions=(
            *c.repo.state.actions[:-1],
            replace(
                row, outcome="unknown", manifest_json="{}", event_sequence=row.event_sequence + 1
            ),
        ),
    )
    calls = len(c.native.calls)
    result = await c.probe.observe(action)
    assert result.outcome == "settled"
    assert len(c.native.calls) == calls


@pytest.mark.parametrize("failure", ["local_unknown", "daemon_changed", "start_changed"])
async def test_local_exit_or_wrong_daemon_lifetime_does_not_settle_bootstrap(
    bootstrap_case, failure
):
    c = bootstrap_case
    action = await reserve(c, CutoverActionKind.STOP_BOOTSTRAP)
    if failure == "local_unknown":
        path = c.journal._path(action)
        payload = json.loads(c.journal.protection.unprotect(c.journal.files.read(path)))
        payload.update(state="unknown", exit_code=None)
        c.journal.files.write(path, c.journal.protection.protect(json.dumps(payload).encode()))
    elif failure == "daemon_changed":
        c.docker.wrong_daemon = True
    else:
        c.docker.wrong_start = True
    with pytest.raises(ValueError):
        await c.probe.observe(action)
