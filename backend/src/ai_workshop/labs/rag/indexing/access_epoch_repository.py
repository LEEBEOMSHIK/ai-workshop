"""Short exact-owner transactions; all OS, secret and ES I/O is elsewhere."""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.indexing.access_epoch_models import (
    AccessEpochEventRecord,
    AccessEpochExecutionRecord,
    AccessEpochFloorRecord,
    AccessEpochRecord,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    AccessEpochBinding,
    AccessEpochFloor,
    ActionOutcome,
    ControlExpectedIdentity,
    ControlSettlement,
    CutoverActionKind,
    LocalAccessEpochTerminationProof,
    OriginalDeploymentIdentity,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    VerifiedAccessEpoch,
    canonical_json,
    decode_termination_proof,
    strict_utc,
)
from ai_workshop.labs.rag.indexing.alias_journal import lock_cluster_gate
from ai_workshop.labs.rag.indexing.alias_models import AliasRecoveryReceiptRecord
from ai_workshop.labs.rag.indexing.alias_recovery_repository import (
    SqlAlchemyAliasRecoveryRepository,
    receipt,
    snapshot,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import (
    AliasRecoveryError,
    AliasRecoveryReceipt,
    FrozenAliasClaim,
    digest,
    utc_text,
)
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding


@dataclass(frozen=True, slots=True)
class ActionReadback:
    action: ReservedCutoverAction
    outcome: ActionOutcome
    manifest_json: str | None
    observed_at: datetime
    event_sequence: int


@dataclass(frozen=True, slots=True)
class AccessEpochReadback:
    prepared: PreparedAccessEpoch | None
    phase: str | None
    actions: tuple[ActionReadback, ...]
    operation_state: str
    gate_state: str
    receipt: AliasRecoveryReceipt | None
    old_server_stopped_at: datetime | None
    executor_generation: str | None


def _conflict() -> AliasRecoveryError:
    return AliasRecoveryError("rag_alias_claim_conflict")


def original_facts(original: OriginalDeploymentIdentity) -> dict[str, object]:
    return {k: utc_text(v) if isinstance(v, datetime) else v for k, v in asdict(original).items()}


def _prepared(
    row: AccessEpochRecord, execution: AccessEpochExecutionRecord, claim: FrozenAliasClaim
) -> PreparedAccessEpoch:
    values = row.original
    original = OriginalDeploymentIdentity(
        daemon_sha256=cast(str, values["daemon_sha256"]),
        container_id=cast(str, values["container_id"]),
        cluster_uuid=cast(str, values["cluster_uuid"]),
        stable_node_id=cast(str, values["stable_node_id"]),
        ephemeral_id=cast(str, values["ephemeral_id"]),
        volume_sha256=cast(str, values["volume_sha256"]),
        mount_sha256=cast(str, values["mount_sha256"]),
        image_sha256=cast(str, values["image_sha256"]),
        config_sha256=cast(str, values["config_sha256"]),
        deployment_sha256=cast(str, values["deployment_sha256"]),
        jvm_start_at=strict_utc(values["jvm_start_at"]),
    )
    return PreparedAccessEpoch(
        AccessEpochBinding(claim, str(row.id), str(execution.id), row.ordinal), original
    )


def _action(row: AccessEpochEventRecord) -> ReservedCutoverAction:
    return ReservedCutoverAction(
        row.action_id,
        row.execution_id,
        row.action_sequence,
        CutoverActionKind(row.kind),
        ControlExpectedIdentity(row.expected_json, row.action_sequence - 1),
        row.executor_generation,
    )


class SqlAlchemyAccessEpochRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        binding: IndexBinding,
        prefix: str,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sessions, self.binding = sessions, binding
        self.clock = clock
        self.recovery = SqlAlchemyAliasRecoveryRepository(sessions, binding, prefix)

    async def _locked(
        self, session: AsyncSession, claim: FrozenAliasClaim
    ) -> AccessEpochRecord | None:
        await self.recovery._owner(session, claim.actor_id)
        gate = await lock_cluster_gate(session, self.binding.cluster_uuid)
        operation = await self.recovery._operation(session, claim.snapshot.operation_id, lock=True)
        if snapshot(operation) != claim.snapshot:
            raise AliasRecoveryError("rag_alias_snapshot_changed")
        self.recovery._exact_gate(gate, claim, frozen=operation.state != "closed")
        row = await session.scalar(
            select(AccessEpochRecord).where(AccessEpochRecord.request_id == claim.request_id)
        )
        if row is not None and (
            row.actor_id != claim.actor_id
            or row.operation_id != claim.snapshot.operation_id
            or row.store_id != self.binding.store_id
            or row.cluster_uuid != self.binding.cluster_uuid
            or row.snapshot_sha256 != claim.snapshot.sha256
            or row.gate_revision != claim.revision
        ):
            raise _conflict()
        if row is not None:
            # The cluster gate serializes acquisition; existing records lock in
            # owner -> gate -> operation -> execution -> epoch order.
            await self._execution(session, row)
            row = await session.scalar(
                select(AccessEpochRecord).where(AccessEpochRecord.id == row.id).with_for_update()
            )
        return row

    async def _execution(
        self, session: AsyncSession, row: AccessEpochRecord
    ) -> AccessEpochExecutionRecord:
        execution = await session.scalar(
            select(AccessEpochExecutionRecord)
            .where(AccessEpochExecutionRecord.epoch_id == row.id)
            .with_for_update()
        )
        if execution is None:
            raise _conflict()
        return execution

    async def _events(
        self, session: AsyncSession, execution_id: UUID
    ) -> list[AccessEpochEventRecord]:
        rows = await session.scalars(
            select(AccessEpochEventRecord)
            .where(AccessEpochEventRecord.execution_id == execution_id)
            .order_by(AccessEpochEventRecord.sequence)
        )
        return sorted(rows.all(), key=lambda r: r.sequence)

    async def acquire(
        self, claim: FrozenAliasClaim, original: OriginalDeploymentIdentity
    ) -> PreparedAccessEpoch:
        try:
            async with self.sessions.begin() as session:
                row = await self._locked(session, claim)
                if row is not None:
                    prepared = _prepared(row, await self._execution(session, row), claim)
                    if prepared.original != original:
                        raise _conflict()
                    return prepared
                operation = await self.recovery._operation(session, claim.snapshot.operation_id)
                if operation.state != "open" or operation.phase not in {
                    "legacy_unknown",
                    "dispatching",
                }:
                    raise AliasRecoveryError("rag_alias_operation_closed")
                floor = await session.scalar(
                    select(AccessEpochFloorRecord)
                    .where(AccessEpochFloorRecord.cluster_uuid == self.binding.cluster_uuid)
                    .with_for_update()
                )
                rows = await session.scalars(
                    select(AccessEpochRecord).where(
                        AccessEpochRecord.cluster_uuid == self.binding.cluster_uuid
                    )
                )
                previous = rows.all()
                if (
                    any(r.phase != "receipted" for r in previous)
                    or original.cluster_uuid != self.binding.cluster_uuid
                ):
                    raise _conflict()
                epoch_id, execution_id = uuid4(), uuid4()
                previous_floor = floor.ordinal if floor else 0
                ordinal = max([previous_floor, *[r.ordinal for r in previous]]) + 1
                now = self.clock()
                row = AccessEpochRecord(
                    id=epoch_id,
                    request_id=claim.request_id,
                    operation_id=claim.snapshot.operation_id,
                    actor_id=claim.actor_id,
                    store_id=self.binding.store_id,
                    cluster_uuid=self.binding.cluster_uuid,
                    snapshot_sha256=claim.snapshot.sha256,
                    gate_revision=claim.revision,
                    ordinal=ordinal,
                    previous_floor=previous_floor,
                    phase="prepared",
                    original=original_facts(original),
                    created_at=now,
                )
                execution = AccessEpochExecutionRecord(
                    id=execution_id,
                    epoch_id=epoch_id,
                    executor_generation=str(uuid4()),
                    created_at=now,
                )
                session.add(row)
                await session.flush()
                session.add(execution)
                await session.flush()
                return _prepared(row, execution, claim)
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def reserve_action(
        self, epoch: PreparedAccessEpoch, kind: CutoverActionKind, expected: ControlExpectedIdentity
    ) -> ReservedCutoverAction:
        try:
            async with self.sessions.begin() as session:
                row = await self._locked(session, epoch.binding.claim)
                if row is None or row.phase in {"verified", "receipted"}:
                    raise _conflict()
                execution = await self._execution(session, row)
                if _prepared(row, execution, epoch.binding.claim) != epoch:
                    raise _conflict()
                events = await self._events(session, execution.id)
                latest = {event.action_id: event for event in events}
                if any(event.outcome != "settled" for event in latest.values()):
                    raise _conflict()
                sequence = max([0, *[event.sequence for event in events]]) + 1
                if expected.preceding_sequence != sequence - 1:
                    raise _conflict()
                completed = tuple(CutoverActionKind(event.kind) for event in latest.values())
                order = tuple(
                    k for k in CutoverActionKind if k != CutoverActionKind.START_REGISTERED_APPS
                )
                if len(completed) >= len(order) or kind != order[len(completed)]:
                    raise _conflict()
                event = AccessEpochEventRecord(
                    id=uuid4(),
                    execution_id=execution.id,
                    action_id=uuid4(),
                    sequence=sequence,
                    action_sequence=sequence,
                    kind=kind.value,
                    outcome="pending",
                    expected_json=expected.identity_json,
                    executor_generation=execution.executor_generation,
                    observed_at=self.clock(),
                )
                session.add(event)
                await session.flush()
                return ReservedCutoverAction(
                    event.action_id,
                    execution.id,
                    sequence,
                    kind,
                    expected,
                    execution.executor_generation,
                )
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def settle_action(self, action: ReservedCutoverAction, result: ControlSettlement) -> None:
        try:
            async with self.sessions.begin() as session:
                execution = await session.scalar(
                    select(AccessEpochExecutionRecord).where(
                        AccessEpochExecutionRecord.id == action.execution_id
                    )
                )
                if execution is None:
                    raise _conflict()
                row = await session.scalar(
                    select(AccessEpochRecord).where(AccessEpochRecord.id == execution.epoch_id)
                )
                if row is None:
                    raise _conflict()
                snap = snapshot(await self.recovery._operation(session, row.operation_id))
                claim = FrozenAliasClaim(snap, row.request_id, row.actor_id, row.gate_revision)
                await self._locked(session, claim)
                execution = await self._execution(session, row)
                events = await self._events(session, execution.id)
                matches = [event for event in events if event.action_id == action.action_id]
                if (
                    not matches
                    or _action(matches[0]) != action
                    or (
                        result.action_id != action.action_id
                        or result.execution_id != execution.id
                        or result.executor_generation != execution.executor_generation
                        or result.outcome not in {"settled", "unknown"}
                        or result.observed_at.utcoffset() != UTC.utcoffset(None)
                    )
                ):
                    raise _conflict()
                latest = matches[-1]
                if latest.outcome == result.outcome:
                    if (
                        latest.manifest_json != result.manifest_json
                        or latest.observed_at != result.observed_at
                    ):
                        raise _conflict()
                    return
                if latest.outcome == "settled" or result.observed_at < latest.observed_at:
                    raise _conflict()
                if action.kind == CutoverActionKind.ISSUE_ROLE_KEY and result.outcome == "settled":
                    from ai_workshop.labs.rag.indexing.access_epoch_keys import key_group_manifest
                    from ai_workshop.labs.rag.indexing.access_epoch_models import (
                        AccessEpochKeyEventRecord,
                    )

                    child_events = list(
                        (
                            await session.scalars(
                                select(AccessEpochKeyEventRecord)
                                .where(
                                    AccessEpochKeyEventRecord.execution_id == execution.id,
                                    AccessEpochKeyEventRecord.parent_action_id == action.action_id,
                                )
                                .order_by(AccessEpochKeyEventRecord.sequence)
                            )
                        ).all()
                    )
                    expected_manifest = key_group_manifest(action, child_events)
                    if expected_manifest is None or result.manifest_json != canonical_json(
                        expected_manifest
                    ):
                        raise _conflict()
                event = AccessEpochEventRecord(
                    id=uuid4(),
                    execution_id=execution.id,
                    action_id=action.action_id,
                    sequence=events[-1].sequence + 1,
                    action_sequence=action.sequence,
                    kind=action.kind.value,
                    outcome=result.outcome,
                    expected_json=action.expected.identity_json,
                    executor_generation=execution.executor_generation,
                    manifest_json=result.manifest_json,
                    observed_at=result.observed_at,
                )
                session.add(event)
                await session.flush()
                if result.outcome == "settled":
                    phase = {
                        CutoverActionKind.STOP_OLD: "old_stopped",
                        CutoverActionKind.RETIRE_OLD: "old_retired",
                        CutoverActionKind.START_SECURED: "secured_started",
                    }.get(action.kind)
                    if phase:
                        row.phase = phase
                    if action.kind == CutoverActionKind.STOP_OLD:
                        row.stopped_sequence = event.sequence
                    elif action.kind == CutoverActionKind.RETIRE_OLD:
                        row.retired_sequence = event.sequence
                await session.flush()
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def readback(self, claim: FrozenAliasClaim) -> AccessEpochReadback:
        status = await self.recovery.readback(
            claim.snapshot.operation_id, claim.actor_id, claim.request_id
        )
        if status.claim != claim:
            raise _conflict()
        try:
            async with self.sessions.begin() as session:
                row = await self._locked(session, claim)
                if row is None:
                    return AccessEpochReadback(
                        None, None, (), status.state, status.gate_state, status.receipt, None, None
                    )
                execution = await self._execution(session, row)
                events = await self._events(session, execution.id)
                latest = {event.action_id: event for event in events}
                actions = tuple(
                    ActionReadback(
                        _action(event),
                        cast(ActionOutcome, event.outcome),
                        event.manifest_json,
                        event.observed_at,
                        event.sequence,
                    )
                    for event in latest.values()
                )
                stopped_manifest = next(
                    (
                        event.manifest_json
                        for event in events
                        if event.kind == CutoverActionKind.STOP_OLD and event.outcome == "settled"
                    ),
                    None,
                )
                stopped = None
                if stopped_manifest is not None:
                    try:
                        stopped = strict_utc(json.loads(stopped_manifest)["finished_at"])
                    except (KeyError, TypeError, ValueError):
                        raise AliasRecoveryError("rag_alias_proof_invalid") from None
                return AccessEpochReadback(
                    _prepared(row, execution, claim),
                    row.phase,
                    actions,
                    status.state,
                    status.gate_state,
                    status.receipt,
                    stopped,
                    execution.executor_generation,
                )
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    @staticmethod
    def floor_from_verified(verified: VerifiedAccessEpoch) -> AccessEpochFloor:
        import json

        proof = decode_termination_proof(json.loads(verified.proof_facts_json))
        if type(proof) is not LocalAccessEpochTerminationProof:
            raise AliasRecoveryError("rag_alias_proof_invalid")
        return AccessEpochFloor(
            proof.store_id,
            proof.cluster_uuid,
            proof.minimum_access_epoch,
            str(proof.access_epoch_id),
            proof.new_container_id,
            proof.stable_node_id,
            proof.route_policy_sha256,
            proof.auth_policy_sha256,
            proof.new_config_sha256,
            proof.tls_public_ca_sha256,
        )

    async def mark_verified(
        self,
        epoch: PreparedAccessEpoch,
        evidence: VerifiedAccessEpoch,
        *,
        anchor: AccessEpochFloor | None,
    ) -> AccessEpochFloor:
        import json

        proof = decode_termination_proof(json.loads(evidence.proof_facts_json))
        if type(proof) is not LocalAccessEpochTerminationProof:
            raise AliasRecoveryError("rag_alias_proof_invalid")
        proof.validate(epoch.binding.claim, evidence, now=datetime.now(UTC))
        floor = self.floor_from_verified(evidence)
        original = epoch.original
        if (
            anchor != floor
            or evidence.binding != epoch.binding
            or (
                proof.old_container_id != original.container_id
                or proof.cluster_uuid != original.cluster_uuid
                or proof.stable_node_id != original.stable_node_id
                or proof.old_ephemeral_id != original.ephemeral_id
                or proof.old_jvm_start_at != original.jvm_start_at
                or proof.daemon_identity_sha256 != original.daemon_sha256
                or proof.original_volume_identity_sha256 != original.volume_sha256
                or proof.protected_mount_sha256 != original.mount_sha256
                or proof.protected_image_sha256 != original.image_sha256
                or proof.old_config_sha256 != original.config_sha256
                or proof.old_deployment_sha256 != original.deployment_sha256
            )
        ):
            raise AliasRecoveryError("rag_alias_proof_invalid")
        try:
            async with self.sessions.begin() as session:
                row = await self._locked(session, epoch.binding.claim)
                if row is None:
                    raise _conflict()
                execution = await self._execution(session, row)
                if (
                    _prepared(row, execution, epoch.binding.claim) != epoch
                    or row.previous_floor != evidence.previous_floor
                ):
                    raise _conflict()
                if row.phase in {"verified", "receipted"}:
                    if row.verified != proof.facts() or row.manifests != dict(evidence.manifests):
                        raise _conflict()
                    return floor
                if row.phase != "secured_started" or (
                    row.stopped_sequence,
                    row.retired_sequence,
                ) != (evidence.stopped_action_sequence, evidence.retired_action_sequence):
                    raise AliasRecoveryError("rag_alias_proof_invalid")
                events = await self._events(session, execution.id)
                actions = list({event.action_id: event for event in events}.values())
                order = tuple(
                    k for k in CutoverActionKind if k != CutoverActionKind.START_REGISTERED_APPS
                )
                if tuple(event.kind for event in actions) != order or any(
                    event.outcome != "settled"
                    or event.manifest_json is None
                    or event.executor_generation != execution.executor_generation
                    for event in actions
                ):
                    raise AliasRecoveryError("rag_alias_proof_invalid")
                stopped, retired = actions[1], actions[2]
                try:
                    stop_manifest = json.loads(stopped.manifest_json or "null")
                    retire_manifest = json.loads(retired.manifest_json or "null")
                    if (
                        stopped.sequence != evidence.stopped_action_sequence
                        or retired.sequence != evidence.retired_action_sequence
                        or stop_manifest["container_id"] != original.container_id
                        or strict_utc(stop_manifest["finished_at"]) != proof.old_server_stopped_at
                        or retire_manifest["container_id"] != original.container_id
                        or strict_utc(retire_manifest["retired_at"])
                        != proof.old_container_retired_at
                    ):
                        raise AliasRecoveryError("rag_alias_proof_invalid")
                except (KeyError, TypeError, ValueError):
                    raise AliasRecoveryError("rag_alias_proof_invalid") from None
                existing = await session.scalar(
                    select(AccessEpochFloorRecord)
                    .where(AccessEpochFloorRecord.cluster_uuid == self.binding.cluster_uuid)
                    .with_for_update()
                )
                if existing is not None and existing.ordinal != evidence.previous_floor:
                    raise _conflict()
                if existing is None:
                    session.add(
                        AccessEpochFloorRecord(
                            cluster_uuid=floor.cluster_uuid,
                            store_id=floor.store_id,
                            ordinal=floor.ordinal,
                            epoch_id=UUID(floor.access_epoch_id),
                            identity=asdict(floor),
                        )
                    )
                else:
                    existing.ordinal, existing.epoch_id, existing.identity = (
                        floor.ordinal,
                        UUID(floor.access_epoch_id),
                        asdict(floor),
                    )
                await session.flush()
                row.verified, row.manifests = proof.facts(), dict(evidence.manifests)
                row.phase, row.verified_at = "verified", proof.verified_at
                await session.flush()
                return floor
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def floor(self, binding: IndexBinding) -> AccessEpochFloor | None:
        if binding != self.binding:
            raise _conflict()
        try:
            async with self.sessions.begin() as session:
                row = await session.scalar(
                    select(AccessEpochFloorRecord).where(
                        AccessEpochFloorRecord.cluster_uuid == binding.cluster_uuid
                    )
                )
                if row is None:
                    return None
                value = row.identity
                return AccessEpochFloor(
                    cast(str, value["store_id"]),
                    cast(str, value["cluster_uuid"]),
                    cast(int, value["ordinal"]),
                    cast(str, value["access_epoch_id"]),
                    cast(str, value["container_id"]),
                    cast(str, value["stable_node_id"]),
                    cast(str, value["route_sha256"]),
                    cast(str, value["auth_sha256"]),
                    cast(str, value["config_sha256"]),
                    cast(str, value["ca_sha256"]),
                )
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def close_access_epoch(
        self, claim: FrozenAliasClaim, proof: LocalAccessEpochTerminationProof
    ) -> AliasRecoveryReceipt:
        if type(proof) is not LocalAccessEpochTerminationProof:
            raise AliasRecoveryError("rag_alias_proof_invalid")
        try:
            async with self.sessions.begin() as session:
                row = await self._locked(session, claim)
                if row is None:
                    raise AliasRecoveryError("rag_alias_proof_required")
                execution = await self._execution(session, row)
                if row.verified is None or row.manifests is None:
                    raise AliasRecoveryError("rag_alias_proof_required")
                evidence = VerifiedAccessEpoch(
                    _prepared(row, execution, claim).binding,
                    row.previous_floor,
                    canonical_json(row.verified),
                    tuple(row.manifests.items()),
                    row.stopped_sequence or 0,
                    row.retired_sequence or 0,
                )
                proof.validate(claim, evidence, now=datetime.now(UTC))
                stored = await self.recovery._receipt(session, claim.request_id)
                if stored is not None:
                    value = self.recovery._exact_receipt(stored, claim)
                    if value.proof != proof or row.phase != "receipted":
                        raise _conflict()
                    return value
                operation = await self.recovery._operation(
                    session, claim.snapshot.operation_id, lock=True
                )
                if operation.state != "open" or row.phase != "verified":
                    raise AliasRecoveryError("rag_alias_operation_closed")
                now = datetime.now(UTC)
                record = AliasRecoveryReceiptRecord(
                    request_id=claim.request_id,
                    operation_id=claim.snapshot.operation_id,
                    actor_id=claim.actor_id,
                    cluster_uuid=claim.snapshot.cluster_uuid,
                    snapshot_sha256=claim.snapshot.sha256,
                    gate_revision=claim.revision,
                    result_code="recovered_terminated",
                    proof_kind=proof.proof_kind,
                    schema_version=2,
                    proof=proof.facts(),
                    proof_sha256=digest(proof.facts()),
                    created_at=now,
                )
                session.add(record)
                operation.state, operation.result_code, operation.closed_at = (
                    "closed",
                    "recovered_terminated",
                    now,
                )
                row.phase, row.receipted_at = "receipted", now
                await session.flush()
                return receipt(record)
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None

    async def verified(self, claim: FrozenAliasClaim) -> VerifiedAccessEpoch:
        try:
            async with self.sessions.begin() as session:
                row = await self._locked(session, claim)
                if (
                    row is None
                    or row.phase not in {"verified", "receipted"}
                    or row.verified is None
                    or row.manifests is None
                ):
                    raise AliasRecoveryError("rag_alias_proof_required")
                execution = await self._execution(session, row)
                value = VerifiedAccessEpoch(
                    _prepared(row, execution, claim).binding,
                    row.previous_floor,
                    canonical_json(row.verified),
                    tuple(row.manifests.items()),
                    row.stopped_sequence or 0,
                    row.retired_sequence or 0,
                )
                proof = decode_termination_proof(row.verified)
                if type(proof) is not LocalAccessEpochTerminationProof:
                    raise AliasRecoveryError("rag_alias_proof_invalid")
                proof.validate(claim, value, now=datetime.now(UTC))
                return value
        except SQLAlchemyError:
            raise AliasRecoveryError("rag_alias_commit_unknown") from None
