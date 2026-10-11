"""One SELECT-only committed sample; ordinary data, never source authority.

The caller's concrete repositories do not attest their engine/DSN or original
deployment. Source-owned assembly and fresh filesystem/server guards are separate.
"""

from __future__ import annotations

import json
import re
from asyncio import CancelledError, create_task, shield
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypeVar, cast
from uuid import UUID

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, raiseload, undefer

from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord
from ai_workshop.labs.rag.indexing.access_epoch_evidence_packets import _stored_control_manifest
from ai_workshop.labs.rag.indexing.access_epoch_keys import (
    KeyActionReadback,
    SqlAlchemyEpochKeyRepository,
    key_group_manifest,
)
from ai_workshop.labs.rag.indexing.access_epoch_keys import (
    _action as key_action,
)
from ai_workshop.labs.rag.indexing.access_epoch_keys import (
    _readback as key_readback,
)
from ai_workshop.labs.rag.indexing.access_epoch_models import (
    AccessEpochEventRecord,
    AccessEpochExecutionRecord,
    AccessEpochFloorRecord,
    AccessEpochKeyEventRecord,
    AccessEpochRecord,
)
from ai_workshop.labs.rag.indexing.access_epoch_repository import (
    AccessEpochReadback,
    ActionReadback,
    SqlAlchemyAccessEpochRepository,
    _action,
    _prepared,
)
from ai_workshop.labs.rag.indexing.access_epoch_secured_read import _freeze
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    AccessEpochFloor,
    ActionOutcome,
    CutoverActionKind,
    LocalAccessEpochTerminationProof,
    VerifiedAccessEpoch,
    canonical_json,
    decode_termination_proof,
    strict_utc,
)
from ai_workshop.labs.rag.indexing.alias_models import (
    AliasClusterGateRecord,
    AliasOperationRecord,
    AliasRecoveryReceiptRecord,
)
from ai_workshop.labs.rag.indexing.alias_recovery_repository import (
    SqlAlchemyAliasRecoveryRepository,
    snapshot,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import FrozenAliasClaim, digest
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, canonical_recovery_targets
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding
from ai_workshop.labs.rag.models.document_processing import (
    index_namespace_document_processing_profile_id,
)
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord

if TYPE_CHECKING:
    from ai_workshop.labs.rag.indexing.access_epoch_secured_read import (
        NativeSecuredReadSource,
        SecuredReadBinding,
    )
    from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
        NativeReadDependencies,
        NativeSecuredReadAssembly,
    )

T = TypeVar("T")


def _denied() -> ValueError:
    return ValueError("committed_snapshot_denied")


def _uuid(value: object) -> None:
    if type(value) is not UUID or type(value.int) is not int or not 0 < value.int < 2**128:
        raise _denied()


def _integer(value: object, minimum: int = 1) -> None:
    if type(value) is not int or value < minimum:
        raise _denied()


def _string(value: object) -> None:
    if type(value) is not str or not value:
        raise _denied()


def _time(value: object) -> None:
    if (
        type(value) is not datetime
        or value.utcoffset() != UTC.utcoffset(None)
        or value > datetime.now(UTC)
    ):
        raise _denied()


def _data(value: object) -> None:
    if type(value) is dict:
        for key, item in value.items():
            _string(key)
            _data(item)
    elif type(value) is list:
        for item in value:
            _data(item)
    elif type(value) not in {str, int, bool, type(None)}:
        raise _denied()


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _denied()
        result[key] = value
    return result


def _packet(value: object) -> dict[str, object]:
    _string(value)
    parsed: object = json.loads(cast(str, value), object_pairs_hook=_pairs)
    _data(parsed)
    if type(parsed) is not dict or canonical_json(parsed) != value:
        raise _denied()
    return cast(dict[str, object], parsed)


