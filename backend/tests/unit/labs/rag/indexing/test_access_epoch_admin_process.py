"""Real administrator recording with RAM private ports and no native execution."""

import asyncio
import importlib
import json
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ai_workshop.infrastructure.local.cutover_control_windows import WindowsControlLock
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap import BootstrapCommands
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_binding import BootstrapBindingFactory
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_original_security import (
    OriginalSecurityAbsenceReader,
)
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
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
from tests.unit.labs.rag.indexing import test_access_epoch_deployment as df
from tests.unit.labs.rag.indexing.test_access_epoch_process import Process, Repo
from tests.unit.labs.rag.indexing.test_access_epoch_submission import Kernel, PrivateMemory


def module():
    return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_admin_process")


@pytest.fixture
async def admin_case(monkeypatch):
    m = module()
    deployment, epoch, *_ = df.setup()
    generation = str(uuid4())
    lock = WindowsControlLock(epoch.original.daemon_sha256, "ai-workshop", native=Kernel())
    owner = lock.acquire(UUID(epoch.binding.execution_id), generation)
    memory = PrivateMemory()
    root = df.module().PROJECT_ROOT
    journal = ProtectedControlJournal(root, memory, memory, lock, owner, lock.scope_sha256)
    bootstrap_action = replace(df.action(deployment), executor_generation=generation)
    observed = df.observation(deployment, bootstrap_action)
    kinds = CUTOVER_ORDER[: CUTOVER_ORDER.index(CutoverActionKind.BOOTSTRAP_ADMIN)]
    previous = tuple(
        ActionReadback(
            bootstrap_action
            if kind == CutoverActionKind.START_BOOTSTRAP
            else ReservedCutoverAction(
                uuid4(),
                owner.execution_id,
                2 * i + 1,
                kind,
                ControlExpectedIdentity("{}", 2 * i),
                generation,
            ),
            "settled",
            observed.manifest_json if kind == CutoverActionKind.START_BOOTSTRAP else "{}",
            datetime.now(UTC),
            2 * i + 2,
        )
        for i, kind in enumerate(kinds)
    )
    repo = Repo(
        AccessEpochReadback(
            epoch, "bootstrap_started", previous, "open", "frozen", None, None, generation
        )
    )

    class Identity:
        async def observe_original(self, snapshot):
            return epoch.original

    class Security:
        async def read(self, path):
            return []

    security = OriginalSecurityAbsenceReader(Identity(), Security())
    absence = await security.observe(epoch.binding.claim.snapshot)
    factory = BootstrapBindingFactory(repo, journal, deployment, security)
    permissions = AccessEpochPermissions("rag", ((uuid4(), None),))
    builder = await factory.create(observed, absence, permissions)

    class Native(Process):
        output = b"Synthetic20Character\n"
        exit_code = 0

        def create_suspended(self, argv, env, cwd, *, stdin=None):
            self.input = stdin
            return super().create_suspended(argv, env, cwd)

        def wait(self, token, timeout_ms):
            result = super().wait(token, timeout_ms)
            result.stdout, result.stderr, result.exit_code = self.output, b"", self.exit_code
            return result

    native = Native()
    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_process._binary_sha", lambda: "c" * 64
    )

    async def runner(*, selected=observed, selected_root=root, fresh_builder=False):
        commands = (
            await factory.create(observed, absence, permissions) if fresh_builder else builder
        )
        return m.RecordedBootstrapAdministrator(
            epoch, repo, deployment, selected, commands, journal, native, selected_root, factory
        )

    c = SimpleNamespace(
        epoch=epoch,
        repo=repo,
        observed=observed,
        deployment=deployment,
        builder=builder,
        journal=journal,
        memory=memory,
        native=native,
        lock=lock,
        owner=owner,
        root=root,
        new_runner=runner,
        factory=factory,
        permissions=permissions,
    )
    c.runner = await runner()
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
        ticket.kind,
        ticket.expected,
        ticket.executor_generation,
    )
    c.repo.state = replace(
        c.repo.state,
        actions=(
            *c.repo.state.actions,
            ActionReadback(action, "pending", None, datetime.now(UTC), action.sequence),
        ),
    )
    return action, ticket


