"""Real recovery facade/repository, with only the collector I/O boundary faked."""

from dataclasses import replace

import pytest

from ai_workshop.config import Settings
from ai_workshop.labs.rag.indexing.alias_recovery import AliasRecoveryService
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError
from tests.unit.labs.rag.indexing.test_access_epoch_repository import closure_case


class Collector:
    def __init__(self, proof):
        self.proof, self.calls = proof, []

    async def collect_verified_end(self, claim):
        self.calls.append("collect")
        return self.proof

    async def revalidate(self, claim, proof):
        self.calls.append("revalidate")


async def prepared_service():
    db, repo, claim, epoch, verified, proof = await closure_case()
    await repo.mark_verified(epoch, verified, anchor=repo.floor_from_verified(verified))
    port = Collector(proof)
    service = AliasRecoveryService(
        db,
        Settings(
            _env_file=None,
            secret_key="synthetic-test-secret-value-00000000",
            rag_index_store_id="rag",
            rag_index_cluster_uuid="cluster",
        ),
        access_epoch_repository=repo,
        access_epoch_port=port,
    )
    return db, service, claim, proof, port


async def test_exact_receipt_replay_does_not_collect_release_or_run_parity():
    db, service, claim, proof, port = await prepared_service()
    first = await service.recover_access_epoch(claim)
    assert first.proof == proof and port.calls == ["collect", "revalidate"]
    assert await service.recover_access_epoch(claim) == first
    assert port.calls == ["collect", "revalidate"]
    status = await service.readback(claim.snapshot.operation_id, claim.actor_id, claim.request_id)
    assert status.gate_state == "frozen" and status.state == "closed"


async def test_forged_collector_result_does_not_close_operation():
    db, service, claim, proof, port = await prepared_service()
    port.proof = replace(proof, auth_policy_sha256="9" * 64)
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await service.recover_access_epoch(claim)
    assert db.operation.state == "open"