@dataclass(frozen=True, slots=True)
class CommittedEpochSnapshot:
    evidence: VerifiedAccessEpoch = field(repr=False)
    state: AccessEpochReadback = field(repr=False)
    floor: AccessEpochFloor = field(repr=False)
    completed_keys: tuple[KeyActionReadback, ...] = field(repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class _Dependencies:
    assembly: NativeSecuredReadAssembly
    cap: NativeReadDependencies
    repository: SqlAlchemyAccessEpochRepository
    keys: SqlAlchemyEpochKeyRepository
    maker: async_sessionmaker[AsyncSession]
    seal: tuple[object, ...]

    def signature(self) -> tuple[object, ...]:
        return (
            id(self.assembly),
            id(self.cap),
            id(self.repository),
            id(self.keys),
            id(self.maker),
            id(self.cap.repository),
            id(self.cap.keys),
            id(self.repository.sessions),
            _freeze(self.cap.phase),
        )

    def guard(self) -> None:
        from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
            NativeReadDependencies,
            NativeSecuredReadAssembly,
        )

        if (
            type(self.assembly) is not NativeSecuredReadAssembly
            or type(self.cap) is not NativeReadDependencies
            or type(self.cap.phase) is not str
            or self.cap.phase != "committed"
            or self.cap.repository is not self.repository
            or self.cap.keys is not self.keys
            or type(self.maker) is not async_sessionmaker
            or self.maker.class_ is not AsyncSession
            or self.repository.sessions is not self.maker
            or self.signature() != self.seal
        ):
            raise _denied()
        # Invoke the concrete source-owned class method, never a caller protocol
        # or replaceable instance callback. Its retained graph seals are fresh.
        NativeSecuredReadAssembly.assert_issued(self.assembly, self.cap)