async def test_reset_records_before_resume_and_returns_only_protected_credential(admin_case):
    c = admin_case
    action, ticket = await reserve(c)

    def order(name):
        record = c.journal.read(action)
        if name == "create":
            assert record.state == "intent"
        elif name in {"resume", "wait"}:
            assert record.state == "process_created"

    c.native.before = order
    result = await c.runner.run(action, ticket)
    assert result.password.get_secret_value() == "Synthetic20Character"
    assert result.audit_status == "pending"
    assert result.pending_audits == (
        "administrator_authentication",
        "native_realm",
        "temporary_file_user_cleanup",
    )
    assert c.runner.assert_credential(result) is None
    with pytest.raises(ValueError):
        c.runner.assert_credential(replace(result))
    assert [x[0] for x in c.native.calls] == ["create", "resume", "wait", "close"]
    argv, env, cwd = c.native.calls[0][1:]
    assert argv[-7:] == (
        "--auto",
        "--batch",
        "--silent",
        "--username",
        "elastic",
        "--url",
        "https://localhost:9200",
    )
    assert argv[7] == c.observed.container_id and cwd == c.root
    assert c.native.input is None
    assert all(not k.upper().startswith(("DOCKER", "COMPOSE", "AI_WORKSHOP")) for k in env)
    assert "Synthetic20Character" not in repr(result)
    assert all(b"Synthetic20Character" not in payload for payload in c.memory.files.values())
    assert c.journal.read(action).state == "process_finished"
    assert c.repo.state.actions[-1].outcome == "pending"
    assert len(c.memory.files) == 4
    with pytest.raises(ValueError):
        await c.runner.run(action, ticket)
    assert len(c.native.calls) == 4


@pytest.mark.parametrize(
    "change",
    [
        "root",
        "copied_observation",
        "wrong_kind",
        "bootstrap_manifest",
        "prior_unknown",
        "generation",
        "gate",
        "closed",
        "current_unknown",
        "copied_ticket",
        "wrong_expected",
    ],
)
async def test_unbound_or_uncommitted_admin_cannot_create_child(admin_case, change):
    c = admin_case
    if change == "root":
        with pytest.raises(ValueError):
            await c.new_runner(selected_root=c.root / "synthetic-other")
        return
    if change == "copied_observation":
        with pytest.raises(ValueError):
            await c.new_runner(selected=replace(c.observed))
        return
    action, ticket = await reserve(c)
    if change == "wrong_kind":
        action = replace(action, kind=CutoverActionKind.ISSUE_ROLE_KEY)
    elif change == "bootstrap_manifest":
        c.repo.state = replace(
            c.repo.state,
            actions=(
                *c.repo.state.actions[:-2],
                replace(c.repo.state.actions[-2], manifest_json="{}"),
                c.repo.state.actions[-1],
            ),
        )
    elif change == "prior_unknown":
        c.repo.state = replace(
            c.repo.state,
            actions=(
                replace(c.repo.state.actions[0], outcome="unknown"),
                *c.repo.state.actions[1:],
            ),
        )
    elif change == "generation":
        c.repo.state = replace(c.repo.state, executor_generation=str(uuid4()))
    elif change == "gate":
        c.repo.state = replace(c.repo.state, gate_state="open")
    elif change == "closed":
        c.repo.state = replace(c.repo.state, operation_state="closed")
    elif change == "current_unknown":
        c.repo.state = replace(
            c.repo.state,
            actions=(
                *c.repo.state.actions[:-1],
                replace(c.repo.state.actions[-1], outcome="unknown"),
            ),
        )
    elif change == "copied_ticket":
        ticket = replace(ticket)
    elif change == "wrong_expected":
        action = replace(action, expected=ControlExpectedIdentity("{}", action.sequence - 1))
    with pytest.raises(ValueError, match="cutover_bootstrap_admin_denied"):
        await c.runner.run(action, ticket)
    assert c.native.calls == [] and c.memory.files == {}


@pytest.mark.parametrize("stage", ["create", "resume", "wait", "cancel"])
async def test_unknown_local_child_never_resets_again(admin_case, stage):
    c = admin_case
    action, ticket = await reserve(c)
    c.native.fail = stage
    if stage == "cancel":

        def cancel(name):
            if name == "wait":
                raise asyncio.CancelledError()

        c.native.before = cancel
        with pytest.raises(asyncio.CancelledError):
            await c.runner.run(action, ticket)
    else:
        with pytest.raises(ValueError):
            await c.runner.run(action, ticket)
    calls = len(c.native.calls)
    c.native.fail, c.native.before = None, None
    replacement = await c.new_runner(fresh_builder=True)
    with pytest.raises(ValueError):
        await replacement.recover(action)
    with pytest.raises(ValueError):
        await replacement.run(action, ticket)
    with pytest.raises(ValueError):
        await replacement.prepare()
    assert len(c.native.calls) == calls


