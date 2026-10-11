"""Native role helpers use exact clean-ACK permits; no Docker is invoked."""

from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from ai_workshop.infrastructure.local.cutover_control_windows import WindowsControlLock
from ai_workshop.labs.rag.indexing.access_epoch_keys import KeyResult
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_types import canonical_json
from tests.unit.labs.rag.indexing.test_access_epoch_process import Process
from tests.unit.labs.rag.indexing.test_access_epoch_role_keys import case, response
from tests.unit.labs.rag.indexing.test_access_epoch_submission import Kernel, PrivateMemory


async def native_case(tmp_path, monkeypatch):
    from ai_workshop.labs.rag.indexing.access_epoch_key_process import RecordedBootstrapKeyCommands

    c = await case()
    lock = WindowsControlLock(c.epoch.original.daemon_sha256, "ai-workshop", native=Kernel())
    owner = lock.acquire(c.parent.execution_id, c.parent.executor_generation)
    memory = PrivateMemory()
    journal = ProtectedControlJournal(tmp_path, memory, memory, lock, owner, lock.scope_sha256)

    class Native(Process):
        def create_suspended(self, argv, env, cwd, *, stdin=None):
            self.input = stdin
            return super().create_suspended(argv, env, cwd)

        def wait(self, token, timeout_ms):
            result = super().wait(token, timeout_ms)
            result.stdout = response({"api_keys": []})
            return result

    native = Native()
    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_process._binary_sha", lambda: "c" * 64
    )
    runner = RecordedBootstrapKeyCommands(
        c.epoch, c.parent, c.repo, c.keys, c.builder, journal, native, Path(tmp_path)
    )
    return c, lock, owner, memory, native, runner


async def test_exact_new_issuance_records_child_before_resume_and_keeps_input_private(
    tmp_path, monkeypatch
):
    c, lock, owner, memory, native, runner = await native_case(tmp_path, monkeypatch)
    try:
        permissions = sha256(
            canonical_json(c.builder.permissions_descriptor("reader")).encode()
        ).hexdigest()
        action = await c.keys.reserve_issue(c.epoch, c.parent, "reader", permissions)
        command = c.builder.issue_key(c.controller.password, "reader", action.issuance_id)
        result = await runner.execute(command, action)
        assert result.exit_code == 0
        assert native.input == command.private_stdin
        assert [x[0] for x in native.calls] == ["create", "resume", "wait", "close"]
        assert "Synthetic20Character" not in repr(result)
        assert all(b"Synthetic20Character" not in value for value in memory.files.values())
        with pytest.raises(ValueError, match="cutover_bootstrap_process_denied"):
            await runner.execute(command, action)
    finally:
        lock.close(owner)


@pytest.mark.parametrize(
    "change", ["copied_action", "old_pending", "wrong_issuance", "lost_owner", "changed_parent"]
)
async def test_old_or_unbound_key_mutation_never_creates_native_child(
    tmp_path, monkeypatch, change
):
    c, lock, owner, memory, native, runner = await native_case(tmp_path, monkeypatch)
    try:
        permissions = sha256(
            canonical_json(c.builder.permissions_descriptor("reader")).encode()
        ).hexdigest()
        action = await c.keys.reserve_issue(c.epoch, c.parent, "reader", permissions)
        command = c.builder.issue_key(c.controller.password, "reader", action.issuance_id)
        if change == "copied_action":
            action = replace(action)
        elif change == "old_pending":
            action = (await c.keys.readback(c.epoch, c.parent))[0].action
        elif change == "wrong_issuance":
            command = replace(command)
        elif change == "lost_owner":
            lock.close(owner)
        else:
            from ai_workshop.labs.rag.indexing.access_epoch_models import AccessEpochEventRecord

            for (kind, _), row in c.db.rows.items():
                if kind is AccessEpochEventRecord and row.action_id == c.parent.action_id:
                    row.outcome = "settled"
        with pytest.raises(ValueError, match="cutover_bootstrap_process_denied"):
            await runner.execute(command, action)
        assert native.calls == []
    finally:
        with suppress(Exception):
            lock.close(owner)


async def test_readonly_lookup_has_recorded_local_job_but_cannot_grant_mutation(
    tmp_path, monkeypatch
):
    c, lock, owner, memory, native, runner = await native_case(tmp_path, monkeypatch)
    try:
        action = await c.keys.reserve_issue(c.epoch, c.parent, "reader", "c" * 64)
        command = c.builder.lookup_key(c.controller.password, "reader", action.issuance_id)
        result = await runner.execute(command, None)
        assert c.builder.decode_lookup(command, result.exit_code, result.stdout) is None
        assert len(memory.files) == 3
        assert len(await c.keys.readback(c.epoch, c.parent)) == 1
    finally:
        lock.close(owner)


