"""PREPARE_TLS uses synthetic RAM keys/storage; no original file or DB writes."""

import importlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from ai_workshop.infrastructure.local.tls_bundle import ProjectTlsBundles
from ai_workshop.labs.rag.indexing.access_epoch_repository import ActionReadback
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    ReservedCutoverAction,
)
from tests.unit.labs.rag.indexing import test_access_epoch_process as process_fixtures

NOW = datetime(2026, 10, 8, tzinfo=UTC)
process_case = process_fixtures.process_case


async def test_settled_tls_readback_is_readonly_and_issuer_bound(tls_case):
    c = tls_case
    action, ticket = await reserve(c)
    prepared = await c.materializer.execute(action, ticket)
    latest = replace(
        c.repo.state.actions[-1],
        outcome="settled",
        manifest_json=prepared.manifest_json,
        event_sequence=action.sequence + 1,
    )
    c.repo.state = replace(
        c.repo.state, phase="tls_prepared", actions=(*c.repo.state.actions[:-1], latest)
    )
    writes = c.storage.writes
    restored = await c.materializer.read_settled(action)
    assert restored.manifest_json == prepared.manifest_json
    assert c.storage.writes == writes
    assert c.materializer.assert_issued(restored) is None
    with pytest.raises(module().AccessEpochTlsError):
        c.materializer.assert_issued(replace(restored))


@pytest.mark.parametrize(
    "change",
    [
        "pending",
        "wrong_manifest",
        "lost_owner",
        "wrong_generation",
        "tampered_leaf",
        "unsettled_predecessor",
        "extra_current_kind",
    ],
)
async def test_settled_tls_readback_requires_actual_material_and_current_owned_state(
    tls_case, change
):
    c = tls_case
    action, ticket = await reserve(c)
    prepared = await c.materializer.execute(action, ticket)
    latest = replace(
        c.repo.state.actions[-1],
        outcome="settled",
        manifest_json=prepared.manifest_json,
        event_sequence=action.sequence + 1,
    )
    c.repo.state = replace(
        c.repo.state, phase="tls_prepared", actions=(*c.repo.state.actions[:-1], latest)
    )
    if change == "pending":
        c.repo.state = replace(
            c.repo.state, actions=(*c.repo.state.actions[:-1], replace(latest, outcome="pending"))
        )
    elif change == "wrong_manifest":
        c.repo.state = replace(
            c.repo.state, actions=(*c.repo.state.actions[:-1], replace(latest, manifest_json="{}"))
        )
    elif change == "lost_owner":
        c.lock.close(c.owner)
    elif change == "wrong_generation":
        c.repo.state = replace(c.repo.state, executor_generation=str(uuid4()))
    elif change == "tampered_leaf":
        c.storage.files[prepared.leaf_locations[0]] = b"synthetic-tamper"
    elif change == "unsettled_predecessor":
        c.repo.state = replace(
            c.repo.state,
            actions=(
                replace(c.repo.state.actions[0], outcome="unknown"),
                *c.repo.state.actions[1:],
            ),
        )
    else:
        extra = replace(
            action,
            action_id=uuid4(),
            kind=CutoverActionKind.START_SECURED,
            sequence=action.sequence + 2,
        )
        c.repo.state = replace(
            c.repo.state,
            actions=(
                *c.repo.state.actions,
                ActionReadback(extra, "pending", None, NOW, extra.sequence),
            ),
        )
    writes = c.storage.writes
    with pytest.raises(module().AccessEpochTlsError):
        await c.materializer.read_settled(action)
    assert c.storage.writes == writes


@pytest.fixture
def tmp_path():
    # Imported process fixture only passes this namespace to RAM private ports.
    return Path("C:/synthetic-workshop")


def module():
    name = "ai_workshop.labs.rag.indexing.access_epoch_tls"
    assert importlib.util.find_spec(name) is not None, "TLS materializer missing"
    return importlib.import_module(name)


@pytest.fixture
def tls_case(process_case):
    c = process_case
    previous = []
    for index, kind in enumerate(
        (
            CutoverActionKind.STOP_REGISTERED_APPS,
            CutoverActionKind.STOP_OLD,
            CutoverActionKind.RETIRE_OLD,
        )
    ):
        sequence = index * 2 + 1
        action = ReservedCutoverAction(
            uuid4(),
            c.owner.execution_id,
            sequence,
            kind,
            ControlExpectedIdentity("{}", sequence - 1),
            c.owner.executor_generation,
        )
        previous.append(ActionReadback(action, "settled", "{}", NOW, sequence + 1))
    c.repo.state = replace(c.repo.state, phase="old_retired", actions=tuple(previous))
    adapter = ProjectTlsBundles(c.storage)
    c.materializer = module().AccessEpochTls(
        c.epoch, c.repo, c.journal, adapter, "172.28.0.2", clock=lambda: NOW
    )
    return c


