"""Daemon observations settle a completed helper, not a client exit alone."""

import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_repository import ActionReadback
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    ReservedCutoverAction,
)
from tests.unit.labs.rag.indexing import test_access_epoch_deployment as fixtures
from tests.unit.labs.rag.indexing.test_access_epoch_deployment_process import (
    deployment_case,  # noqa: F401
    reserve,
)


async def settled_case(c):
    from ai_workshop.labs.rag.indexing.access_epoch_deployment_settlement import (
        DeploymentDaemonSettlement,
    )

    action, ticket, predecessor = await reserve(c)
    await c.runner.run(action, ticket, predecessor)
    packets = []

    def capture(packet):
        packets.append(packet)
        return packet

    observed = fixtures.observation(c.builder, action, transform=capture)
    packet = packets[0]

    class Reads:
        calls = 0

        async def read(self, kind, hashes):
            self.calls += 1
            return replace(packet, tls_public_hashes=hashes)

    class Tls:
        calls = 0

        async def read_settled(self, original):
            self.calls += 1
            return c.builder.tls

        def assert_issued(self, value):
            assert value is c.builder.tls

    tls = Tls()
    reads = Reads()
    tls_row = c.repo.state.actions[3]
    c.repo.state = replace(
        c.repo.state,
        actions=(
            *c.repo.state.actions[:3],
            replace(tls_row, manifest_json=c.builder.tls.manifest_json),
            *c.repo.state.actions[4:],
        ),
    )
    c.observer = DeploymentDaemonSettlement(
        c.epoch,
        c.repo,
        c.journal,
        c.builder,
        tls,
        reads,
        clock=lambda: fixtures.NOW + timedelta(seconds=2),
    )
    return SimpleNamespace(action=action, reads=reads, tls=tls, observed=observed)


async def test_settlement_requires_independent_daemon_and_protected_tls(deployment_case):  # noqa: F811
    c = deployment_case
    s = await settled_case(c)
    observed, result = await c.observer.observe(s.action)
    assert observed.container_id == s.observed.container_id
    assert result.outcome == "settled" and result.action_id == s.action.action_id
    assert json.loads(result.manifest_json) == json.loads(observed.manifest_json)
    assert s.reads.calls == 2 and s.tls.calls == 2
    assert c.builder.assert_observed(observed) is None


@pytest.mark.parametrize(
    "change",
    [
        "missing_journal",
        "local_unknown",
        "wrong_target",
        "closed",
        "owner_lost",
        "changed_daemon",
        "db_changed",
        "copied_action",
    ],
)
async def test_incomplete_or_changed_observation_never_settles(deployment_case, change):  # noqa: F811
    c = deployment_case
    s = await settled_case(c)
    action = s.action
    if change == "missing_journal":
        c.memory.files.pop(c.journal._path(action))
    elif change == "local_unknown":
        path = c.journal._path(action)
        packet = json.loads(c.memory.unprotect(c.memory.files[path]))
        packet.update(state="unknown", exit_code=None, revision=packet["revision"] + 1)
        c.memory.files[path] = c.memory.protect(json.dumps(packet).encode())
    elif change == "wrong_target":
        expected = replace(action.expected, identity_json='{"target_sha256":"' + "a" * 64 + '"}')
        action = replace(action, expected=expected)
        c.repo.state = replace(
            c.repo.state,
            actions=(*c.repo.state.actions[:-1], replace(c.repo.state.actions[-1], action=action)),
        )
    elif change == "closed":
        c.repo.state = replace(c.repo.state, operation_state="closed")
    elif change == "owner_lost":
        c.journal.owner = replace(c.journal.owner, session_id=uuid4())
    elif change == "copied_action":
        action = ReservedCutoverAction(
            uuid4(),
            action.execution_id,
            action.sequence,
            action.kind,
            action.expected,
            action.executor_generation,
        )
    else:
        read = s.reads.read

        async def changed(kind, hashes):
            packet = await read(kind, hashes)
            if change == "db_changed":
                c.repo.state = replace(c.repo.state, executor_generation=str(uuid4()))
            if change == "changed_daemon" and s.reads.calls == 2:
                packet = replace(packet, daemon=b'{"ID":"different","OSType":"linux"}')
            return packet

        s.reads.read = changed
    with pytest.raises(ValueError, match="deployment_settlement_denied"):
        await c.observer.observe(action)


async def test_completed_local_helper_can_reconcile_unknown_database_ack(deployment_case):  # noqa: F811
    c = deployment_case
    s = await settled_case(c)
    row = c.repo.state.actions[-1]
    c.repo.state = replace(
        c.repo.state,
        actions=(
            *c.repo.state.actions[:-1],
            ActionReadback(row.action, "unknown", "{}", row.observed_at, row.event_sequence + 1),
        ),
    )
    _, result = await c.observer.observe(s.action)
    assert result.outcome == "settled"


@pytest.mark.parametrize("final", [False, True])
async def test_fixed_production_reader_and_decoder_agree_on_selected_network(
    deployment_case, final  # noqa: F811
):  # noqa: F811
    from ai_workshop.labs.rag.indexing.access_epoch_deployment_settlement import (
        FixedDeploymentDaemonReads,
    )
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import FixedCommand

    c = deployment_case
    s = await settled_case(c)
    packet = await s.reads.read(s.action.kind, c.builder.tls_hashes)
    action = s.action
    predecessor = None
    if final:
        predecessor = s.observed
        final_template = fixtures.action(c.builder, CutoverActionKind.START_SECURED)
        action = replace(final_template, executor_generation=s.action.executor_generation)
        packets = []

        def capture(value):
            packets.append(value)
            return value

        fixtures.observation(
            c.builder,
            action,
            fixtures.container_json(c.builder, action, "f" * 64),
            predecessor,
            transform=capture,
        )
        packet = packets[0]
    replies = {
        FixedCommand.ORIGINAL_DAEMON_ID: fixtures.raw({"id": fixtures.DAEMON, "os": "linux"}),
        FixedCommand.SELECTED_SLOT_CONTAINER: packet.container,
        FixedCommand.SELECTED_IMAGE_RAW: packet.image,
        FixedCommand.SELECTED_VOLUME_RAW: packet.volume,
        FixedCommand.ORIGINAL_ALL_IDS: packet.all_container_ids,
        FixedCommand.SELECTED_SECURITY_CONFIG: packet.secured_config,
    }
    if final:
        replies[FixedCommand.SELECTED_NETWORK_RAW] = packet.network

    class Executor:
        calls = []

        async def run(self, command):
            self.calls.append(command)
            assert command in replies
            return replies[command].decode()

    executor = Executor()
    result = await FixedDeploymentDaemonReads(executor).read(action.kind, packet.tls_public_hashes)
    assert result.network == packet.network
    assert (FixedCommand.SELECTED_NETWORK_RAW in executor.calls) is final
    assert c.builder.decode_daemon(
        action, result, predecessor=predecessor, observed_at=fixtures.NOW + timedelta(seconds=2)
    )


async def test_readonly_daemon_reader_rejects_untyped_kind_before_io():
    from ai_workshop.labs.rag.indexing.access_epoch_deployment_settlement import (
        FixedDeploymentDaemonReads,
    )

    class Executor:
        async def run(self, command):
            raise AssertionError("Unexpected command")

    with pytest.raises(ValueError, match="deployment_settlement_denied"):
        await FixedDeploymentDaemonReads(Executor()).read("start_secured", ())