async def test_owner_loss_during_resume_never_supplies_private_stdin(tmp_path, monkeypatch):
    c, lock, owner, memory, native, runner = await native_case(tmp_path, monkeypatch)
    permissions = sha256(
        canonical_json(c.builder.permissions_descriptor("reader")).encode()
    ).hexdigest()
    action = await c.keys.reserve_issue(c.epoch, c.parent, "reader", permissions)
    command = c.builder.issue_key(c.controller.password, "reader", action.issuance_id)
    original = native.resume

    def resume(token):
        original(token)
        lock.close(owner)

    native.resume = resume
    with pytest.raises(ValueError, match="cutover_bootstrap_process_denied"):
        await runner.execute(command, action)
    assert [x[0] for x in native.calls] == ["create", "resume", "close"]
    assert (await c.keys.readback(c.epoch, c.parent))[-1].outcome == "pending"


@pytest.mark.parametrize("failure", ["timeout", "missing", "reconstructed", "unknown_lookup"])
async def test_unknown_prior_local_helper_cannot_be_settled_by_key_metadata(
    tmp_path, monkeypatch, failure
):
    from ai_workshop.labs.rag.indexing.access_epoch_key_process import RecordedBootstrapKeyCommands

    c, lock, owner, memory, native, runner = await native_case(tmp_path, monkeypatch)
    try:
        permissions = sha256(
            canonical_json(c.builder.permissions_descriptor("reader")).encode()
        ).hexdigest()
        first = await c.keys.reserve_issue(c.epoch, c.parent, "reader", permissions)
        wait = native.wait

        def timeout(token, timeout_ms):
            raise TimeoutError("synthetic-timeout")

        native.wait = timeout
        if failure == "unknown_lookup":
            lookup = c.builder.lookup_key(c.controller.password, "reader", first.issuance_id)
            with pytest.raises(ValueError):
                await runner.execute(lookup, None)
        elif failure != "missing":
            command = c.builder.issue_key(c.controller.password, "reader", first.issuance_id)
            with pytest.raises(ValueError):
                await runner.execute(command, first)
        native.wait = wait
        await c.keys.settle(
            c.epoch,
            first,
            KeyResult(
                "issued",
                "synthetic-reader-key",
                "reader",
                first.issuance_id,
                permissions,
                datetime.now(UTC),
            ),
        )
        permissions = sha256(
            canonical_json(c.builder.permissions_descriptor("writer")).encode()
        ).hexdigest()
        second = await c.keys.reserve_issue(c.epoch, c.parent, "writer", permissions)
        command = c.builder.issue_key(c.controller.password, "writer", second.issuance_id)
        if failure == "reconstructed":
            runner = RecordedBootstrapKeyCommands(
                c.epoch, c.parent, c.repo, c.keys, c.builder, runner.journal, native, Path(tmp_path)
            )
        calls = len(native.calls)
        with pytest.raises(ValueError, match="cutover_bootstrap_process_denied"):
            await runner.execute(command, second)
        assert len(native.calls) == calls
    finally:
        lock.close(owner)


async def test_durable_prior_local_end_allows_next_committed_role(tmp_path, monkeypatch):
    c, lock, owner, memory, native, runner = await native_case(tmp_path, monkeypatch)
    try:
        permissions = sha256(
            canonical_json(c.builder.permissions_descriptor("reader")).encode()
        ).hexdigest()
        first = await c.keys.reserve_issue(c.epoch, c.parent, "reader", permissions)
        command = c.builder.issue_key(c.controller.password, "reader", first.issuance_id)
        await runner.execute(command, first)
        await c.keys.settle(
            c.epoch,
            first,
            KeyResult(
                "issued",
                "synthetic-reader-key",
                "reader",
                first.issuance_id,
                permissions,
                datetime.now(UTC),
            ),
        )
        permissions = sha256(
            canonical_json(c.builder.permissions_descriptor("writer")).encode()
        ).hexdigest()
        second = await c.keys.reserve_issue(c.epoch, c.parent, "writer", permissions)
        command = c.builder.issue_key(c.controller.password, "writer", second.issuance_id)
        assert (await runner.execute(command, second)).exit_code == 0
        assert [x[0] for x in native.calls].count("create") == 2
    finally:
        lock.close(owner)


async def test_catalog_lost_ack_never_launches_or_replays_helper(tmp_path, monkeypatch):
    c, lock, owner, memory, native, runner = await native_case(tmp_path, monkeypatch)
    try:
        permissions = sha256(
            canonical_json(c.builder.permissions_descriptor("reader")).encode()
        ).hexdigest()
        action = await c.keys.reserve_issue(c.epoch, c.parent, "reader", permissions)
        command = c.builder.issue_key(c.controller.password, "reader", action.issuance_id)
        memory.lost_ack = True
        with pytest.raises(ValueError, match="cutover_bootstrap_process_denied"):
            await runner.execute(command, action)
        memory.lost_ack = False
        with pytest.raises(ValueError, match="cutover_bootstrap_process_denied"):
            await runner.execute(command, action)
        assert native.calls == []
        assert len(memory.files) == 1
    finally:
        lock.close(owner)