async def reserve(c):
    ticket = await c.materializer.prepare()
    action = ReservedCutoverAction(
        uuid4(),
        ticket.execution_id,
        ticket.sequence,
        CutoverActionKind.PREPARE_TLS,
        ticket.expected,
        ticket.executor_generation,
    )
    pending = ActionReadback(action, "pending", None, NOW, action.sequence)
    c.repo.state = replace(c.repo.state, actions=(*c.repo.state.actions, pending))
    return action, ticket


async def test_exact_committed_tls_creates_only_six_bind_files_and_protected_packet(tls_case):
    c = tls_case
    action, ticket = await reserve(c)
    result = await c.materializer.execute(action, ticket)
    paths = [p.replace("\\", "/") for p in c.storage.files]
    bind = [p for p in paths if "/bind/" in p]
    assert len(bind) == 6
    assert {p.split("/bind/")[1] for p in bind} == {
        "http/node.key",
        "http/node.crt",
        "http/ca.crt",
        "transport/node.key",
        "transport/node.crt",
        "transport/ca.crt",
    }
    assert len([p for p in paths if p.endswith("bundle.dpapi")]) == 1
    assert len(paths) == 8  # intent + protected bundle + six exact leaves/public certs
    assert result.original_ipv4 == "172.28.0.2"
    assert len(result.leaf_locations) == 6
    manifest = json.loads(result.manifest_json)
    assert manifest["preparation_kind"] == "local_files"
    assert (
        manifest["http_ca_sha256"] == sha256(c.storage.files[result.leaf_locations[2]]).hexdigest()
    )
    assert manifest["http_ca_der_sha256"] != manifest["http_ca_sha256"]
    assert "PRIVATE KEY" not in repr(result)
    record = c.journal.read(action)
    assert record.state == "intent" and record.child is None
    writes = c.storage.writes
    recovered = await c.materializer.reconcile(action)
    assert recovered.manifest_json == result.manifest_json and c.storage.writes == writes
    with pytest.raises(module().AccessEpochTlsError):
        await c.materializer.execute(action, ticket)


@pytest.mark.parametrize(
    "field,value",
    [
        ("gate_state", "open"),
        ("operation_state", "closed"),
        ("prepared", None),
        ("phase", "verified"),
        ("executor_generation", str(uuid4())),
    ],
)
async def test_changed_committed_owner_or_gate_never_generates(tls_case, field, value):
    c = tls_case
    action, ticket = await reserve(c)
    c.repo.state = replace(c.repo.state, **{field: value})
    with pytest.raises(module().AccessEpochTlsError):
        await c.materializer.execute(action, ticket)
    assert c.storage.writes == 0 and not c.storage.plain


async def test_uncommitted_or_copied_ticket_does_not_write(tls_case):
    c = tls_case
    action, ticket = await reserve(c)
    with pytest.raises(module().AccessEpochTlsError):
        await c.materializer.execute(action, replace(ticket))
    c.repo.state = replace(c.repo.state, actions=c.repo.state.actions[:-1])
    with pytest.raises(module().AccessEpochTlsError):
        await c.materializer.execute(action, ticket)
    assert c.storage.writes == 0


async def test_unknown_without_bundle_cannot_generate_or_resume(tls_case):
    c = tls_case
    action, ticket = await reserve(c)
    c.journal.begin(action, ticket)
    latest = replace(
        c.repo.state.actions[-1], outcome="unknown", event_sequence=action.sequence + 1
    )
    c.repo.state = replace(c.repo.state, actions=(*c.repo.state.actions[:-1], latest))
    writes = c.storage.writes
    with pytest.raises(module().AccessEpochTlsError, match="tls_preparation_unknown"):
        await c.materializer.reconcile(action)
    assert c.storage.writes == writes


@pytest.mark.parametrize("lost_write", [1, 2, 3, 8])
async def test_write_ack_loss_never_regenerates_or_rewrites(tls_case, lost_write):
    c = tls_case
    action, ticket = await reserve(c)
    original = c.storage.write

    def write(path, data):
        original(path, data)
        if c.storage.writes == lost_write:
            raise OSError("synthetic-private-error")

    c.storage.write = write
    with pytest.raises(module().AccessEpochTlsError, match="tls_preparation_unknown"):
        await c.materializer.execute(action, ticket)
    writes = c.storage.writes
    with pytest.raises(module().AccessEpochTlsError):
        await c.materializer.execute(action, ticket)
    if lost_write == 8:
        assert await c.materializer.reconcile(action)
    else:
        with pytest.raises(module().AccessEpochTlsError):
            await c.materializer.reconcile(action)
    assert c.storage.writes == writes


