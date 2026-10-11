"""Internal local-owner recovery facade; never submits an alias mutation."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.config import Settings
from ai_workshop.labs.rag.indexing.access_epoch_repository import SqlAlchemyAccessEpochRepository
from ai_workshop.labs.rag.indexing.access_epoch_types import LocalAccessEpochTerminationProof
from ai_workshop.labs.rag.indexing.alias_recovery_repository import (
    AliasRecoveryRepositoryPort,
    SqlAlchemyAliasRecoveryRepository,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import (
    AliasOperationSnapshot,
    AliasRecoveryError,
    AliasRecoveryReadback,
    AliasRecoveryReceipt,
    FrozenAliasClaim,
    TerminationProof,
    TerminationProofPort,
)
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding


class AccessEpochProofPort(Protocol):
    async def collect_verified_end(
        self, claim: FrozenAliasClaim
    ) -> LocalAccessEpochTerminationProof: ...
    async def revalidate(
        self, claim: FrozenAliasClaim, proof: LocalAccessEpochTerminationProof
    ) -> None: ...


class AliasRecoveryService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: Settings,
        proof_port: TerminationProofPort | None = None,
        *,
        repository: AliasRecoveryRepositoryPort | None = None,
        access_epoch_repository: SqlAlchemyAccessEpochRepository | None = None,
        access_epoch_port: AccessEpochProofPort | None = None,
    ) -> None:
        self.settings, self.proof_port = settings, proof_port
        if settings.rag_index_store_id is None or settings.rag_index_cluster_uuid is None:
            raise AliasRecoveryError("rag_alias_binding_mismatch")
        self.binding = IndexBinding(settings.rag_index_store_id, settings.rag_index_cluster_uuid)
        self.index_prefix = settings.elasticsearch_index_prefix
        self.repository = repository or SqlAlchemyAliasRecoveryRepository(
            sessions, self.binding, self.index_prefix
        )
        self.access_epoch_repository = access_epoch_repository or SqlAlchemyAccessEpochRepository(
            sessions, self.binding, self.index_prefix
        )
        self.access_epoch_port = access_epoch_port

    def _local(self) -> None:
        if self.settings.environment != "local":
            raise AliasRecoveryError("rag_alias_local_required")
        if (self.settings.rag_index_store_id, self.settings.rag_index_cluster_uuid) != (
            self.binding.store_id,
            self.binding.cluster_uuid,
        ):
            raise AliasRecoveryError("rag_alias_binding_mismatch")
        if self.settings.elasticsearch_index_prefix != self.index_prefix:
            raise AliasRecoveryError("rag_alias_binding_mismatch")

    async def preview(self, operation_id: UUID, actor_id: UUID) -> AliasOperationSnapshot:
        self._local()
        return await self.repository.preview(operation_id, actor_id)

    async def freeze(
        self, operation_id: UUID, actor_id: UUID, request_id: UUID, snapshot_sha256: str
    ) -> FrozenAliasClaim:
        self._local()
        return await self.repository.freeze(operation_id, actor_id, request_id, snapshot_sha256)

    async def readback(
        self, operation_id: UUID, actor_id: UUID, request_id: UUID
    ) -> AliasRecoveryReadback:
        self._local()
        return await self.repository.readback(operation_id, actor_id, request_id)

    async def recover_not_dispatched(self, claim: FrozenAliasClaim) -> AliasRecoveryReceipt:
        self._local()
        return await self.repository.close(claim, "not_dispatched", None)

    async def recover_terminated(self, claim: FrozenAliasClaim) -> AliasRecoveryReceipt:
        self._local()
        status = await self.repository.readback(
            claim.snapshot.operation_id, claim.actor_id, claim.request_id
        )
        if status.claim != claim:
            raise AliasRecoveryError("rag_alias_claim_conflict")
        if status.receipt is not None:
            if status.receipt.result_code != "recovered_terminated":
                raise AliasRecoveryError("rag_alias_claim_conflict")
            return status.receipt
        if status.result_code == "confirmed":
            raise AliasRecoveryError("rag_alias_already_confirmed")
        if status.gate_state != "frozen":
            raise AliasRecoveryError("rag_alias_claim_conflict")
        if status.snapshot.phase not in {"legacy_unknown", "dispatching"}:
            raise AliasRecoveryError("rag_alias_proof_required")
        if self.proof_port is None:
            raise AliasRecoveryError("rag_alias_proof_required")
        # All collector I/O precedes the final atomic transaction and its locks.
        try:
            proof = await self.proof_port.collect_verified_end(claim)
            if type(proof) is not TerminationProof:
                raise AliasRecoveryError("rag_alias_proof_invalid")
            proof.validate(claim)
            await self.proof_port.revalidate(claim, proof)
        except AliasRecoveryError:
            raise
        except Exception:
            raise AliasRecoveryError("rag_alias_proof_invalid") from None
        self._local()
        return await self.repository.close(claim, "recovered_terminated", proof)

    async def release(self, claim: FrozenAliasClaim) -> None:
        self._local()
        await self.repository.release(claim)

    async def recover_access_epoch(self, claim: FrozenAliasClaim) -> AliasRecoveryReceipt:
        self._local()
        status = await self.repository.readback(
            claim.snapshot.operation_id, claim.actor_id, claim.request_id
        )
        if status.claim != claim:
            raise AliasRecoveryError("rag_alias_claim_conflict")
        if status.receipt is not None:
            if type(status.receipt.proof) is not LocalAccessEpochTerminationProof:
                raise AliasRecoveryError("rag_alias_claim_conflict")
            return status.receipt
        if status.result_code == "confirmed":
            raise AliasRecoveryError("rag_alias_already_confirmed")
        if status.gate_state != "frozen" or status.state != "open":
            raise AliasRecoveryError("rag_alias_claim_conflict")
        if self.access_epoch_port is None or status.snapshot.phase not in {
            "legacy_unknown",
            "dispatching",
        }:
            raise AliasRecoveryError("rag_alias_proof_required")
        try:
            proof = await self.access_epoch_port.collect_verified_end(claim)
            if type(proof) is not LocalAccessEpochTerminationProof:
                raise AliasRecoveryError("rag_alias_proof_invalid")
            evidence = await self.access_epoch_repository.verified(claim)
            proof.validate(claim, evidence, now=datetime.now(UTC))
            await self.access_epoch_port.revalidate(claim, proof)
        except AliasRecoveryError:
            raise
        except Exception:
            raise AliasRecoveryError("rag_alias_proof_invalid") from None
        self._local()
        return await self.access_epoch_repository.close_access_epoch(claim, proof)
