"""Fixed production builders and durable readback; external OS/DB are synthetic."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ai_workshop.infrastructure.local.cutover_control_windows import WindowsControlLock
from ai_workshop.labs.rag.indexing.access_epoch_repository import (
    AccessEpochReadback,
    ActionReadback,
)
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    ReservedCutoverAction,
    canonical_json,
)
from tests.unit.labs.rag.indexing import test_access_epoch_deployment as fixtures
from tests.unit.labs.rag.indexing.test_access_epoch_process import Process, Repo
from tests.unit.labs.rag.indexing.test_access_epoch_submission import Kernel, PrivateMemory


@pytest.fixture
def deployment_case(monkeypatch):
    from ai_workshop.labs.rag.indexing.access_epoch_deployment_process import (
        RecordedDeploymentControlProcess,
    )

    builder, epoch, tls, index = fixtures.setup()
    generation = str(uuid4())
    lock = WindowsControlLock(epoch.original.daemon_sha256, "ai-workshop", native=Kernel())
    owner = lock.acquire(UUID(epoch.binding.execution_id), generation)
    memory = PrivateMemory()
    root = fixtures.module().PROJECT_ROOT
    journal = ProtectedControlJournal(root, memory, memory, lock, owner, lock.scope_sha256)
    kinds = (
        CutoverActionKind.STOP_REGISTERED_APPS,
        CutoverActionKind.STOP_OLD,
        CutoverActionKind.RETIRE_OLD,
        CutoverActionKind.PREPARE_TLS,
    )
    previous = tuple(
        ActionReadback(
            ReservedCutoverAction(
                uuid4(),
                owner.execution_id,
                2 * i + 1,
                kind,
                ControlExpectedIdentity("{}", 2 * i),
                generation,
            ),
            "settled",
            "{}",
            datetime.now(UTC),
            2 * i + 2,
        )
        for i, kind in enumerate(kinds)
    )
    repo = Repo(
        AccessEpochReadback(
            epoch, "tls_prepared", previous, "open", "frozen", None, None, generation
        )
    )
    native = Process()
    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_process._binary_sha", lambda: "c" * 64
    )

    class Inventory:
        async def read(self):
            return fixtures.raw({"ID": fixtures.DAEMON, "OSType": "linux"}), b""

    runner = RecordedDeploymentControlProcess(epoch, repo, builder, journal, native, Inventory())
    c = SimpleNamespace(
        builder=builder,
        epoch=epoch,
        journal=journal,
        repo=repo,
        native=native,
        runner=runner,
        memory=memory,
    )
    try:
        yield c
    finally:
        lock.close(owner)


async def reserve(c):
    ticket = await c.runner.prepare(CutoverActionKind.START_BOOTSTRAP)
    action = ReservedCutoverAction(
        uuid4(),
        ticket.execution_id,
        ticket.sequence,
        ticket.kind,
        ticket.expected,
        ticket.executor_generation,
    )
    predecessor = fixtures.retirement(c.builder, action)
    old = c.repo.state.actions[-2]
    manifest = json.loads(predecessor.settlement.manifest_json)
    manifest.update(action_id=str(old.action.action_id), sequence=old.action.sequence)
    predecessor = replace(
        predecessor,
        action=old.action,
        settlement=replace(
            predecessor.settlement,
            action_id=old.action.action_id,
            manifest_json=canonical_json(manifest),
        ),
    )
    previous = (
        *c.repo.state.actions[:-2],
        replace(
            old,
            action=predecessor.action,
            manifest_json=predecessor.settlement.manifest_json,
            observed_at=predecessor.settlement.observed_at,
        ),
        c.repo.state.actions[-1],
    )
    c.repo.state = replace(
        c.repo.state,
        actions=(
            *previous,
            ActionReadback(action, "pending", None, datetime.now(UTC), action.sequence),
        ),
    )
    return action, ticket, predecessor


async def test_committed_compose_is_recorded_but_does_not_settle_daemon(deployment_case):
    c = deployment_case
    action, ticket, predecessor = await reserve(c)
    record = await c.runner.run(action, ticket, predecessor)
    assert record.state == "process_finished" and record.exit_code == 0
    assert [x[0] for x in c.native.calls] == ["create", "resume", "wait", "close"]
    assert c.repo.state.actions[-1].outcome == "pending"
    argv, env, cwd = c.native.calls[0][1:]
    assert "--no-recreate" in argv and "--pull" in argv
    assert env["COMPOSE_DISABLE_ENV_FILE"] == "true"
    assert Path(cwd).name == "compose"
    with pytest.raises(ValueError):
        await c.runner.run(action, ticket, predecessor)
    assert len(c.native.calls) == 4


async def test_changed_protected_journal_root_never_submits_original_compose(deployment_case):
    c = deployment_case
    action, ticket, predecessor = await reserve(c)
    c.journal.root = c.journal.root / "synthetic-unrelated-root"
    with pytest.raises(ValueError, match="cutover_deployment_process_denied"):
        await c.runner.run(action, ticket, predecessor)
    assert c.native.calls == []


@pytest.mark.parametrize(
    "change",
    ["ticket_copy", "uncommitted", "retirement_copy", "wrong_generation", "binary_changed"],
)
async def test_nonfresh_or_uncommitted_compose_never_creates_child(
    deployment_case, monkeypatch, change
):
    c = deployment_case
    action, ticket, predecessor = await reserve(c)
    if change == "ticket_copy":
        ticket = replace(ticket)
    elif change == "uncommitted":
        c.repo.state = replace(c.repo.state, actions=c.repo.state.actions[:-1])
    elif change == "retirement_copy":
        predecessor = replace(
            predecessor, settlement=replace(predecessor.settlement, manifest_json="{}")
        )
    elif change == "wrong_generation":
        action = replace(action, executor_generation=str(uuid4()))
    else:
        monkeypatch.setattr(
            "ai_workshop.labs.rag.indexing.access_epoch_process._binary_sha", lambda: "e" * 64
        )
    with pytest.raises(ValueError):
        await c.runner.run(action, ticket, predecessor)
    assert c.native.calls == []