async def test_readback_tamper_and_missing_file_remain_unknown(tls_case):
    c = tls_case
    action, ticket = await reserve(c)
    prepared = await c.materializer.execute(action, ticket)
    path = prepared.leaf_locations[0]
    c.storage.files[path] = b"synthetic-tamper"
    writes = c.storage.writes
    with pytest.raises(module().AccessEpochTlsError):
        await c.materializer.reconcile(action)
    del c.storage.files[path]
    with pytest.raises(module().AccessEpochTlsError):
        await c.materializer.reconcile(action)
    assert writes == c.storage.writes


async def test_owner_loss_during_write_prevents_later_leaf_writes(tls_case):
    c = tls_case
    action, ticket = await reserve(c)
    original = c.storage.write

    def write(path, data):
        original(path, data)
        if c.storage.writes == 2:
            c.lock.close(c.owner)

    c.storage.write = write
    with pytest.raises(module().AccessEpochTlsError):
        await c.materializer.execute(action, ticket)
    assert c.storage.writes == 2


async def test_db_owner_change_after_materialization_prevents_assets_result(tls_case):
    c = tls_case
    action, ticket = await reserve(c)
    original = c.storage.write

    def write(path, data):
        original(path, data)
        if c.storage.writes == 8:
            c.repo.state = replace(c.repo.state, gate_state="open")

    c.storage.write = write
    with pytest.raises(module().AccessEpochTlsError):
        await c.materializer.execute(action, ticket)


async def test_existing_packet_denies_fresh_key_generation_and_is_never_overwritten(tls_case):
    c = tls_case
    action, ticket = await reserve(c)
    packet = str(
        c.journal.root
        / ".local-data/access-epoch/private/tls"
        / c.epoch.binding.access_epoch_id
        / "bundle.dpapi"
    )
    c.storage.files[packet] = b"synthetic-existing-protected-packet"
    with pytest.raises(module().AccessEpochTlsError):
        await c.materializer.execute(action, ticket)
    assert c.storage.files[packet] == b"synthetic-existing-protected-packet"
    assert c.storage.writes == 1  # Journal intent only; no TLS generation or overwrite.


async def test_unknown_pending_action_cannot_use_a_fresh_generation_ticket(tls_case):
    c = tls_case
    action, ticket = await reserve(c)
    unknown = replace(
        c.repo.state.actions[-1], outcome="unknown", event_sequence=action.sequence + 1
    )
    c.repo.state = replace(c.repo.state, actions=(*c.repo.state.actions[:-1], unknown))
    with pytest.raises(module().AccessEpochTlsError):
        await c.materializer.execute(action, ticket)
    assert c.storage.writes == 0 and not c.storage.plain


async def test_protected_bundle_from_another_action_is_not_reconciled(tls_case):
    c = tls_case
    action, ticket = await reserve(c)
    await c.materializer.execute(action, ticket)
    packet = next(p for p in c.storage.files if p.endswith("bundle.dpapi"))
    encrypted = c.storage.files[packet]
    wire = json.loads(c.storage.unprotect(encrypted))
    wire["binding"]["action_id"] = str(uuid4())
    c.storage.files[packet] = c.storage.protect(json.dumps(wire).encode())
    writes = c.storage.writes
    with pytest.raises(module().AccessEpochTlsError):
        await c.materializer.reconcile(action)
    assert writes == c.storage.writes


async def test_write_readback_mismatch_stops_before_next_file(tls_case):
    c = tls_case
    action, ticket = await reserve(c)
    original = c.storage.write

    def write(path, data):
        original(path, data)
        if c.storage.writes == 3:
            c.storage.files[path] = b"synthetic-corrupted-leaf"

    c.storage.write = write
    with pytest.raises(module().AccessEpochTlsError, match="^tls_preparation_unknown$"):
        await c.materializer.execute(action, ticket)
    assert c.storage.writes == 3


async def test_committed_unknown_with_result_manifest_can_read_complete_existing_files(tls_case):
    c = tls_case
    action, ticket = await reserve(c)
    prepared = await c.materializer.execute(action, ticket)
    unknown = replace(
        c.repo.state.actions[-1],
        outcome="unknown",
        manifest_json="{}",
        event_sequence=action.sequence + 1,
    )
    c.repo.state = replace(c.repo.state, actions=(*c.repo.state.actions[:-1], unknown))
    writes = c.storage.writes
    recovered = await c.materializer.reconcile(action)
    assert recovered.manifest_json == prepared.manifest_json and writes == c.storage.writes
