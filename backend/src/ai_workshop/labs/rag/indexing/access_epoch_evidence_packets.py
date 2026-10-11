"""Pure public packet projection, never native/source issuance authority.

The backend must validate every actual issuer and per-manifest schema before
calling these functions. Equal DTOs/strings do not establish execution, fresh
observation, termination, credential possession or operational readiness.
"""

import json
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_native import (
    OriginalDeploymentObservation,
    _observation_signature,
)
from ai_workshop.labs.rag.indexing.access_epoch_repository import (
    AccessEpochReadback,
    ActionReadback,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    MANIFEST_NAMES,
    AccessEpochBinding,
    ControlExpectedIdentity,
    CutoverActionKind,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
)

_MAX_PACKET = 4 * 1024 * 1024
_ORIGINAL_DIGESTS = (
    ("daemon_identity", "daemon_sha256"),
    ("original_volume_identity", "volume_sha256"),
    ("protected_mount", "mount_sha256"),
    ("protected_image", "image_sha256"),
    ("old_config", "config_sha256"),
    ("old_deployment", "deployment_sha256"),
)


def _denied() -> ValueError:
    return ValueError("native_evidence_packet_denied")


def _constant(_: str) -> None:
    raise _denied()


def _packet(raw: object) -> str:
    if type(raw) is not str or not 0 < len(raw.encode("utf-8")) <= _MAX_PACKET:
        raise _denied()
    value = json.loads(raw, parse_constant=_constant)
    if (
        type(value) is not dict
        or json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
        != raw
    ):
        raise _denied()
    return raw


def _uuid(value: object) -> str:
    if type(value) is not UUID or value.int == 0:
        raise _denied()
    return str(value)


def _uuid_text(value: object) -> str:
    if type(value) is not str or _uuid(UUID(value)) != value:
        raise _denied()
    return value


def _time(value: object) -> str:
    if (
        type(value) is not datetime
        or value.utcoffset() != timedelta(0)
        or value > datetime.now(UTC)
    ):
        raise _denied()
    return value.isoformat(timespec="microseconds")


def _epoch(epoch: PreparedAccessEpoch) -> None:
    if (
        type(epoch) is not PreparedAccessEpoch
        or type(epoch.binding) is not AccessEpochBinding
        or type(epoch.binding.ordinal) is not int
        or epoch.binding.ordinal <= 0
    ):
        raise _denied()
    _uuid_text(epoch.binding.access_epoch_id)
    _uuid_text(epoch.binding.execution_id)


@dataclass(frozen=True, slots=True)
class _FinalManifestPackets:
    """Plain already-validated public strings; deliberately not a capability."""

    new_config: str
    new_deployment: str
    route_policy: str
    tls_public_ca: str
    auth_policy: str
    credential_deployment: str
    deployment_history: str
    control_settlement: str


def _stored_control_manifest(epoch: PreparedAccessEpoch, state: AccessEpochReadback) -> str:
    """Phase-neutral stored-row data only; grants no phase or source authority."""
    try:
        _epoch(epoch)
        if (
            type(state) is not AccessEpochReadback
            or state.prepared != epoch
            or type(state.actions) is not tuple
            or len(state.actions) != len(CUTOVER_ORDER)
        ):
            raise _denied()
        generation = _uuid_text(state.executor_generation)
        expected_execution = epoch.binding.execution_id
        previous_event = 0
        previous_time: datetime | None = None
        seen: set[str] = set()
        packets: list[dict[str, object]] = []
        for kind, row in zip(CUTOVER_ORDER, state.actions, strict=True):
            if type(row) is not ActionReadback or type(row.action) is not ReservedCutoverAction:
                raise _denied()
            action = row.action
            action_id = _uuid(action.action_id)
            if (
                action_id in seen
                or _uuid(action.execution_id) != expected_execution
                or action.executor_generation != generation
                or type(action.executor_generation) is not str
                or type(action.kind) is not CutoverActionKind
                or action.kind != kind
                or type(action.sequence) is not int
                or action.sequence != previous_event + 1
                or type(action.expected) is not ControlExpectedIdentity
                or type(action.expected.preceding_sequence) is not int
                or action.expected.preceding_sequence != previous_event
                or type(row.event_sequence) is not int
                or row.event_sequence <= action.sequence
                or type(row.outcome) is not str
                or row.outcome != "settled"
            ):
                raise _denied()
            _packet(action.expected.identity_json)
            manifest = _packet(row.manifest_json)
            sampled = _time(row.observed_at)
            if previous_time is not None and row.observed_at < previous_time:
                raise _denied()
            seen.add(action_id)
            previous_event, previous_time = row.event_sequence, row.observed_at
            packets.append(
                {
                    "action_id": action_id,
                    "kind": kind.value,
                    "sequence": action.sequence,
                    "preceding_sequence": action.expected.preceding_sequence,
                    "event_sequence": row.event_sequence,
                    "outcome": "settled",
                    "observed_at": sampled,
                    "manifest_json": manifest,
                    "manifest_sha256": sha256(manifest.encode()).hexdigest(),
                }
            )
        return _packet(
            canonical_json(
                {
                    "schema_version": 1,
                    "epoch_id": epoch.binding.access_epoch_id,
                    "execution_id": expected_execution,
                    "executor_generation": generation,
                    "actions": packets,
                }
            )
        )
    except Exception:
        raise _denied() from None


def _settlement_manifest(
    epoch: PreparedAccessEpoch,
    state: AccessEpochReadback,
    verify_manifest: str,
    verify_at: datetime,
) -> str:
    """Project active settled rows after actual owner/issuer checks by backend."""
    try:
        if (
            type(state) is not AccessEpochReadback
            or state.phase != "secured_started"
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
        ):
            raise _denied()
        manifest = _stored_control_manifest(epoch, state)
        if _packet(verify_manifest) != state.actions[-1].manifest_json or _time(verify_at) != _time(
            state.actions[-1].observed_at
        ):
            raise _denied()
        return manifest
    except Exception:
        raise _denied() from None


def _assemble_manifest_packets(
    original: OriginalDeploymentObservation,
    epoch: PreparedAccessEpoch,
    final: _FinalManifestPackets,
) -> tuple[tuple[str, str], ...]:
    """Preserve the same six original strings; do not manufacture source origin."""
    try:
        _epoch(epoch)
        if (
            type(original) is not OriginalDeploymentObservation
            or type(final) is not _FinalManifestPackets
            or original.identity != epoch.original
            or original.snapshot_sha256 != epoch.binding.claim.snapshot.sha256
            or original.origin.container_id != epoch.original.container_id
            or original.origin.daemon_sha256 != epoch.original.daemon_sha256
        ):
            raise _denied()
        _observation_signature(original)
        originals = dict(original.manifest_jsons)
        if len(original.manifest_jsons) != len(_ORIGINAL_DIGESTS) or set(originals) != {
            name for name, _ in _ORIGINAL_DIGESTS
        }:
            raise _denied()
        for name, digest_field in _ORIGINAL_DIGESTS:
            raw = _packet(originals[name])
            if sha256(raw.encode()).hexdigest() != getattr(epoch.original, digest_field):
                raise _denied()
        result = originals | {f.name: _packet(getattr(final, f.name)) for f in fields(final)}
        if set(result) != MANIFEST_NAMES:
            raise _denied()
        return tuple((name, result[name]) for name in sorted(MANIFEST_NAMES))
    except Exception:
        raise _denied() from None
