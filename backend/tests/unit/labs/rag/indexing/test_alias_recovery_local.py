"""Offline controlled-restart contract; no native commands or sockets."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.indexing.alias_recovery_types import (
    AliasOperationSnapshot,
    AliasRecoveryReadback,
    FrozenAliasClaim,
)


def claim():
    return FrozenAliasClaim(
        AliasOperationSnapshot(
            uuid4(),
            "local_rag_indexes",
            "cluster",
            "active",
            uuid4(),
            uuid4(),
            (),
            datetime.now(UTC) - timedelta(days=1),
            "legacy_unknown",
        ),
        uuid4(),
        uuid4(),
        1,
    )


class Backend:
    def __init__(self):
        from ai_workshop.labs.rag.indexing.alias_recovery_local import ServerIdentity

        self.events = []
        self.t = datetime.now(UTC) - timedelta(seconds=20)
        self.old = ServerIdentity(
            "desktop-linux",
            "daemon",
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "cluster",
            "node",
            "old",
            self.t - timedelta(days=2),
            self.t - timedelta(days=3),
            self.t - timedelta(days=2),
            None,
            True,
        )
        self.new = replace(
            self.old,
            ephemeral_id="new",
            jvm_start_at=self.t + timedelta(seconds=3),
            started_at=self.t + timedelta(seconds=2),
            finished_at=self.t + timedelta(seconds=1),
        )
        self.current = self.old
        self.denial = None
        self.restart_error = False

    async def identity(self):
        self.events.append("identity")
        return self.current

    async def history(self, snapshot, identity):
        self.events.append("history")
        if self.denial == "history":
            raise RuntimeError("private-history-secret")
        return "d" * 64

    async def clients_absent(self):
        self.events.append("clients")
        if self.denial == "clients":
            raise RuntimeError("private-client-secret")
        return "e" * 64, self.t

    async def stop(self, identity):
        self.events.append("stop")
        self.current = replace(
            self.old,
            running=False,
            finished_at=self.t + timedelta(seconds=1),
        )
        return self.current

    async def start(self, identity):
        self.events.append("start")
        if self.restart_error:
            raise RuntimeError("private-start-secret")
        self.current = self.new
        return self.new


class Authority:
    def __init__(self, frozen, events):
        self.frozen, self.events = frozen, events
        self.fail_at = None
        self.calls = 0

    async def __call__(self, supplied):
        from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

        self.events.append("gate")
        self.calls += 1
        if self.calls == self.fail_at:
            raise AliasRecoveryError("rag_alias_commit_unknown")
        return AliasRecoveryReadback(
            self.frozen.snapshot,
            "open",
            None,
            "frozen",
            self.frozen,
            None,
        )


def collector(backend, frozen):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalTerminationCollector

    authority = Authority(frozen, backend.events)
    return LocalTerminationCollector(backend, authority), authority


async def test_controlled_drain_requires_ordered_gate_clients_stop_start_and_revalidation():
    frozen, backend = claim(), Backend()
    port, _ = collector(backend, frozen)
    proof = await port.collect_verified_end(frozen)
    proof.validate(frozen)
    assert backend.events == [
        "gate",
        "identity",
        "history",
        "clients",
        "gate",
        "identity",
        "stop",
        "gate",
        "start",
        "history",
        "clients",
        "gate",
    ]
    await port.revalidate(frozen, proof)
    assert backend.events[-4:] == ["gate", "identity", "history", "clients"]
    assert proof.old_ephemeral_id != proof.new_ephemeral_id
    assert proof.clients_terminated_at < proof.server_stopped_at < proof.server_started_at


@pytest.mark.parametrize("denial", ["history", "clients"])
async def test_missing_support_preconditions_prevent_any_restart(denial):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

    frozen, backend = claim(), Backend()
    backend.denial = denial
    port, _ = collector(backend, frozen)
    with pytest.raises(LocalRecoveryRefusal) as caught:
        await port.collect_verified_end(frozen)
    assert "secret" not in str(caught.value)
    assert "stop" not in backend.events and "start" not in backend.events


@pytest.mark.parametrize(
    "field,value",
    [
        ("container_id", "f" * 64),
        ("mount_sha256", "f" * 64),
        ("config_sha256", "f" * 64),
        ("context", "other"),
        ("daemon_id", "other"),
        ("cluster_uuid", "other"),
        ("stable_node_id", "other"),
        ("ephemeral_id", "old"),
    ],
)
async def test_changed_identity_cannot_produce_proof(field, value):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

    frozen, backend = claim(), Backend()
    backend.new = replace(backend.new, **{field: value})
    port, _ = collector(backend, frozen)
    with pytest.raises(LocalRecoveryRefusal):
        await port.collect_verified_end(frozen)


async def test_old_jvm_or_stale_start_cannot_be_a_new_barrier():
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

    frozen, backend = claim(), Backend()
    backend.new = replace(backend.new, jvm_start_at=backend.old.jvm_start_at)
    port, _ = collector(backend, frozen)
    with pytest.raises(LocalRecoveryRefusal):
        await port.collect_verified_end(frozen)


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
async def test_unknown_gate_commit_never_continues_workflow(fail_at):
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    frozen, backend = claim(), Backend()
    port, authority = collector(backend, frozen)
    authority.fail_at = fail_at
    with pytest.raises(AliasRecoveryError, match="rag_alias_commit_unknown"):
        await port.collect_verified_end(frozen)
    assert backend.events[-1] == "gate"
    if fail_at <= 2:
        assert "stop" not in backend.events
    if fail_at == 3:
        assert "start" not in backend.events


async def test_proof_cannot_be_revalidated_by_another_collector_instance():
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

    frozen, backend = claim(), Backend()
    first, _ = collector(backend, frozen)
    proof = await first.collect_verified_end(frozen)
    second, _ = collector(backend, frozen)
    with pytest.raises(LocalRecoveryRefusal):
        await second.revalidate(frozen, proof)
