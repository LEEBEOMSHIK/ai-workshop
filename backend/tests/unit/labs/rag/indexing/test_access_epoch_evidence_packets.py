"""Pure packet projection cannot mint native execution/source authority."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_evidence_packets import (
    _assemble_manifest_packets,
    _FinalManifestPackets,
    _settlement_manifest,
)
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_native import (
    OriginalDeploymentObservation,
    OriginalImageReference,
)
from ai_workshop.labs.rag.indexing.access_epoch_repository import (
    AccessEpochReadback,
    ActionReadback,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    MANIFEST_NAMES,
    AccessEpochBinding,
    ControlExpectedIdentity,
    OriginalDeploymentIdentity,
    OriginalTargetOrigin,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import (
    AliasOperationSnapshot,
    FrozenAliasClaim,
)


def values():
    now = datetime(2020, 1, 1, tzinfo=UTC)
    snapshot = AliasOperationSnapshot(
        uuid4(), "store", "cluster", "alias", uuid4(), uuid4(), ("index",), now, "dispatching"
    )
    claim = FrozenAliasClaim(snapshot, uuid4(), uuid4(), 1)
    originals = tuple(
        (name, canonical_json({"kind": name}))
        for name in (
            "daemon_identity",
            "original_volume_identity",
            "protected_mount",
            "protected_image",
            "old_config",
            "old_deployment",
        )
    )
    digests = {name: sha256(raw.encode()).hexdigest() for name, raw in originals}
    identity = OriginalDeploymentIdentity(
        digests["daemon_identity"],
        "a" * 64,
        "cluster",
        "node",
        "old",
        digests["original_volume_identity"],
        digests["protected_mount"],
        digests["protected_image"],
        digests["old_config"],
        digests["old_deployment"],
        now,
    )
    epoch = PreparedAccessEpoch(AccessEpochBinding(claim, str(uuid4()), str(uuid4()), 1), identity)
    generation = str(uuid4())
    rows = tuple(
        ActionReadback(
            ReservedCutoverAction(
                uuid4(),
                UUID(epoch.binding.execution_id),
                i * 2 + 1,
                kind,
                ControlExpectedIdentity("{}", i * 2),
                generation,
            ),
            "settled",
            canonical_json({"kind": kind.value}),
            now + timedelta(seconds=i + 1),
            i * 2 + 2,
        )
        for i, kind in enumerate(CUTOVER_ORDER)
    )
    state = AccessEpochReadback(
        epoch,
        "secured_started",
        rows,
        "open",
        "frozen",
        None,
        now + timedelta(seconds=2),
        generation,
    )
    original = OriginalDeploymentObservation(
        uuid4(),
        snapshot.sha256,
        identity,
        OriginalTargetOrigin("a" * 64, identity.daemon_sha256, "/original", now),
        OriginalImageReference("sha256:" + "b" * 64, "c" * 64, "amd64"),
        "cluster-name",
        "172.18.0.2",
        "172.18.0.0/16",
        "172.18.0.1",
        originals,
    )
    return epoch, state, original


def settlement(epoch, state):
    return _settlement_manifest(
        epoch, state, state.actions[-1].manifest_json, state.actions[-1].observed_at
    )


def test_complete_packet_preserves_all_stored_manifests_and_sample_times():
    epoch, state, _ = values()
    raw = settlement(epoch, state)
    wire = json.loads(raw)
    assert raw == canonical_json(wire)
    assert wire["execution_id"] == epoch.binding.execution_id
    assert len(wire["actions"]) == 12
    for packet, row in zip(wire["actions"], state.actions, strict=True):
        assert packet["manifest_json"] == row.manifest_json
        assert packet["manifest_sha256"] == sha256(row.manifest_json.encode()).hexdigest()
        assert packet["observed_at"] == row.observed_at.isoformat(timespec="microseconds")
        assert packet["preceding_sequence"] == row.action.expected.preceding_sequence


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "extra",
        "reordered",
        "pending",
        "unknown",
        "wrong_execution",
        "wrong_generation",
        "duplicate_id",
        "zero_id",
        "bool_sequence",
        "gap_sequence",
        "wrong_preceding",
        "bool_event",
        "event_not_completed",
        "event_gap",
        "backward_time",
        "naive_time",
        "future_time",
        "no_manifest",
        "noncanonical",
        "duplicate_json",
        "nan_json",
        "array_json",
        "oversize_json",
        "wrong_epoch",
        "wrong_phase",
        "closed",
        "gate_open",
        "receipt",
        "verify_body",
        "verify_time",
    ],
)
def test_invalid_settlement_never_becomes_complete_packet(fault):
    epoch, state, _ = values()
    rows = list(state.actions)
    row = rows[1]
    changes = {}
    if fault == "missing":
        rows.pop()
    elif fault == "extra":
        rows.append(rows[-1])
    elif fault == "reordered":
        rows[1], rows[2] = rows[2], rows[1]
    elif fault in {"pending", "unknown"}:
        rows[1] = replace(row, outcome=fault)
    elif fault in {
        "wrong_execution",
        "wrong_generation",
        "duplicate_id",
        "zero_id",
        "bool_sequence",
        "gap_sequence",
        "wrong_preceding",
    }:
        action_changes = {
            "wrong_execution": {"execution_id": uuid4()},
            "wrong_generation": {"executor_generation": str(uuid4())},
            "duplicate_id": {"action_id": rows[0].action.action_id},
            "zero_id": {"action_id": UUID(int=0)},
            "bool_sequence": {"sequence": True},
            "gap_sequence": {"sequence": 99},
            "wrong_preceding": {"expected": ControlExpectedIdentity("{}", 99)},
        }[fault]
        rows[1] = replace(row, action=replace(row.action, **action_changes))
    elif fault in {"bool_event", "event_not_completed", "event_gap"}:
        rows[1] = replace(
            row,
            event_sequence={
                "bool_event": True,
                "event_not_completed": row.action.sequence,
                "event_gap": 99,
            }[fault],
        )
    elif fault in {"backward_time", "naive_time", "future_time"}:
        rows[1] = replace(
            row,
            observed_at={
                "backward_time": rows[0].observed_at - timedelta(seconds=1),
                "naive_time": row.observed_at.replace(tzinfo=None),
                "future_time": datetime.now(UTC) + timedelta(days=2),
            }[fault],
        )
    elif fault in {
        "no_manifest",
        "noncanonical",
        "duplicate_json",
        "nan_json",
        "array_json",
        "oversize_json",
    }:
        rows[1] = replace(
            row,
            manifest_json={
                "no_manifest": None,
                "noncanonical": '{"x": 1}',
                "duplicate_json": '{"x":1,"x":2}',
                "nan_json": '{"x":NaN}',
                "array_json": "[]",
                "oversize_json": canonical_json({"x": "a" * (4 * 1024 * 1024)}),
            }[fault],
        )
    elif fault == "wrong_epoch":
        changes["prepared"] = replace(
            epoch, binding=replace(epoch.binding, access_epoch_id=str(uuid4()))
        )
    elif fault == "wrong_phase":
        changes["phase"] = "verified"
    elif fault == "closed":
        changes["operation_state"] = "closed"
    elif fault == "gate_open":
        changes["gate_state"] = "open"
    elif fault == "receipt":
        changes["receipt"] = object()
    changed = replace(state, actions=tuple(rows), **changes)
    verify_manifest = state.actions[-1].manifest_json
    verify_at = state.actions[-1].observed_at
    if fault == "verify_body":
        verify_manifest = '{"changed":true}'
    if fault == "verify_time":
        verify_at += timedelta(seconds=1)
    with pytest.raises(ValueError, match="native_evidence_packet_denied"):
        _settlement_manifest(epoch, changed, verify_manifest, verify_at)


def final_packets():
    return _FinalManifestPackets(
        **{
            name: canonical_json({"kind": name})
            for name in (
                "new_config",
                "new_deployment",
                "route_policy",
                "tls_public_ca",
                "auth_policy",
                "credential_deployment",
                "deployment_history",
                "control_settlement",
            )
        }
    )


def test_fourteen_packets_preserve_exact_original_and_final_public_strings():
    epoch, _, original = values()
    final = final_packets()
    packets = _assemble_manifest_packets(original, epoch, final)
    assert tuple(name for name, _ in packets) == tuple(sorted(MANIFEST_NAMES))
    assert all(dict(packets)[name] == raw for name, raw in original.manifest_jsons)
    assert dict(packets)["control_settlement"] == final.control_settlement
    assert not hasattr(final, "assert_issued")


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "foreign_name",
        "changed_original",
        "changed_snapshot",
        "changed_identity",
        "bad_final",
        "subclass_final",
    ],
)
def test_incorrect_original_or_packet_shape_is_refused(fault):
    epoch, _, original = values()
    final = final_packets()
    pairs = list(original.manifest_jsons)
    if fault == "missing":
        pairs.pop()
    elif fault == "duplicate":
        pairs[-1] = pairs[0]
    elif fault == "foreign_name":
        pairs[-1] = ("other", pairs[-1][1])
    elif fault == "changed_original":
        pairs[0] = (pairs[0][0], '{"changed":true}')
    elif fault == "changed_snapshot":
        original = replace(original, snapshot_sha256="d" * 64)
    elif fault == "changed_identity":
        original = replace(original, identity=replace(original.identity, container_id="e" * 64))
    elif fault == "bad_final":
        final = replace(final, route_policy="null")
    elif fault == "subclass_final":

        class Foreign(_FinalManifestPackets):
            pass

        final = Foreign(**{name: getattr(final, name) for name in final.__dataclass_fields__})
    original = replace(original, manifest_jsons=tuple(pairs))
    with pytest.raises(ValueError, match="native_evidence_packet_denied"):
        _assemble_manifest_packets(original, epoch, final)


def test_settled_unknown_history_keeps_actual_event_gap_not_synthetic_positions():
    epoch, state, _ = values()
    rows = []
    for i, row in enumerate(state.actions):
        action = (
            row.action
            if i == 0
            else replace(
                row.action,
                sequence=row.action.sequence + 1,
                expected=replace(
                    row.action.expected,
                    preceding_sequence=row.action.expected.preceding_sequence + 1,
                ),
            )
        )
        rows.append(replace(row, action=action, event_sequence=row.event_sequence + 1))
    changed = replace(state, actions=tuple(rows))
    packet = json.loads(settlement(epoch, changed))
    assert packet["actions"][0]["event_sequence"] == 3
    assert packet["actions"][1]["sequence"] == 4
    assert packet["actions"][-1]["event_sequence"] == 25


@pytest.mark.parametrize("field", ["nonce", "observed_at"])
def test_subclass_primitives_never_inherit_exact_packet_types(field):
    epoch, state, original = values()
    if field == "nonce":

        class UUIDCopy(UUID):
            pass

        changed = replace(original, nonce=UUIDCopy(str(original.nonce)))
        with pytest.raises(ValueError, match="native_evidence_packet_denied"):
            _assemble_manifest_packets(changed, epoch, final_packets())
    else:

        class DateCopy(datetime):
            pass

        row = state.actions[-1]
        altered = DateCopy.fromtimestamp(row.observed_at.timestamp(), tz=UTC)
        with pytest.raises(ValueError, match="native_evidence_packet_denied"):
            _settlement_manifest(epoch, state, row.manifest_json, altered)


@pytest.mark.parametrize("phase", ["secured_started", "verified", "receipted"])
def test_stored_projection_is_phase_neutral_but_active_projection_stays_guarded(phase):
    from ai_workshop.labs.rag.indexing import access_epoch_evidence_packets as packets

    epoch, state, _ = values()
    expected = settlement(epoch, state)
    changed = replace(state, phase=phase)
    assert packets._stored_control_manifest(epoch, changed) == expected
    if phase != "secured_started":
        with pytest.raises(ValueError, match="native_evidence_packet_denied"):
            settlement(epoch, changed)


def test_stored_projection_never_turns_pending_rows_into_completed_actions():
    from ai_workshop.labs.rag.indexing import access_epoch_evidence_packets as packets

    epoch, state, _ = values()
    changed = replace(
        state,
        phase="verified",
        actions=state.actions[:-1] + (replace(state.actions[-1], outcome="pending"),),
    )
    with pytest.raises(ValueError, match="native_evidence_packet_denied"):
        packets._stored_control_manifest(epoch, changed)
