"""Bounded immutable recovery data. A proof is minted only by a trusted port."""

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from ai_workshop.labs.rag.indexing.access_epoch_types import LocalAccessEpochTerminationProof

type AliasPhase = Literal["legacy_unknown", "reserved", "dispatching"]
type RecoveryResult = Literal["not_dispatched", "recovered_terminated"]

RECOVERY_ERROR_CODES = frozenset(
    {
        "rag_alias_local_required",
        "rag_alias_actor_denied",
        "rag_alias_operation_missing",
        "rag_alias_binding_mismatch",
        "rag_alias_snapshot_changed",
        "rag_alias_claim_conflict",
        "rag_alias_proof_required",
        "rag_alias_proof_invalid",
        "rag_alias_already_confirmed",
        "rag_alias_operation_closed",
        "rag_alias_operation_open",
        "rag_alias_commit_unknown",
    }
)


class AliasRecoveryError(RuntimeError):
    def __init__(self, code: str) -> None:
        if code not in RECOVERY_ERROR_CODES:
            raise ValueError("Invalid alias recovery code")
        self.code = code
        super().__init__(code)


def utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AliasRecoveryError("rag_alias_proof_invalid")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def digest(value: dict[str, object]) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class AliasOperationSnapshot:
    operation_id: UUID
    store_id: str
    cluster_uuid: str
    alias: str
    indexing_profile_id: UUID
    document_processing_profile_id: UUID
    targets: tuple[str, ...]
    created_at: datetime
    phase: AliasPhase

    @property
    def sha256(self) -> str:
        return digest(
            {
                "operation_id": str(self.operation_id),
                "store_id": self.store_id,
                "cluster_uuid": self.cluster_uuid,
                "alias": self.alias,
                "indexing_profile_id": str(self.indexing_profile_id),
                "document_processing_profile_id": str(self.document_processing_profile_id),
                "targets": list(self.targets),
                "created_at": utc_text(self.created_at),
                "phase": self.phase,
            }
        )


@dataclass(frozen=True, slots=True)
class FrozenAliasClaim:
    snapshot: AliasOperationSnapshot
    request_id: UUID
    actor_id: UUID
    revision: int


@dataclass(frozen=True, slots=True)
class TerminationProof:
    """Allowlisted facts from a controlled local drain, never caller JSON.

    The port must establish trusted endpoint/history, inventory completeness,
    ended process lifetimes, no relaunch, preserved mounts/config, one node and
    a maintained barrier. Timestamps and changed names alone are insufficient.
    """

    request_id: UUID
    operation_id: UUID
    snapshot_sha256: str
    cluster_uuid: str
    container_id: str
    protected_mount_sha256: str
    config_sha256: str
    client_inventory_sha256: str
    deployment_history_sha256: str
    stable_node_id: str
    old_ephemeral_id: str
    new_ephemeral_id: str
    old_jvm_start_at: datetime
    clients_terminated_at: datetime
    server_stopped_at: datetime
    server_started_at: datetime
    new_jvm_start_at: datetime
    verified_at: datetime
    schema_version: int
    proof_kind: Literal["local_single_node_controlled_restart"] = (
        "local_single_node_controlled_restart"
    )

    def validate(self, claim: FrozenAliasClaim) -> None:
        times = (
            self.old_jvm_start_at,
            self.clients_terminated_at,
            self.server_stopped_at,
            self.server_started_at,
            self.new_jvm_start_at,
            self.verified_at,
        )
        for value in times:
            utc_text(value)
        if (
            self.request_id != claim.request_id
            or self.operation_id != claim.snapshot.operation_id
            or self.snapshot_sha256 != claim.snapshot.sha256
            or self.cluster_uuid != claim.snapshot.cluster_uuid
            or self.schema_version != 1
            or type(self.schema_version) is not int
            or self.proof_kind != "local_single_node_controlled_restart"
            or any(
                re.fullmatch(r"[0-9a-f]{64}", value) is None
                for value in (
                    self.container_id,
                    self.snapshot_sha256,
                    self.protected_mount_sha256,
                    self.config_sha256,
                    self.client_inventory_sha256,
                    self.deployment_history_sha256,
                )
            )
            or any(
                re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None
                for value in (
                    self.stable_node_id,
                    self.old_ephemeral_id,
                    self.new_ephemeral_id,
                )
            )
            or self.old_ephemeral_id == self.new_ephemeral_id
            or self.clients_terminated_at < claim.snapshot.created_at
            or self.verified_at > datetime.now(UTC)
            or not (
                self.old_jvm_start_at
                <= self.clients_terminated_at
                < self.server_stopped_at
                < self.server_started_at
                <= self.new_jvm_start_at
                <= self.verified_at
            )
        ):
            raise AliasRecoveryError("rag_alias_proof_invalid")

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


class TerminationProofPort(Protocol):
    async def collect_verified_end(self, claim: FrozenAliasClaim) -> TerminationProof: ...

    async def revalidate(self, claim: FrozenAliasClaim, proof: TerminationProof) -> None:
        """Recheck the live barrier and all protected identities outside DB locks."""
        ...


@dataclass(frozen=True, slots=True)
class AliasRecoveryReceipt:
    request_id: UUID
    operation_id: UUID
    actor_id: UUID
    cluster_uuid: str
    snapshot_sha256: str
    gate_revision: int
    result_code: RecoveryResult
    proof: "TerminationProof | LocalAccessEpochTerminationProof | None"
    proof_sha256: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AliasRecoveryReadback:
    snapshot: AliasOperationSnapshot
    state: str
    result_code: str | None
    gate_state: str
    claim: FrozenAliasClaim | None
    receipt: AliasRecoveryReceipt | None