class _Read:
    def __init__(
        self,
        repository: SqlAlchemyAccessEpochRepository,
        keys: SqlAlchemyEpochKeyRepository,
        claim: FrozenAliasClaim,
    ) -> None:
        if (
            type(repository) is not SqlAlchemyAccessEpochRepository
            or type(keys) is not SqlAlchemyEpochKeyRepository
            or type(repository.recovery) is not SqlAlchemyAliasRecoveryRepository
            or type(repository.binding) is not IndexBinding
            or type(claim) is not FrozenAliasClaim
            or keys.parent is not repository
            or repository.recovery.sessions is not repository.sessions
            or repository.recovery.binding != repository.binding
        ):
            raise _denied()
        self.repository, self.keys, self.claim = repository, keys, claim
        self._dependencies: _Dependencies | None = None
        self._retained_dependencies: _Dependencies | None = None
        self._bound: tuple[NativeSecuredReadSource, SecuredReadBinding] | None = None
        self.inputs = self.signature()
        self.guard()

    @classmethod
    def from_dependencies(
        cls,
        assembly: NativeSecuredReadAssembly,
        cap: NativeReadDependencies,
        claim: FrozenAliasClaim,
    ) -> _Read:
        from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
            NativeReadDependencies,
            NativeSecuredReadAssembly,
        )

        if (
            type(assembly) is not NativeSecuredReadAssembly
            or type(cap) is not NativeReadDependencies
        ):
            raise _denied()
        NativeSecuredReadAssembly.assert_issued(assembly, cap)
        if type(cap.phase) is not str or cap.phase != "committed":
            raise _denied()
        reader = cls(cap.repository, cap.keys, claim)
        dependency = _Dependencies(
            assembly, cap, cap.repository, cap.keys, cap.repository.sessions, ()
        )
        dependency = _Dependencies(
            assembly, cap, cap.repository, cap.keys, cap.repository.sessions, dependency.signature()
        )
        reader._dependencies = reader._retained_dependencies = dependency
        reader.inputs = reader.signature()
        reader.guard()
        return reader

    @classmethod
    def from_bound_source(cls, source: NativeSecuredReadSource, cap: SecuredReadBinding) -> _Read:
        from ai_workshop.labs.rag.indexing.access_epoch_secured_read import (
            _ASSOCIATIONS,
            NativeSecuredReadSource,
        )

        if type(source) is not NativeSecuredReadSource:
            raise _denied()
        NativeSecuredReadSource._assert_committed_dependencies(source)
        entry = NativeSecuredReadSource._entry(source, cap)
        association = _ASSOCIATIONS[source]
        reader = cls.from_dependencies(association.assembly, association.dependencies, entry.claim)
        reader._bound = (source, cap)
        reader.inputs = reader.signature()
        reader.guard()
        return reader

    def check_session(self, session: AsyncSession) -> None:
        self.guard()
        dependency = self._dependencies
        if dependency is not None:
            engine = dependency.maker.kw.get("bind")
            if (
                type(session) is not AsyncSession
                or type(engine) is not AsyncEngine
                or session.bind is not engine
                or type(session.sync_session) is not Session
                or session.sync_session.bind is not engine.sync_engine
            ):
                raise _denied()

    def signature(self) -> object:
        r = self.repository
        return (
            id(r.sessions),
            id(r.binding),
            id(r.recovery),
            id(r.recovery.sessions),
            id(r.recovery.binding),
            id(r.clock),
            id(self.keys.parent),
            id(self.keys.clock),
            _freeze(r.binding),
            _freeze(r.recovery.binding),
            _freeze(r.recovery.index_prefix),
            _freeze(self.claim),
            id(self._dependencies),
            None if self._dependencies is None else self._dependencies.seal,
            None
            if self._bound is None
            else (id(self._bound[0]), id(self._bound[1]), _freeze(self._bound[1])),
        )

    def guard(self) -> None:
        if self._bound is not None:
            from ai_workshop.labs.rag.indexing.access_epoch_secured_read import (
                NativeSecuredReadSource,
            )

            source, cap = self._bound
            NativeSecuredReadSource._assert_committed_dependencies(source)
            entry = NativeSecuredReadSource._entry(source, cap)
            if entry.claim is not self.claim or source._repository is not self.repository:
                raise _denied()
        if self._dependencies is not self._retained_dependencies:
            raise _denied()
        if self._dependencies is not None:
            if type(self._dependencies) is not _Dependencies:
                raise _denied()
            self._dependencies.guard()
        c, r = self.claim, self.repository
        _integer(c.revision)
        for value in (
            c.request_id,
            c.actor_id,
            c.snapshot.operation_id,
            c.snapshot.indexing_profile_id,
            c.snapshot.document_processing_profile_id,
        ):
            _uuid(value)
        _time(c.snapshot.created_at)
        for text_value in (r.binding.store_id, r.binding.cluster_uuid, r.recovery.index_prefix):
            _string(text_value)
        if (
            self.signature() != self.inputs
            or r.recovery.sessions is not r.sessions
            or self.keys.parent is not r
            or r.recovery.binding != r.binding
            or (c.snapshot.store_id, c.snapshot.cluster_uuid)
            != (r.binding.store_id, r.binding.cluster_uuid)
        ):
            raise _denied()

    async def all(self, session: AsyncSession, statement: Select[tuple[T]]) -> list[T]:
        self.check_session(session)
        result = await session.scalars(
            statement.options(raiseload("*")).execution_options(populate_existing=True)
        )
        self.check_session(session)
        return list(result.all())

    async def one(self, session: AsyncSession, statement: Select[tuple[T]]) -> T:
        rows = await self.all(session, statement)
        if len(rows) != 1:
            raise _denied()
        return rows[0]

    async def canonical(self, session: AsyncSession, operation: AliasOperationRecord) -> None:
        alias = IndexDescriptor(1, "cosine").active_alias(
            self.repository.recovery.index_prefix,
            operation.indexing_profile_id,
            document_processing_profile_id=index_namespace_document_processing_profile_id(
                operation.document_processing_profile_id
            ),
        )
        if alias != operation.alias or canonical_recovery_targets(
            alias, operation.targets
        ) != tuple(operation.targets):
            raise _denied()
        if operation.state == "closed":
            return
        for profile_id, kind in (
            (operation.indexing_profile_id, "indexing"),
            (operation.document_processing_profile_id, "document_processing"),
        ):
            profile = await self.one(
                session, select(ProfileRecord).where(ProfileRecord.id == profile_id)
            )
            if type(profile.kind) is not str or profile.kind != kind:
                raise _denied()
        for name in operation.targets:
            await self.one(
                session,
                select(RagIndexBuildRecord).where(
                    RagIndexBuildRecord.id == UUID(name[-36:]),
                    RagIndexBuildRecord.indexing_profile_id == operation.indexing_profile_id,
                    RagIndexBuildRecord.document_processing_profile_id
                    == operation.document_processing_profile_id,
                    RagIndexBuildRecord.index_name == name,
                ),
            )

    async def sample(self, session: AsyncSession) -> CommittedEpochSnapshot:
        c = self.claim
        actor = await self.one(session, select(UserRecord).where(UserRecord.id == c.actor_id))
        _uuid(actor.id)
        if (
            actor.is_active is not True
            or type(actor.role) not in {str, UserRole}
            or actor.role != UserRole.OWNER
        ):
            raise _denied()
        op = await self.one(
            session,
            select(AliasOperationRecord).where(AliasOperationRecord.id == c.snapshot.operation_id),
        )
        if snapshot(op) != c.snapshot or _freeze(snapshot(op)) != _freeze(c.snapshot):
            raise _denied()
        await self.canonical(session, op)
        gate = await self.one(
            session,
            select(AliasClusterGateRecord).where(
                AliasClusterGateRecord.cluster_uuid == c.snapshot.cluster_uuid
            ),
        )
        _integer(gate.revision)
        for value in (gate.request_id, gate.actor_id, gate.operation_id):
            _uuid(value)
        for string_value in (gate.state, gate.cluster_uuid, gate.snapshot_sha256, op.state):
            _string(string_value)
        self.repository.recovery._exact_gate(gate, c)
        receipts = await self.all(
            session,
            select(AliasRecoveryReceiptRecord)
            .options(
                undefer(AliasRecoveryReceiptRecord.access_epoch_id),
                undefer(AliasRecoveryReceiptRecord.execution_id),
            )
            .where(AliasRecoveryReceiptRecord.request_id == c.request_id),
        )
        if len(receipts) > 1:
            raise _denied()
        row = await self.one(
            session, select(AccessEpochRecord).where(AccessEpochRecord.request_id == c.request_id)
        )
        for value in (row.id, row.actor_id, row.operation_id, row.request_id):
            _uuid(value)
        for counter in (row.gate_revision, row.ordinal, row.stopped_sequence, row.retired_sequence):
            _integer(counter)
        _integer(row.previous_floor, 0)
        for string_value in (row.store_id, row.cluster_uuid, row.snapshot_sha256):
            _string(string_value)
        if (
            (
                row.actor_id,
                row.operation_id,
                row.store_id,
                row.cluster_uuid,
                row.snapshot_sha256,
                row.gate_revision,
            )
            != (
                c.actor_id,
                c.snapshot.operation_id,
                c.snapshot.store_id,
                c.snapshot.cluster_uuid,
                c.snapshot.sha256,
                c.revision,
            )
            or row.verified is None
            or row.manifests is None
            or type(row.phase) is not str
            or row.phase not in {"verified", "receipted"}
            or (row.phase == "verified" and (op.state != "open" or receipts))
            or (row.phase == "receipted" and (op.state != "closed" or len(receipts) != 1))
        ):
            raise _denied()
        stored_receipt = None
        if receipts:
            r = receipts[0]
            _integer(r.gate_revision)
            _integer(r.schema_version)
            for identifier in (r.request_id, r.operation_id, r.actor_id):
                _uuid(identifier)
            for string_value in (
                r.result_code,
                r.proof_kind,
                r.proof_sha256,
                r.snapshot_sha256,
                r.cluster_uuid,
            ):
                _string(string_value)
            _time(r.created_at)
            if r.schema_version != 2 or r.proof_sha256 != digest(r.proof):
                raise _denied()
            stored_receipt = self.repository.recovery._exact_receipt(r, c)
        execution = await self.one(
            session,
            select(AccessEpochExecutionRecord).where(AccessEpochExecutionRecord.epoch_id == row.id),
        )
        _uuid(execution.id)
        _uuid(execution.epoch_id)
        _string(execution.executor_generation)
        if str(UUID(execution.executor_generation)) != execution.executor_generation:
            raise _denied()
        _data(row.original)
        _data(row.verified)
        _data(row.manifests)
        prepared = _prepared(row, execution, c)
        evidence = VerifiedAccessEpoch(
            prepared.binding,
            row.previous_floor,
            canonical_json(row.verified),
            tuple(row.manifests.items()),
            cast(int, row.stopped_sequence),
            cast(int, row.retired_sequence),
        )
        proof = decode_termination_proof(row.verified)
        if type(proof) is not LocalAccessEpochTerminationProof:
            raise _denied()
        proof.validate(c, evidence, now=datetime.now(UTC))
        original = prepared.original
        if (
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
            or (
                receipts
                and (
                    receipts[0].access_epoch_id != row.id
                    or receipts[0].execution_id != execution.id
                )
            )
        ):
            raise _denied()
        if stored_receipt is not None and stored_receipt.proof != proof:
            raise _denied()
        events = await self.all(
            session,
            select(AccessEpochEventRecord)
            .where(AccessEpochEventRecord.execution_id == execution.id)
            .order_by(AccessEpochEventRecord.sequence),
        )
        actions = _actions(events, execution)
        stopped = next(x for x in actions if x.action.kind == CutoverActionKind.STOP_OLD)
        retired = next(x for x in actions if x.action.kind == CutoverActionKind.RETIRE_OLD)
        if (
            stopped.event_sequence != row.stopped_sequence
            or retired.event_sequence != row.retired_sequence
            or _packet(stopped.manifest_json).get("container_id") != original.container_id
            or strict_utc(_packet(stopped.manifest_json)["finished_at"])
            != proof.old_server_stopped_at
            or _packet(retired.manifest_json).get("container_id") != original.container_id
            or strict_utc(_packet(retired.manifest_json)["retired_at"])
            != proof.old_container_retired_at
        ):
            raise _denied()
        state = AccessEpochReadback(
            prepared,
            row.phase,
            actions,
            op.state,
            gate.state,
            stored_receipt,
            strict_utc(_packet(stopped.manifest_json)["finished_at"]),
            execution.executor_generation,
        )
        if _stored_control_manifest(prepared, state) != row.manifests.get("control_settlement"):
            raise _denied()
        floor_row = await self.one(
            session,
            select(AccessEpochFloorRecord).where(
                AccessEpochFloorRecord.cluster_uuid == c.snapshot.cluster_uuid
            ),
        )
        _integer(floor_row.ordinal)
        _uuid(floor_row.epoch_id)
        floor = self.repository.floor_from_verified(evidence)
        if _freeze(floor_row.identity) != _freeze(asdict(floor)) or (
            floor_row.store_id,
            floor_row.cluster_uuid,
            floor_row.ordinal,
            str(floor_row.epoch_id),
        ) != (floor.store_id, floor.cluster_uuid, floor.ordinal, floor.access_epoch_id):
            raise _denied()
        parent = next(x for x in actions if x.action.kind == CutoverActionKind.ISSUE_ROLE_KEY)
        key_events = await self.all(
            session,
            select(AccessEpochKeyEventRecord)
            .where(
                AccessEpochKeyEventRecord.execution_id == execution.id,
                AccessEpochKeyEventRecord.parent_action_id == parent.action.action_id,
            )
            .order_by(AccessEpochKeyEventRecord.sequence),
        )
        ledger = _keys(key_events, parent)
        group = key_group_manifest(parent.action, key_events)
        if (
            group is None
            or canonical_json(group) != parent.manifest_json
            or canonical_json(
                group
                | {
                    "epoch_id": prepared.binding.access_epoch_id,
                    "ordinal": prepared.binding.ordinal,
                }
            )
            != row.manifests.get("credential_deployment")
        ):
            raise _denied()
        self.guard()
        return CommittedEpochSnapshot(evidence, state, floor, ledger)


