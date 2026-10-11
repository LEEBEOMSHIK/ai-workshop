"""Exact immutable access-epoch evidence; never an operator attestation."""

import json
import re
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import UUID

from ai_workshop.labs.rag.indexing.alias_recovery_types import (
    AliasRecoveryError,
    FrozenAliasClaim,
    TerminationProof,
    digest,
    utc_text,
)

UUID_FIELDS = frozenset(
    {"request_id", "operation_id", "actor_id", "access_epoch_id", "execution_id"}
)
TIME_FIELDS = frozenset(
    {
        "old_jvm_start_at",
        "old_server_stopped_at",
        "old_container_retired_at",
        "new_server_started_at",
        "new_jvm_start_at",
        "access_verified_at",
        "verified_at",
    }
)
IDENTIFIER_FIELDS = frozenset(
    {
        "store_id",
        "cluster_uuid",
        "stable_node_id",
        "old_ephemeral_id",
        "new_ephemeral_id",
    }
)
MANIFEST_NAMES = frozenset(
    {
        "daemon_identity",
        "original_volume_identity",
        "protected_mount",
        "protected_image",
        "old_config",
        "new_config",
        "old_deployment",
        "new_deployment",
        "route_policy",
        "tls_public_ca",
        "auth_policy",
        "credential_deployment",
        "deployment_history",
        "control_settlement",
    }
)
DIGEST_FIELDS = frozenset(name + "_sha256" for name in MANIFEST_NAMES) | {
    "snapshot_sha256",
    "old_container_id",
    "new_container_id",
}
V2_FIELDS = (
    UUID_FIELDS
    | TIME_FIELDS
    | IDENTIFIER_FIELDS
    | DIGEST_FIELDS
    | {
        "schema_version",
        "proof_kind",
        "gate_revision",
        "minimum_access_epoch",
    }
)


def invalid() -> AliasRecoveryError:
    return AliasRecoveryError("rag_alias_proof_invalid")


