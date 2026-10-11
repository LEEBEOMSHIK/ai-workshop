"""Short independent transactions; never acquire source/profile/build locks."""

from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord
from ai_workshop.labs.rag.indexing.alias_journal import lock_cluster_gate
from ai_workshop.labs.rag.indexing.alias_models import (
    AliasClusterGateRecord,
    AliasOperationRecord,
    AliasRecoveryReceiptRecord,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import (
    AliasOperationSnapshot,
    AliasPhase,
    AliasRecoveryError,
    AliasRecoveryReadback,
    AliasRecoveryReceipt,
    FrozenAliasClaim,
    RecoveryResult,
    TerminationProof,
    digest,
)
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, canonical_recovery_targets
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding
from ai_workshop.labs.rag.models.document_processing import (
    index_namespace_document_processing_profile_id,
)
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord


class AliasRecoveryRepositoryPort(Protocol):
    async def preview(self, operation_id: UUID, actor_id: UUID) -> AliasOperationSnapshot: ...
    async def freeze(
        self, operation_id: UUID, actor_id: UUID, request_id: UUID, snapshot_sha256: str
    ) -> FrozenAliasClaim: ...
    async def readback(
        self, operation_id: UUID, actor_id: UUID, request_id: UUID
    ) -> AliasRecoveryReadback: ...
    async def close(
        self, claim: FrozenAliasClaim, result: RecoveryResult, proof: TerminationProof | None
    ) -> AliasRecoveryReceipt: ...
    async def release(self, claim: FrozenAliasClaim) -> None: ...


def snapshot(row: AliasOperationRecord) -> AliasOperationSnapshot:
    if row.phase not in {"legacy_unknown", "reserved", "dispatching"}:
        raise AliasRecoveryError("rag_alias_snapshot_changed")
    if tuple(sorted(set(row.targets))) != tuple(row.targets):
        raise AliasRecoveryError("rag_alias_snapshot_changed")
    return AliasOperationSnapshot(
        row.id,
        row.store_id,
        row.cluster_uuid,
        row.alias,
        row.indexing_profile_id,
        row.document_processing_profile_id,
        tuple(row.targets),
        row.created_at,
        cast(AliasPhase, row.phase),
    )


def proof_from_facts(facts: dict[str, object]) -> TerminationProof:
    """Decode trusted persisted allowlisted facts, never an operator input."""
    try:
        return TerminationProof(
            request_id=UUID(str(facts["request_id"])),
            operation_id=UUID(str(facts["operation_id"])),
            snapshot_sha256=str(facts["snapshot_sha256"]),
            cluster_uuid=str(facts["cluster_uuid"]),
            container_id=str(facts["container_id"]),
            protected_mount_sha256=str(facts["protected_mount_sha256"]),
            config_sha256=str(facts["config_sha256"]),
            client_inventory_sha256=str(facts["client_inventory_sha256"]),
            deployment_history_sha256=str(facts["deployment_history_sha256"]),
            stable_node_id=str(facts["stable_node_id"]),
            old_ephemeral_id=str(facts["old_ephemeral_id"]),
            new_ephemeral_id=str(facts["new_ephemeral_id"]),
            old_jvm_start_at=datetime.fromisoformat(str(facts["old_jvm_start_at"])),
            clients_terminated_at=datetime.fromisoformat(str(facts["clients_terminated_at"])),
            server_stopped_at=datetime.fromisoformat(str(facts["server_stopped_at"])),
            server_started_at=datetime.fromisoformat(str(facts["server_started_at"])),
            new_jvm_start_at=datetime.fromisoformat(str(facts["new_jvm_start_at"])),
            verified_at=datetime.fromisoformat(str(facts["verified_at"])),
            schema_version=cast(int, facts["schema_version"]),
        )
    except (KeyError, TypeError, ValueError):
        raise AliasRecoveryError("rag_alias_proof_invalid") from None


def receipt(row: AliasRecoveryReceiptRecord) -> AliasRecoveryReceipt:
    from ai_workshop.labs.rag.indexing.access_epoch_types import decode_termination_proof

    proof = (
        decode_termination_proof(row.proof) if row.result_code == "recovered_terminated" else None
    )
    return AliasRecoveryReceipt(
        row.request_id,
        row.operation_id,
        row.actor_id,
        row.cluster_uuid,
        row.snapshot_sha256,
        row.gate_revision,
        cast(RecoveryResult, row.result_code),
        proof,
        row.proof_sha256,
        row.created_at,
    )


class SqlAlchemyAliasRecoveryRepository:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], binding: IndexBinding, index_prefix: str
    ) -> None:
        self.sessions, self.binding, self.index_prefix = sessions, binding, index_prefix

    async def _canonical(self, session: AsyncSession, row: AliasOperationRecord) -> None:
        descriptor = IndexDescriptor(1, "cosine")
        alias = descriptor.active_alias(
            self.index_prefix,
            row.indexing_profile_id,
            document_processing_profile_id=index_namespace_document_processing_profile_id(
                row.document_processing_profile_id
            ),
        )
        try:
            valid = alias == row.alias and canonical_recovery_targets(alias, row.targets) == tuple(
                row.targets
            )
        except ValueError:
            valid = False
        if not valid:
            raise AliasRecoveryError("rag_alias_binding_mismatch")
        if row.state == "closed":
            # Immutable receipts remain readable after ordinary profile/build
            # retirement; live membership is required before any open recovery.
            return
        # These are immutable identity reads, not locks or FKs. MVCC SELECTs never
        # acquire caller-owned source/profile/build row locks in this journal.
        for profile_id, kind in (
            (row.indexing_profile_id, "indexing"),
            (row.document_processing_profile_id, "document_processing"),
        ):
            actual = await session.scalar(
                select(ProfileRecord.kind).where(ProfileRecord.id == profile_id)
            )
            if actual != kind:
                raise AliasRecoveryError("rag_alias_binding_mismatch")
        for name in row.targets:
            build_id = UUID(name[-36:])  # Canonical target validation above owns its grammar.
            member = await session.scalar(
                select(RagIndexBuildRecord.id).where(
                    RagIndexBuildRecord.id == build_id,
                    RagIndexBuildRecord.indexing_profile_id == row.indexing_profile_id,
                    RagIndexBuildRecord.document_processing_profile_id
                    == row.document_processing_profile_id,
                    RagIndexBuildRecord.index_name == name,
                )
            )
            if member is None:
                raise AliasRecoveryError("rag_alias_binding_mismatch")

    async def _owner(self, session: AsyncSession, actor_id: UUID) -> None:
        actor = await session.scalar(
            select(UserRecord)
            .where(UserRecord.id == actor_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if actor is None or not actor.is_active or actor.role != UserRole.OWNER:
            raise AliasRecoveryError("rag_alias_actor_denied")

    async def _operation(
        self, session: AsyncSession, operation_id: UUID, *, lock: bool = False
    ) -> AliasOperationRecord:
        statement = select(AliasOperationRecord).where(AliasOperationRecord.id == operation_id)
        if lock:
            statement = statement.with_for_update()
        row = await session.scalar(statement.execution_options(populate_existing=True))
        if row is None:
            raise AliasRecoveryError("rag_alias_operation_missing")
        if (row.store_id, row.cluster_uuid) != (self.binding.store_id, self.binding.cluster_uuid):
            raise AliasRecoveryError("rag_alias_binding_mismatch")
        await self._canonical(session, row)
        return row

    async def _receipt(
        self, session: AsyncSession, request_id: UUID
    ) -> AliasRecoveryReceiptRecord | None:
        value: AliasRecoveryReceiptRecord | None = await session.scalar(
            select(AliasRecoveryReceiptRecord).where(
                AliasRecoveryReceiptRecord.request_id == request_id
            )
        )
        return value

    def _exact_gate(
        self, gate: AliasClusterGateRecord, claim: FrozenAliasClaim, *, frozen: bool = True
    ) -> None:
        if (
            gate.cluster_uuid != claim.snapshot.cluster_uuid
            or gate.request_id != claim.request_id
            or gate.actor_id != claim.actor_id
            or gate.operation_id != claim.snapshot.operation_id
            or gate.snapshot_sha256 != claim.snapshot.sha256
            or gate.revision != claim.revision
            or (frozen and gate.state != "frozen")
        ):
            raise AliasRecoveryError("rag_alias_claim_conflict")

    def _exact_receipt(
        self, stored: AliasRecoveryReceiptRecord, claim: FrozenAliasClaim
    ) -> AliasRecoveryReceipt:
        value = receipt(stored)
        if (
            value.request_id != claim.request_id
            or value.actor_id != claim.actor_id
            or value.operation_id != claim.snapshot.operation_id
            or value.cluster_uuid != claim.snapshot.cluster_uuid
            or value.snapshot_sha256 != claim.snapshot.sha256
            or value.gate_revision != claim.revision
        ):
            raise AliasRecoveryError("rag_alias_claim_conflict")
        return value

    async def preview(self, operation_id: UUID, actor_id: UUID) -> AliasOperationSnapshot:
        try:
            async with self.sessions.begin() as session:
                await self._owner(session, actor_id)
                return snapshot(await self._operation(session, operation_id))
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def freeze(
        self, operation_id: UUID, actor_id: UUID, request_id: UUID, snapshot_sha256: str
    ) -> FrozenAliasClaim:
        try:
            async with self.sessions.begin() as session:
                await self._owner(session, actor_id)
                gate = await lock_cluster_gate(session, self.binding.cluster_uuid)
                row = await self._operation(session, operation_id, lock=True)
                value = snapshot(row)
                if value.sha256 != snapshot_sha256:
                    raise AliasRecoveryError("rag_alias_snapshot_changed")
                stored = await self._receipt(session, request_id)
                if stored is not None:
                    claim = FrozenAliasClaim(value, request_id, actor_id, stored.gate_revision)
                    self._exact_receipt(stored, claim)
                    return claim
                if gate.request_id == request_id:
                    claim = FrozenAliasClaim(value, request_id, actor_id, gate.revision)
                    self._exact_gate(gate, claim, frozen=False)
                    return claim
                if gate.state != "admitted":
                    raise AliasRecoveryError("rag_alias_claim_conflict")
                if row.state != "open":
                    raise AliasRecoveryError("rag_alias_operation_closed")
                gate.state, gate.request_id, gate.actor_id = "frozen", request_id, actor_id
                gate.operation_id, gate.snapshot_sha256 = operation_id, snapshot_sha256
                gate.revision += 1
                return FrozenAliasClaim(value, request_id, actor_id, gate.revision)
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def readback(
        self, operation_id: UUID, actor_id: UUID, request_id: UUID
    ) -> AliasRecoveryReadback:
        try:
            async with self.sessions.begin() as session:
                await self._owner(session, actor_id)
                # A read must not create a gate or assume an unknown freeze committed.
                gate = await session.scalar(
                    select(AliasClusterGateRecord).where(
                        AliasClusterGateRecord.cluster_uuid == self.binding.cluster_uuid
                    )
                )
                row = await self._operation(session, operation_id)
                value, claim, recovered = snapshot(row), None, None
                stored = await self._receipt(session, request_id)
                if stored is not None:
                    claim = FrozenAliasClaim(value, request_id, actor_id, stored.gate_revision)
                    recovered = self._exact_receipt(stored, claim)
                elif gate is not None and gate.request_id == request_id:
                    claim = FrozenAliasClaim(value, request_id, actor_id, gate.revision)
                    self._exact_gate(gate, claim, frozen=False)
                elif gate is not None and gate.state == "frozen":
                    raise AliasRecoveryError("rag_alias_claim_conflict")
                return AliasRecoveryReadback(
                    value,
                    row.state,
                    row.result_code,
                    gate.state if gate else "admitted",
                    claim,
                    recovered,
                )
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def close(
        self, claim: FrozenAliasClaim, result: RecoveryResult, proof: TerminationProof | None
    ) -> AliasRecoveryReceipt:
        try:
            async with self.sessions.begin() as session:
                await self._owner(session, claim.actor_id)
                gate = await lock_cluster_gate(session, self.binding.cluster_uuid)
                row = await self._operation(session, claim.snapshot.operation_id, lock=True)
                if snapshot(row) != claim.snapshot:
                    raise AliasRecoveryError("rag_alias_snapshot_changed")
                stored = await self._receipt(session, claim.request_id)
                if stored is not None:
                    value = self._exact_receipt(stored, claim)
                    if value.result_code != result or value.proof != proof:
                        raise AliasRecoveryError("rag_alias_claim_conflict")
                    return value
                self._exact_gate(gate, claim)
                if row.state == "closed":
                    code = (
                        "rag_alias_already_confirmed"
                        if row.result_code == "confirmed"
                        else "rag_alias_operation_closed"
                    )
                    raise AliasRecoveryError(code)
                if result == "not_dispatched":
                    if row.phase != "reserved" or proof is not None:
                        raise AliasRecoveryError("rag_alias_proof_required")
                    facts: dict[str, object] = {}
                    kind = "reserved_cas"
                else:
                    if row.phase not in {"legacy_unknown", "dispatching"} or proof is None:
                        raise AliasRecoveryError("rag_alias_proof_required")
                    proof.validate(claim)
                    facts, kind = proof.facts(), proof.proof_kind
                now = datetime.now(UTC)
                record = AliasRecoveryReceiptRecord(
                    request_id=claim.request_id,
                    operation_id=row.id,
                    actor_id=claim.actor_id,
                    cluster_uuid=row.cluster_uuid,
                    snapshot_sha256=claim.snapshot.sha256,
                    gate_revision=claim.revision,
                    result_code=result,
                    proof_kind=kind,
                    schema_version=1,
                    proof=facts,
                    proof_sha256=digest(facts),
                    created_at=now,
                )
                session.add(record)
                row.state, row.result_code, row.closed_at = "closed", result, now
                await session.flush()
                return receipt(record)
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def release(self, claim: FrozenAliasClaim) -> None:
        try:
            async with self.sessions.begin() as session:
                await self._owner(session, claim.actor_id)
                gate = await lock_cluster_gate(session, self.binding.cluster_uuid)
                self._exact_gate(gate, claim, frozen=False)
                row = await self._operation(session, claim.snapshot.operation_id, lock=True)
                if snapshot(row) != claim.snapshot:
                    raise AliasRecoveryError("rag_alias_snapshot_changed")
                if row.state != "closed":
                    raise AliasRecoveryError("rag_alias_operation_open")
                if row.result_code != "confirmed":
                    stored = await self._receipt(session, claim.request_id)
                    if stored is None:
                        raise AliasRecoveryError("rag_alias_claim_conflict")
                    self._exact_receipt(stored, claim)
                gate.state = "admitted"
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None