def _actions(
    events: list[AccessEpochEventRecord], execution: AccessEpochExecutionRecord
) -> tuple[ActionReadback, ...]:
    previous: AccessEpochEventRecord | None = None
    first: dict[UUID, AccessEpochEventRecord] = {}
    latest: dict[UUID, AccessEpochEventRecord] = {}
    ids: set[UUID] = set()
    outcomes: set[tuple[UUID, str]] = set()
    for sequence, event in enumerate(events, 1):
        for value in (event.id, event.action_id, event.execution_id):
            _uuid(value)
        _integer(event.sequence)
        _integer(event.action_sequence)
        _time(event.observed_at)
        _packet(event.expected_json)
        for string_value in (event.kind, event.outcome, event.executor_generation):
            _string(string_value)
        if (
            event.sequence != sequence
            or event.execution_id != execution.id
            or event.executor_generation != execution.executor_generation
            or event.id in ids
            or (event.action_id, event.outcome) in outcomes
            or (previous is not None and event.observed_at < previous.observed_at)
        ):
            raise _denied()
        if event.action_id not in first:
            if (
                event.outcome != "pending"
                or event.action_sequence != sequence
                or event.manifest_json is not None
                or (previous is not None and previous.outcome != "settled")
            ):
                raise _denied()
            first[event.action_id] = event
        else:
            initial = first[event.action_id]
            if (
                _freeze(_action(initial)) != _freeze(_action(event))
                or event.outcome not in {"unknown", "settled"}
                or previous is None
                or previous.action_id != event.action_id
                or previous.outcome == "settled"
            ):
                raise _denied()
            _packet(event.manifest_json)
        ids.add(event.id)
        outcomes.add((event.action_id, event.outcome))
        latest[event.action_id] = event
        previous = event
    return tuple(
        ActionReadback(
            _action(e), cast(ActionOutcome, e.outcome), e.manifest_json, e.observed_at, e.sequence
        )
        for e in latest.values()
    )


