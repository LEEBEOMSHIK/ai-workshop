"""One exact execution; uncertain actions are observed, never reissued."""

from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from ai_workshop.labs.rag.indexing.access_epoch_repository import (
    AccessEpochReadback,
    SqlAlchemyAccessEpochRepository,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    AccessEpochFloor,
    ControlExpectedIdentity,
    ControlSettlement,
    CutoverActionKind,
    LocalAccessEpochTerminationProof,
    OriginalDeploymentIdentity,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    VerifiedAccessEpoch,
    decode_termination_proof,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import (
    AliasOperationSnapshot,
    AliasRecoveryError,
    FrozenAliasClaim,
)

# Fresh applications start only after anchor + verified DB floor, as a separate
# registered launch. Starting them in an unverified cutover phase would be unsafe.
CUTOVER_ORDER = tuple(k for k in CutoverActionKind if k != CutoverActionKind.START_REGISTERED_APPS)


@dataclass(frozen=True, slots=True)
class ControlOwnership:
    execution_id: UUID
    executor_generation: str
    control_port_id: UUID


class CutoverControlPort(Protocol):
    @property
    def control_port_id(self) -> UUID: ...

    async def acquire(self, execution_id: UUID, executor_generation: str) -> ControlOwnership: ...
    async def assert_owned(self, ownership: ControlOwnership) -> None: ...
    async def expected(
        self,
        epoch: PreparedAccessEpoch,
        kind: CutoverActionKind,
        sequence: int,
        ownership: ControlOwnership,
    ) -> ControlExpectedIdentity: ...
    async def execute(
        self, action: ReservedCutoverAction, ownership: ControlOwnership
    ) -> ControlSettlement: ...
    async def reconcile(
        self, action: ReservedCutoverAction, ownership: ControlOwnership
    ) -> ControlSettlement | None: ...


class OriginalAccessEpochBackend(Protocol):
    async def preflight(self, snapshot: AliasOperationSnapshot) -> OriginalDeploymentIdentity: ...
    async def observe_secured(self, epoch: PreparedAccessEpoch) -> VerifiedAccessEpoch: ...
    async def commit_anchor(self, evidence: VerifiedAccessEpoch) -> AccessEpochFloor: ...
    async def revalidate(self, claim: FrozenAliasClaim, evidence: VerifiedAccessEpoch) -> None: ...


class LocalAccessEpochController:
    def __init__(
        self,
        repository: SqlAlchemyAccessEpochRepository,
        backend: OriginalAccessEpochBackend,
        control: CutoverControlPort,
    ) -> None:
        self.repository, self.backend, self.control = repository, backend, control
        try:
            self._control_port_id = control.control_port_id
            if type(self._control_port_id) is not UUID:
                raise ValueError
        except Exception:
            raise AliasRecoveryError("rag_alias_proof_invalid") from None

    @staticmethod
    def _validate_state(
        epoch: PreparedAccessEpoch, state: AccessEpochReadback, ownership: ControlOwnership
    ) -> None:
        if state.prepared != epoch or state.executor_generation != ownership.executor_generation:
            raise AliasRecoveryError("rag_alias_proof_invalid")
        for item in state.actions:
            LocalAccessEpochController._validate_action(item.action, ownership)

    @staticmethod
    def _validate_action(action: ReservedCutoverAction, ownership: ControlOwnership) -> None:
        if (
            action.execution_id != ownership.execution_id
            or action.executor_generation != ownership.executor_generation
        ):
            raise AliasRecoveryError("rag_alias_proof_invalid")

    def _validate_ownership(self, epoch: PreparedAccessEpoch, ownership: ControlOwnership) -> None:
        try:
            if (
                type(ownership) is not ControlOwnership
                or type(ownership.execution_id) is not UUID
                or ownership.execution_id != UUID(epoch.binding.execution_id)
                or type(ownership.executor_generation) is not str
                or str(UUID(ownership.executor_generation)) != ownership.executor_generation
                or type(ownership.control_port_id) is not UUID
                or ownership.control_port_id != self._control_port_id
                or self.control.control_port_id != self._control_port_id
            ):
                raise ValueError
        except Exception:
            raise AliasRecoveryError("rag_alias_proof_invalid") from None

    async def _assert_owned(self, epoch: PreparedAccessEpoch, ownership: ControlOwnership) -> None:
        # This check is not a native mutex. The port must also keep submission
        # atomic with its ownership check and prove previous controls settled.
        self._validate_ownership(epoch, ownership)
        try:
            if await cast(Awaitable[object], self.control.assert_owned(ownership)) is not None:
                raise ValueError
        except Exception:
            raise AliasRecoveryError("rag_alias_proof_invalid") from None
        self._validate_ownership(epoch, ownership)

    async def _owned_readback(
        self, epoch: PreparedAccessEpoch, ownership: ControlOwnership
    ) -> AccessEpochReadback:
        state = await self.repository.readback(epoch.binding.claim)
        self._validate_state(epoch, state, ownership)
        await self._assert_owned(epoch, ownership)
        return state

    async def advance(self, claim: FrozenAliasClaim) -> AccessEpochReadback:
        state = await self.repository.readback(claim)
        epoch = state.prepared
        if epoch is None:
            original = await self.backend.preflight(claim.snapshot)
            epoch = await self.repository.acquire(claim, original)
            state = await self.repository.readback(claim)
        if state.phase in {"verified", "receipted"}:
            return state
        generation = state.executor_generation
        if type(generation) is not str:
            raise AliasRecoveryError("rag_alias_proof_invalid")
        try:
            if str(UUID(generation)) != generation:
                raise ValueError
            ownership = await self.control.acquire(UUID(epoch.binding.execution_id), generation)
        except Exception:
            raise AliasRecoveryError("rag_alias_proof_invalid") from None
        self._validate_ownership(epoch, ownership)
        self._validate_state(epoch, state, ownership)
        await self._assert_owned(epoch, ownership)
        state = await self._owned_readback(epoch, ownership)
        if state.phase in {"verified", "receipted"}:
            return state
        for position, kind in enumerate(CUTOVER_ORDER):
            await self._assert_owned(epoch, ownership)
            if position < len(state.actions):
                last = state.actions[position]
                if last.action.kind != kind:
                    raise AliasRecoveryError("rag_alias_proof_invalid")
                if last.outcome != "settled":
                    resolved = await self.control.reconcile(last.action, ownership)
                    await self._assert_owned(epoch, ownership)
                    if resolved is None:
                        return state
                    await self.repository.settle_action(last.action, resolved)
                    state = await self._owned_readback(epoch, ownership)
                    if state.phase in {"verified", "receipted"}:
                        return state
                    if resolved.outcome != "settled":
                        return state
                continue
            sequence = state.actions[-1].event_sequence if state.actions else 0
            expected = await self.control.expected(epoch, kind, sequence, ownership)
            await self._assert_owned(epoch, ownership)
            action = await self.repository.reserve_action(epoch, kind, expected)
            self._validate_action(action, ownership)
            await self._assert_owned(epoch, ownership)
            result = await self.control.execute(action, ownership)
            await self._assert_owned(epoch, ownership)
            await self.repository.settle_action(action, result)
            state = await self._owned_readback(epoch, ownership)
            if state.phase in {"verified", "receipted"}:
                return state
            if result.outcome != "settled":
                return state
        await self._assert_owned(epoch, ownership)
        evidence = await self.backend.observe_secured(epoch)
        await self._assert_owned(epoch, ownership)
        anchor = await self.backend.commit_anchor(evidence)
        await self._assert_owned(epoch, ownership)
        await self.repository.mark_verified(epoch, evidence, anchor=anchor)
        await self._assert_owned(epoch, ownership)
        return await self._owned_readback(epoch, ownership)


class LocalAccessEpochCollector:
    def __init__(self, controller: LocalAccessEpochController) -> None:
        self.controller = controller
        self._issued: dict[UUID, str] = {}

    async def collect_verified_end(
        self, claim: FrozenAliasClaim
    ) -> LocalAccessEpochTerminationProof:
        import json

        state = await self.controller.advance(claim)
        if state.phase not in {"verified", "receipted"}:
            raise AliasRecoveryError("rag_alias_proof_required")
        evidence = await self.controller.repository.verified(claim)
        proof = decode_termination_proof(json.loads(evidence.proof_facts_json))
        if type(proof) is not LocalAccessEpochTerminationProof:
            raise AliasRecoveryError("rag_alias_proof_invalid")
        proof.validate(claim, evidence, now=datetime.now(UTC))
        await self.controller.backend.revalidate(claim, evidence)
        self._issued[claim.request_id] = proof.sha256
        return proof

    async def revalidate(
        self, claim: FrozenAliasClaim, proof: LocalAccessEpochTerminationProof
    ) -> None:
        if (
            type(proof) is not LocalAccessEpochTerminationProof
            or self._issued.get(claim.request_id) != proof.sha256
        ):
            raise AliasRecoveryError("rag_alias_proof_invalid")
        evidence = await self.controller.repository.verified(claim)
        proof.validate(claim, evidence, now=datetime.now(UTC))
        await self.controller.backend.revalidate(claim, evidence)
