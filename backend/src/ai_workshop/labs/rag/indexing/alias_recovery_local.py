"""Ordered local drain; typed facts are constructed only by this live workflow.

The native backend is a trusted operator boundary, not hostile-client isolation.
No task/alias observation or externally supplied evidence can replace a restart.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ai_workshop.labs.rag.indexing.alias_recovery_types import (
    AliasOperationSnapshot,
    AliasRecoveryError,
    AliasRecoveryReadback,
    FrozenAliasClaim,
    TerminationProof,
)


class LocalRecoveryRefusal(AliasRecoveryError):
    def __init__(self, diagnostic: str = "local_boundary_unsupported") -> None:
        self.diagnostic = diagnostic
        super().__init__("rag_alias_proof_invalid")


@dataclass(frozen=True, slots=True)
class ServerIdentity:
    context: str
    daemon_id: str
    container_id: str
    mount_sha256: str
    config_sha256: str
    cluster_uuid: str
    stable_node_id: str
    ephemeral_id: str
    jvm_start_at: datetime
    created_at: datetime
    started_at: datetime
    finished_at: datetime | None
    running: bool

    @property
    def persistent(self) -> tuple[object, ...]:
        return (
            self.context,
            self.daemon_id,
            self.container_id,
            self.mount_sha256,
            self.config_sha256,
            self.cluster_uuid,
            self.stable_node_id,
            self.created_at,
        )


class LocalRecoveryBackend(Protocol):
    async def identity(self) -> ServerIdentity: ...
    async def history(
        self,
        snapshot: AliasOperationSnapshot,
        identity: ServerIdentity,
    ) -> str: ...
    async def clients_absent(self) -> tuple[str, datetime]: ...
    async def stop(self, identity: ServerIdentity) -> ServerIdentity: ...
    async def start(self, identity: ServerIdentity) -> ServerIdentity: ...


Authority = Callable[[FrozenAliasClaim], Awaitable[AliasRecoveryReadback]]


class LocalTerminationCollector:
    def __init__(self, backend: LocalRecoveryBackend, authority: Authority) -> None:
        self.backend, self.authority = backend, authority
        self._issued: dict[str, tuple[FrozenAliasClaim, ServerIdentity]] = {}

    async def _gate(self, claim: FrozenAliasClaim) -> None:
        status = await self.authority(claim)
        if (
            status.claim != claim
            or status.snapshot != claim.snapshot
            or status.gate_state != "frozen"
            or status.state != "open"
            or status.receipt is not None
            or status.result_code is not None
            or status.snapshot.phase not in {"legacy_unknown", "dispatching"}
        ):
            raise AliasRecoveryError("rag_alias_claim_conflict")

    async def collect_verified_end(self, claim: FrozenAliasClaim) -> TerminationProof:
        try:
            await self._gate(claim)
            old = await self.backend.identity()
            if not old.running or old.cluster_uuid != claim.snapshot.cluster_uuid:
                raise LocalRecoveryRefusal("server_identity_changed")
            history = await self.backend.history(claim.snapshot, old)
            inventory, clients_end = await self.backend.clients_absent()
            await self._gate(claim)
            before_stop = await self.backend.identity()
            if before_stop != old:
                raise LocalRecoveryRefusal("server_identity_changed")
            stopped = await self.backend.stop(old)
            if (
                stopped.running
                or stopped.persistent != old.persistent
                or stopped.finished_at is None
                or stopped.finished_at <= clients_end
            ):
                raise LocalRecoveryRefusal("server_stop_unverified")
            # An authority/readback failure here deliberately leaves the server stopped:
            # never issue a fresh mutation to resolve an unknown database commit.
            await self._gate(claim)
            new = await self.backend.start(stopped)
            if (
                not new.running
                or new.persistent != old.persistent
                or new.ephemeral_id == old.ephemeral_id
                or new.jvm_start_at <= old.jvm_start_at
                or new.started_at <= stopped.finished_at
                or new.jvm_start_at < new.started_at
            ):
                raise LocalRecoveryRefusal("server_incarnation_unverified")
            if await self.backend.history(claim.snapshot, new) != history:
                raise LocalRecoveryRefusal("original_history_changed")
            await self.backend.clients_absent()
            await self._gate(claim)
            proof = TerminationProof(
                request_id=claim.request_id,
                operation_id=claim.snapshot.operation_id,
                snapshot_sha256=claim.snapshot.sha256,
                cluster_uuid=new.cluster_uuid,
                container_id=new.container_id,
                protected_mount_sha256=new.mount_sha256,
                config_sha256=new.config_sha256,
                client_inventory_sha256=inventory,
                deployment_history_sha256=history,
                stable_node_id=new.stable_node_id,
                old_ephemeral_id=old.ephemeral_id,
                new_ephemeral_id=new.ephemeral_id,
                old_jvm_start_at=old.jvm_start_at,
                clients_terminated_at=clients_end,
                server_stopped_at=stopped.finished_at,
                server_started_at=new.started_at,
                new_jvm_start_at=new.jvm_start_at,
                verified_at=datetime.now(UTC),
                schema_version=1,
            )
            proof.validate(claim)
            self._issued[proof.sha256] = (claim, new)
            return proof
        except AliasRecoveryError:
            raise
        except Exception:
            raise LocalRecoveryRefusal("local_observation_failed") from None

    async def revalidate(self, claim: FrozenAliasClaim, proof: TerminationProof) -> None:
        issued = self._issued.get(proof.sha256)
        if issued is None or issued[0] != claim:
            raise LocalRecoveryRefusal("proof_not_collected_here")
        try:
            proof.validate(claim)
            await self._gate(claim)
            current = await self.backend.identity()
            if current != issued[1]:
                raise LocalRecoveryRefusal("server_identity_changed")
            if (
                await self.backend.history(claim.snapshot, current)
                != proof.deployment_history_sha256
            ):
                raise LocalRecoveryRefusal("original_history_changed")
            await self.backend.clients_absent()
        except AliasRecoveryError:
            raise
        except Exception:
            raise LocalRecoveryRefusal("local_observation_failed") from None