def _keys(
    events: list[AccessEpochKeyEventRecord], parent: ActionReadback
) -> tuple[KeyActionReadback, ...]:
    first: dict[UUID, AccessEpochKeyEventRecord] = {}
    outcomes: set[tuple[UUID, str]] = set()
    previous: AccessEpochKeyEventRecord | None = None
    ids: set[UUID] = set()
    for sequence, event in enumerate(events, 1):
        for value in (
            event.id,
            event.action_id,
            event.execution_id,
            event.parent_action_id,
            event.issuance_id,
        ):
            _uuid(value)
        _integer(event.sequence)
        _integer(event.action_sequence)
        _time(event.observed_at)
        for string_value in (event.outcome, event.executor_generation):
            _string(string_value)
        if (
            event.sequence != sequence
            or event.execution_id != parent.action.execution_id
            or event.parent_action_id != parent.action.action_id
            or event.executor_generation != parent.action.executor_generation
            or type(event.role) is not str
            or event.role not in {"reader", "writer", "collector"}
            or type(event.kind) is not str
            or event.kind not in {"issue", "invalidate"}
            or type(event.permissions_sha256) is not str
            or re.fullmatch("[a-f0-9]{64}", event.permissions_sha256) is None
            or event.id in ids
            or (event.action_id, event.outcome) in outcomes
            or (previous is not None and event.observed_at < previous.observed_at)
        ):
            raise _denied()
        if event.action_id not in first:
            if (
                event.outcome != "pending"
                or event.action_sequence != sequence
                or event.manifest_json is not None
                or (previous is not None and previous.outcome != "settled")
            ):
                raise _denied()
            first[event.action_id] = event
        else:
            if (
                _freeze(key_action(first[event.action_id])) != _freeze(key_action(event))
                or event.outcome not in {"unknown", "settled"}
                or previous is None
                or previous.action_id != event.action_id
                or previous.outcome == "settled"
            ):
                raise _denied()
            wire = _packet(event.manifest_json)
            if event.outcome == "settled" and (
                set(wire)
                != {
                    "schema_version",
                    "result",
                    "key_id",
                    "role",
                    "issuance_id",
                    "permissions_sha256",
                }
                or type(wire["schema_version"]) is not int
                or wire["schema_version"] != 1
                or wire["role"] != event.role
                or wire["issuance_id"] != str(event.issuance_id)
                or wire["permissions_sha256"] != event.permissions_sha256
                or wire["result"]
                not in (
                    {"issued", "issued_inaccessible"} if event.kind == "issue" else {"invalidated"}
                )
                or type(wire["key_id"]) is not str
                or not wire["key_id"]
                or (event.kind == "invalidate" and wire["key_id"] != event.key_id)
            ):
                raise _denied()
        ids.add(event.id)
        outcomes.add((event.action_id, event.outcome))
        previous = event
    return key_readback(events)