def canonical_json(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def strict_utc(value: object) -> datetime:
    if type(value) is not str:
        raise invalid()
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise invalid() from None
    if result.utcoffset() != timedelta(0) or result.isoformat(timespec="microseconds") != value:
        raise invalid()
    return result


@dataclass(frozen=True, slots=True)
class AccessEpochBinding:
    claim: FrozenAliasClaim
    access_epoch_id: str
    execution_id: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class VerifiedAccessEpoch:
    binding: AccessEpochBinding
    previous_floor: int
    proof_facts_json: str
    manifests: tuple[tuple[str, str], ...]
    stopped_action_sequence: int
    retired_action_sequence: int


@dataclass(frozen=True, slots=True)
class OriginalTargetOrigin:
    container_id: str
    daemon_sha256: str
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OriginalDeploymentIdentity:
    daemon_sha256: str
    container_id: str
    cluster_uuid: str
    stable_node_id: str
    ephemeral_id: str
    volume_sha256: str
    mount_sha256: str
    image_sha256: str
    config_sha256: str
    deployment_sha256: str
    jvm_start_at: datetime


@dataclass(frozen=True, slots=True)
class PreparedAccessEpoch:
    binding: AccessEpochBinding
    original: OriginalDeploymentIdentity


@dataclass(frozen=True, slots=True)
class AccessEpochFloor:
    store_id: str
    cluster_uuid: str
    ordinal: int
    access_epoch_id: str
    container_id: str
    stable_node_id: str
    route_sha256: str
    auth_sha256: str
    config_sha256: str
    ca_sha256: str


class CutoverActionKind(StrEnum):
    STOP_REGISTERED_APPS = "stop_registered_apps"
    STOP_OLD = "stop_old"
    RETIRE_OLD = "retire_old"
    PREPARE_TLS = "prepare_tls"
    START_BOOTSTRAP = "start_bootstrap"
    BOOTSTRAP_ADMIN = "bootstrap_admin"
    REVOKE_HISTORICAL = "revoke_historical"
    ISSUE_ROLE_KEY = "issue_role_key"
    STOP_BOOTSTRAP = "stop_bootstrap"
    RETIRE_BOOTSTRAP = "retire_bootstrap"
    START_SECURED = "start_secured"
    START_REGISTERED_APPS = "start_registered_apps"
    VERIFY_ACCESS = "verify_access"


type ActionOutcome = Literal["pending", "settled", "unknown"]


@dataclass(frozen=True, slots=True)
class ControlExpectedIdentity:
    identity_json: str
    preceding_sequence: int


@dataclass(frozen=True, slots=True)
class ReservedCutoverAction:
    action_id: UUID
    execution_id: UUID
    sequence: int
    kind: CutoverActionKind
    expected: ControlExpectedIdentity
    executor_generation: str


@dataclass(frozen=True, slots=True)
class ControlSettlement:
    action_id: UUID
    execution_id: UUID
    executor_generation: str
    outcome: ActionOutcome
    manifest_json: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class LocalAccessEpochTerminationProof:
    request_id: UUID
    operation_id: UUID
    actor_id: UUID
    access_epoch_id: UUID
    execution_id: UUID
    gate_revision: int
    minimum_access_epoch: int
    store_id: str
    cluster_uuid: str
    stable_node_id: str
    old_ephemeral_id: str
    new_ephemeral_id: str
    snapshot_sha256: str
    old_container_id: str
    new_container_id: str
    daemon_identity_sha256: str
    original_volume_identity_sha256: str
    protected_mount_sha256: str
    protected_image_sha256: str
    old_config_sha256: str
    new_config_sha256: str
    old_deployment_sha256: str
    new_deployment_sha256: str
    route_policy_sha256: str
    tls_public_ca_sha256: str
    auth_policy_sha256: str
    credential_deployment_sha256: str
    deployment_history_sha256: str
    control_settlement_sha256: str
    old_jvm_start_at: datetime
    old_server_stopped_at: datetime
    old_container_retired_at: datetime
    new_server_started_at: datetime
    new_jvm_start_at: datetime
    access_verified_at: datetime
    verified_at: datetime
    schema_version: int = 2
    proof_kind: Literal["local_single_node_access_epoch"] = "local_single_node_access_epoch"

    def facts(self) -> dict[str, object]:
        return {
            key: str(value)
            if isinstance(value, UUID)
            else utc_text(value)
            if isinstance(value, datetime)
            else value
            for key, value in asdict(self).items()
        }

    @property
    def sha256(self) -> str:
        return digest(self.facts())

    def validate(
        self,
        claim: FrozenAliasClaim,
        epoch: VerifiedAccessEpoch,
        *,
        now: datetime,
    ) -> None:
        # Validate direct object instances too; callers cannot bypass strict decoding.
        if (
            type(self) is not LocalAccessEpochTerminationProof
            or type(epoch) is not VerifiedAccessEpoch
        ):
            raise invalid()
        if any(
            type(getattr(self, name)) is not datetime
            or getattr(self, name).utcoffset() != timedelta(0)
            for name in TIME_FIELDS
        ):
            raise invalid()
        _validate_v2(self.facts())
        facts = self.facts()
        binding = epoch.binding
        if (
            binding.claim != claim
            or type(binding.ordinal) is not int
            or self.request_id != claim.request_id
            or self.operation_id != claim.snapshot.operation_id
            or self.actor_id != claim.actor_id
            or self.gate_revision != claim.revision
            or self.snapshot_sha256 != claim.snapshot.sha256
            or self.store_id != claim.snapshot.store_id
            or self.cluster_uuid != claim.snapshot.cluster_uuid
            or str(self.access_epoch_id) != binding.access_epoch_id
            or str(self.execution_id) != binding.execution_id
            or self.minimum_access_epoch != binding.ordinal
            or type(epoch.previous_floor) is not int
            or not 0 <= epoch.previous_floor < binding.ordinal
            or canonical_json(facts) != epoch.proof_facts_json
            or now.utcoffset() != timedelta(0)
            or self.verified_at > now
            or self.old_server_stopped_at < claim.snapshot.created_at
            or type(epoch.stopped_action_sequence) is not int
            or type(epoch.retired_action_sequence) is not int
            or not 0 < epoch.stopped_action_sequence < epoch.retired_action_sequence
        ):
            raise invalid()
        if (
            len(epoch.manifests) != len(MANIFEST_NAMES)
            or {n for n, _ in epoch.manifests} != MANIFEST_NAMES
        ):
            raise invalid()
        for name, payload in epoch.manifests:
            try:
                parsed = json.loads(payload)
            except (TypeError, ValueError):
                raise invalid() from None
            if type(parsed) is not dict or canonical_json(parsed) != payload:
                raise invalid()
            if sha256(payload.encode()).hexdigest() != facts[name + "_sha256"]:
                raise invalid()


type AliasTerminationProof = TerminationProof | LocalAccessEpochTerminationProof


def _validate_v2(facts: dict[str, object]) -> None:
    if type(facts) is not dict or set(facts) != V2_FIELDS:
        raise invalid()
    for name in UUID_FIELDS:
        value = facts[name]
        if type(value) is not str:
            raise invalid()
        try:
            if str(UUID(value)) != value:
                raise invalid()
        except ValueError:
            raise invalid() from None
    for name in DIGEST_FIELDS:
        value = facts[name]
        if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise invalid()
    for name in IDENTIFIER_FIELDS:
        value = facts[name]
        size = 80 if name == "store_id" else 128
        pattern = r"[a-z][a-z0-9_]{0,79}" if name == "store_id" else rf"[A-Za-z0-9_-]{{1,{size}}}"
        if type(value) is not str or re.fullmatch(pattern, value) is None:
            raise invalid()
    if (
        type(facts["schema_version"]) is not int
        or facts["schema_version"] != 2
        or type(facts["proof_kind"]) is not str
        or facts["proof_kind"] != "local_single_node_access_epoch"
        or any(
            type(facts[n]) is not int or cast(int, facts[n]) <= 0
            for n in ("gate_revision", "minimum_access_epoch")
        )
        or facts["old_container_id"] == facts["new_container_id"]
        or facts["old_ephemeral_id"] == facts["new_ephemeral_id"]
    ):
        raise invalid()
    times = {name: strict_utc(facts[name]) for name in TIME_FIELDS}
    if not (
        times["old_jvm_start_at"]
        <= times["old_server_stopped_at"]
        <= times["old_container_retired_at"]
        < times["new_server_started_at"]
        <= times["new_jvm_start_at"]
        <= times["access_verified_at"]
        <= times["verified_at"]
    ):
        raise invalid()


def decode_termination_proof(facts: dict[str, object]) -> AliasTerminationProof:
    """For trusted persisted records only. This function is not a CLI input path."""
    if type(facts) is not dict or type(facts.get("schema_version")) is not int:
        raise invalid()
    if facts["schema_version"] == 2:
        _validate_v2(facts)
        values: dict[str, Any] = dict(facts)
        for name in UUID_FIELDS:
            values[name] = UUID(cast(str, facts[name]))
        for name in TIME_FIELDS:
            values[name] = strict_utc(facts[name])
        return LocalAccessEpochTerminationProof(**values)
    if facts["schema_version"] == 1 and set(facts) == {f.name for f in fields(TerminationProof)}:
        from ai_workshop.labs.rag.indexing.alias_recovery_repository import proof_from_facts

        if facts.get("proof_kind") != "local_single_node_controlled_restart":
            raise invalid()
        return proof_from_facts(facts)
    raise invalid()