@pytest.mark.parametrize("stage", ["catalog", "output", "credential", "finished"])
async def test_lost_write_ack_never_replays_reset_and_recovers_only_completed_capture(
    admin_case, stage
):
    c = admin_case
    action, ticket = await reserve(c)
    write = c.memory.write

    def lost(path, content):
        write(path, content)
        packet = json.loads(c.memory.unprotect(content))
        selected = (
            stage == "catalog"
            and path.endswith("administrator-catalog.dpapi")
            or stage == "output"
            and path.endswith(".administrator-output.dpapi")
            or stage == "credential"
            and path.endswith(".administrator.dpapi")
            or stage == "finished"
            and packet.get("state") == "process_finished"
        )
        if selected:
            raise OSError("synthetic-lost-ack")

    c.memory.write = lost
    with pytest.raises(ValueError):
        await c.runner.run(action, ticket)
    c.memory.write = write
    calls = len(c.native.calls)
    replacement = await c.new_runner(fresh_builder=True)
    if stage in {"credential", "finished"}:
        result = await replacement.recover(action)
        assert result.password.get_secret_value() == "Synthetic20Character"
        assert result.audit_status == "pending"
    else:
        with pytest.raises(ValueError):
            await replacement.recover(action)
    with pytest.raises(ValueError):
        await replacement.run(action, ticket)
    assert len(c.native.calls) == calls


async def test_completed_output_recovery_requires_same_catalog_action_and_child(admin_case):
    c = admin_case
    action, ticket = await reserve(c)
    await c.runner.run(action, ticket)
    for path in tuple(c.memory.files):
        if path.endswith(".administrator.dpapi"):
            del c.memory.files[path]
    replacement = await c.new_runner(fresh_builder=True)
    result = await replacement.recover(action)
    assert result.password.get_secret_value() == "Synthetic20Character"
    assert len(c.native.calls) == 4
    with pytest.raises(ValueError):
        await replacement.recover(replace(action, action_id=uuid4()))


@pytest.mark.parametrize(
    "change",
    [
        "missing_capture",
        "wrong_capture_child",
        "wrong_catalog",
        "missing_journal",
        "unfinished_journal",
        "missing_credential_and_output",
    ],
)
async def test_private_credential_alone_does_not_establish_completed_reset(admin_case, change):
    c = admin_case
    action, ticket = await reserve(c)
    await c.runner.run(action, ticket)
    for path in tuple(c.memory.files):
        if (
            change in {"missing_capture", "missing_credential_and_output"}
            and path.endswith(".administrator-output.dpapi")
            or change == "missing_credential_and_output"
            and path.endswith(".administrator.dpapi")
            or change == "missing_journal"
            and path.endswith(str(action.action_id) + ".dpapi")
        ):
            del c.memory.files[path]
        elif change == "wrong_catalog" and path.endswith("administrator-catalog.dpapi"):
            packet = json.loads(c.memory.unprotect(c.memory.files[path]))
            packet["action_id"] = str(uuid4())
            c.memory.files[path] = c.memory.protect(json.dumps(packet).encode())
        elif change == "wrong_capture_child" and path.endswith(".administrator-output.dpapi"):
            packet = json.loads(c.memory.unprotect(c.memory.files[path]))
            packet["child"]["pid"] += 1
            c.memory.files[path] = c.memory.protect(json.dumps(packet).encode())
        elif change == "unfinished_journal" and path.endswith(str(action.action_id) + ".dpapi"):
            packet = json.loads(c.memory.unprotect(c.memory.files[path]))
            packet.update(state="unknown", exit_code=None)
            c.memory.files[path] = c.memory.protect(json.dumps(packet).encode())
    with pytest.raises(ValueError):
        await (await c.new_runner(fresh_builder=True)).recover(action)
    assert len(c.native.calls) == 4


@pytest.mark.parametrize("password", [b"12345678", b"Synthetic20Character", b"x" * 128])
async def test_real_reset_decoder_accepts_cli_password_lengths(admin_case, password):
    c = admin_case
    c.native.output = password + b"\r\n"
    action, ticket = await reserve(c)
    assert (await c.runner.run(action, ticket)).password.get_secret_value() == password.decode()


async def test_owner_loss_after_resume_prevents_wait_or_credential_return(admin_case):
    c = admin_case
    action, ticket = await reserve(c)

    def lose(name):
        if name == "resume":
            c.lock.close(c.owner)

    c.native.before = lose
    with pytest.raises(ValueError, match="cutover_bootstrap_admin_denied"):
        await c.runner.run(action, ticket)
    assert [x[0] for x in c.native.calls] == ["create", "resume", "close"]