async def read_committed_snapshot(
    repository: SqlAlchemyAccessEpochRepository,
    keys: SqlAlchemyEpochKeyRepository,
    claim: FrozenAliasClaim,
) -> CommittedEpochSnapshot:
    """Rollback-only coherent persisted data; no read/source capability is minted."""
    try:
        reader = _Read(repository, keys, claim)
        return await _read(reader)
    except Exception:
        raise _denied() from None


async def _read_committed_from_dependencies(
    assembly: NativeSecuredReadAssembly,
    cap: NativeReadDependencies,
    claim: FrozenAliasClaim,
) -> CommittedEpochSnapshot:
    """Only the exact source-owned committed graph may use this private path."""
    try:
        return await _read(_Read.from_dependencies(assembly, cap, claim))
    except Exception:
        raise _denied() from None


async def _read_committed_from_bound_source(
    source: NativeSecuredReadSource, cap: SecuredReadBinding
) -> CommittedEpochSnapshot:
    """Fresh per-await checks of an actual issuer's retained read binding."""
    try:
        return await _read(_Read.from_bound_source(source, cap))
    except Exception:
        raise _denied() from None


async def _read(reader: _Read) -> CommittedEpochSnapshot:
    try:
        session = reader.repository.sessions()
        primary: BaseException | None = None
        sample: CommittedEpochSnapshot | None = None
        try:
            reader.check_session(session)
            await session.begin()
            reader.check_session(session)
            with session.no_autoflush:
                await session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )
                reader.check_session(session)
                sample = await reader.sample(session)
        except BaseException as error:
            primary = error
        # AsyncSession.__aexit__ can itself mask the primary. Own both teardown
        # operations and wait until they finish even after repeated cancellation.
        cleanup = create_task(_cleanup(session))
        while not cleanup.done():
            try:
                await shield(cleanup)
            except CancelledError as error:
                if primary is None:
                    primary = error
            except BaseException:
                break  # Retrieve the exact task failure below.
        try:
            cleanup.result()
        except BaseException as error:
            if primary is None:
                primary = error
        if primary is not None:
            raise primary
        reader.guard()
        if sample is None:
            raise _denied()
        return sample
    except Exception:
        raise _denied() from None


async def _cleanup(session: AsyncSession) -> None:
    primary: BaseException | None = None
    try:
        await session.rollback()
    except BaseException as error:
        primary = error
    try:
        await session.close()
    except BaseException as error:
        if primary is None:
            primary = error
    if primary is not None:
        raise primary