async def test_recovery_rejects_float_child_identity_even_when_python_compares_equal(admin_case):
    c = admin_case
    action, ticket = await reserve(c)
    await c.runner.run(action, ticket)
    for path in c.memory.files:
        if path.endswith(".administrator-output.dpapi"):
            packet = json.loads(c.memory.unprotect(c.memory.files[path]))
            packet["child"]["pid"] = float(packet["child"]["pid"])
            c.memory.files[path] = c.memory.protect(canonical_json(packet).encode())
    with pytest.raises(ValueError, match="cutover_bootstrap_admin_denied"):
        await (await c.new_runner(fresh_builder=True)).recover(action)
    assert len(c.native.calls) == 4


async def test_unknown_database_outcome_recovers_completed_capture_without_native_retry(admin_case):
    c = admin_case
    action, ticket = await reserve(c)
    await c.runner.run(action, ticket)
    c.repo.state = replace(
        c.repo.state,
        actions=(
            *c.repo.state.actions[:-1],
            replace(
                c.repo.state.actions[-1], outcome="unknown", event_sequence=action.sequence + 1
            ),
        ),
    )
    result = await (await c.new_runner(fresh_builder=True)).recover(action)
    assert result.password.get_secret_value() == "Synthetic20Character"
    assert result.audit_status == "pending"
    assert len(c.native.calls) == 4


@pytest.mark.parametrize(
    "output,exit_code",
    [
        (b"short\n", 0),
        (b"private-marker\x00\n", 0),
        (b"x" * 131, 0),
        (b"Synthetic20Character\n", 1),
    ],
)
async def test_invalid_or_failed_reset_output_is_never_credential_or_retry(
    admin_case, output, exit_code
):
    c = admin_case
    c.native.output, c.native.exit_code = output, exit_code
    action, ticket = await reserve(c)
    with pytest.raises(ValueError, match="^cutover_bootstrap_admin_denied$") as failure:
        await c.runner.run(action, ticket)
    assert "private-marker" not in repr(failure.value)
    with pytest.raises(ValueError):
        await (await c.new_runner(fresh_builder=True)).recover(action)
    assert not any(path.endswith(".administrator.dpapi") for path in c.memory.files)
    assert len(c.native.calls) == 4


async def test_changed_native_child_is_not_completed_administrator_reset(admin_case):
    c = admin_case
    action, ticket = await reserve(c)
    original_wait = c.native.wait

    def changed(token, timeout_ms):
        result = original_wait(token, timeout_ms)
        result.child = SimpleNamespace(
            pid=9999, creation_time=c.native.child.creation_time, job_id=uuid4()
        )
        return result

    c.native.wait = changed
    with pytest.raises(ValueError):
        await c.runner.run(action, ticket)
    assert c.journal.read(action).state == "unknown"
    assert not any(path.endswith(".administrator-output.dpapi") for path in c.memory.files)


async def test_private_credential_password_must_equal_original_completed_output(admin_case):
    c = admin_case
    action, ticket = await reserve(c)
    await c.runner.run(action, ticket)
    for path in c.memory.files:
        if path.endswith(".administrator.dpapi"):
            packet = json.loads(c.memory.unprotect(c.memory.files[path]))
            packet["password"] = "DifferentSyntheticPassword"
            c.memory.files[path] = c.memory.protect(canonical_json(packet).encode())
    with pytest.raises(ValueError):
        await (await c.new_runner(fresh_builder=True)).recover(action)
    assert len(c.native.calls) == 4


async def test_direct_security_absent_boolean_builder_is_not_native_authority(admin_case):
    c = admin_case
    unissued = BootstrapCommands(c.builder.binding, c.permissions)
    with pytest.raises(ValueError, match="cutover_bootstrap_admin_denied"):
        module().RecordedBootstrapAdministrator(
            c.epoch,
            c.repo,
            c.deployment,
            c.observed,
            unissued,
            c.journal,
            c.native,
            c.root,
            c.factory,
        )
    assert c.native.calls == []


@pytest.mark.parametrize("field", ["repository", "journal", "deployment"])
async def test_factory_boundaries_are_exact_objects_before_native_create(admin_case, field):
    c = admin_case
    action, ticket = await reserve(c)
    setattr(c.factory, field, SimpleNamespace())
    with pytest.raises(ValueError, match="cutover_bootstrap_admin_denied"):
        await c.runner.run(action, ticket)
    assert c.native.calls == [] and c.memory.files == {}
