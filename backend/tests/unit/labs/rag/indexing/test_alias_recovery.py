"""Offline recovery decisions; SQL transport doubles never replace policy."""

from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from ai_workshop.config import Settings
from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord
from ai_workshop.labs.rag.indexing.alias_journal import AliasJournal
from ai_workshop.labs.rag.indexing.alias_models import AliasOperationRecord
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding, IndexTrackingError
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.identity.models import UserRecord


class Database:
    """Only the SQL transport/transaction is synthetic; service/repository are real."""

    def __init__(self, phase="reserved"):
        self.actor = uuid4()
        operation = AliasOperationRecord(
            id=uuid4(),
            store_id="rag",
            cluster_uuid="cluster",
            alias="test-active",
            indexing_profile_id=uuid4(),
            document_processing_profile_id=uuid4(),
            targets=["test-index"],
            state="open",
            phase=phase,
            created_at=datetime(2026, 9, 20, tzinfo=UTC),
        )
        self.operation_id = operation.id
        self.rows = {(AliasOperationRecord, operation.id): operation}
        base = (
            f"ai-workshop-rag-{operation.document_processing_profile_id}-"
            f"{operation.indexing_profile_id}"
        )
        build_id = uuid4()
        operation.alias, operation.targets = base + "-active", [f"{base}-{build_id}"]
        for profile_id, kind in [
            (operation.indexing_profile_id, "indexing"),
            (operation.document_processing_profile_id, "document_processing"),
        ]:
            self.rows[ProfileRecord, profile_id] = ProfileRecord(id=profile_id, kind=kind)
        self.rows[RagIndexBuildRecord, build_id] = RagIndexBuildRecord(
            id=build_id,
            indexing_profile_id=operation.indexing_profile_id,
            document_processing_profile_id=operation.document_processing_profile_id,
            index_name=operation.targets[0],
        )
        self.rows[UserRecord, self.actor] = UserRecord(
            id=self.actor,
            role="owner",
            is_active=True,
        )
        self.statements = []
        self.commit_fault = None

    @property
    def operation(self):
        return self.rows[AliasOperationRecord, self.operation_id]

    def __call__(self):
        return self.begin()

    @asynccontextmanager
    async def begin(self):
        before = deepcopy(self.rows)
        try:
            yield self
            if self.commit_fault == "rollback":
                raise OperationalError("synthetic", {}, Exception("private-secret"))
        except BaseException:
            self.rows = before
            raise
        if self.commit_fault == "lost_response":
            raise OperationalError("synthetic", {}, Exception("private-secret"))

    async def scalar(self, statement):
        self.statements.append(statement)
        params = statement.compile(dialect=postgresql.dialect()).params
        entity = statement.column_descriptions[0]["entity"]
        for (kind, _key), row in self.rows.items():
            if kind is not entity:
                continue
            if all(getattr(row, name.rsplit("_", 1)[0]) == value for name, value in params.items()):
                name = statement.column_descriptions[0]["name"]
                return getattr(row, name) if name in {"id", "kind"} else row
        return None

    async def execute(self, statement):
        self.statements.append(statement)
        table = statement.table
        params = statement.compile(dialect=postgresql.dialect()).params
        from ai_workshop.labs.rag.indexing.alias_models import AliasClusterGateRecord

        if table.name == "rag_alias_cluster_gates":
            key = AliasClusterGateRecord, params["cluster_uuid"]
            if key not in self.rows:
                self.rows[key] = AliasClusterGateRecord(
                    **{
                        **params,
                        "state": "admitted",
                        "revision": 0,
                    }
                )

    def add(self, row):
        self.rows[type(row), row.request_id] = row

    async def flush(self):
        pass


@pytest.fixture
def case():
    from ai_workshop.labs.rag.indexing.alias_recovery import AliasRecoveryService

    db = Database()
    settings = Settings(
        secret_key="synthetic-test-secret-value-00000000",
        environment="local",
        rag_index_store_id="rag",
        rag_index_cluster_uuid="cluster",
    )
    return SimpleNamespace(db=db, service=AliasRecoveryService(db, settings))


async def freeze(case):
    snapshot = await case.service.preview(case.db.operation.id, case.db.actor)
    return await case.service.freeze(snapshot.operation_id, case.db.actor, uuid4(), snapshot.sha256)


async def test_reserved_closure_is_exact_atomic_and_replayable(case):
    claim = await freeze(case)
    receipt = await case.service.recover_not_dispatched(claim)
    assert receipt.result_code == "not_dispatched"
    assert receipt.operation_id == case.db.operation.id
    assert case.db.operation.state == "closed"
    assert await case.service.recover_not_dispatched(claim) == receipt
    status = await case.service.readback(
        claim.snapshot.operation_id, claim.actor_id, claim.request_id
    )
    assert status.receipt == receipt
    await case.service.release(claim)
    # A new operation with identical alias and targets cannot be touched by replay.
    newer = deepcopy(case.db.operation)
    newer.id, newer.state, newer.result_code, newer.closed_at = uuid4(), "open", None, None
    case.db.rows[AliasOperationRecord, newer.id] = newer
    newer_snapshot = await case.service.preview(newer.id, case.db.actor)
    newer_claim = await case.service.freeze(newer.id, case.db.actor, uuid4(), newer_snapshot.sha256)
    assert await case.service.recover_not_dispatched(claim) == receipt
    assert newer.state == "open"
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    with pytest.raises(AliasRecoveryError, match="claim_conflict"):
        await case.service.release(claim)
    status = await case.service.readback(newer.id, case.db.actor, newer_claim.request_id)
    assert status.claim == newer_claim and status.gate_state == "frozen"


@pytest.mark.parametrize("phase", ["legacy_unknown", "dispatching"])
async def test_only_reserved_can_close_without_a_trusted_proof(case, phase):
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    case.db.operation.phase = phase
    claim = await freeze(case)
    with pytest.raises(AliasRecoveryError, match="proof_required"):
        await case.service.recover_not_dispatched(claim)
    assert case.db.operation.state == "open"


@pytest.mark.parametrize("role,active", [("member", True), ("owner", False)])
async def test_actor_cannot_preview_or_apply_after_revocation(case, role, active):
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    claim = await freeze(case)
    actor = case.db.rows[UserRecord, case.db.actor]
    actor.role, actor.is_active = role, active
    with pytest.raises(AliasRecoveryError, match="actor_denied"):
        await case.service.preview(case.db.operation.id, case.db.actor)
    with pytest.raises(AliasRecoveryError, match="actor_denied"):
        await case.service.recover_not_dispatched(claim)
    assert case.db.operation.state == "open"


@pytest.mark.parametrize("fault", ["rollback", "lost_response"])
async def test_commit_uncertainty_requires_same_request_readback(case, fault):
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    claim = await freeze(case)
    case.db.commit_fault = fault
    with pytest.raises(AliasRecoveryError, match="commit_unknown") as caught:
        await case.service.recover_not_dispatched(claim)
    assert "private-secret" not in str(caught.value)
    case.db.commit_fault = None
    status = await case.service.readback(
        claim.snapshot.operation_id, claim.actor_id, claim.request_id
    )
    assert (status.receipt is not None) == (fault == "lost_response")
    assert status.gate_state == "frozen"


async def test_normal_finish_winner_is_preserved_and_can_be_released(case):
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    await AliasJournal(case.db).dispatch(case.db.operation.id)
    claim = await freeze(case)
    await AliasJournal(case.db).finish(case.db.operation.id)
    with pytest.raises(AliasRecoveryError, match="already_confirmed"):
        await case.service.recover_not_dispatched(claim)
    status = await case.service.readback(
        claim.snapshot.operation_id, claim.actor_id, claim.request_id
    )
    assert status.result_code == "confirmed" and status.receipt is None
    await case.service.release(claim)


async def test_freeze_snapshot_and_claim_conflicts_do_not_change_gate(case):
    from dataclasses import replace

    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    claim = await freeze(case)
    for changed in [
        replace(claim, actor_id=uuid4()),
        replace(claim, revision=99),
        replace(claim, request_id=uuid4()),
    ]:
        with pytest.raises(AliasRecoveryError):
            await case.service.recover_not_dispatched(changed)
    with pytest.raises(AliasRecoveryError, match="conflict"):
        await case.service.freeze(
            case.db.operation.id, case.db.actor, uuid4(), claim.snapshot.sha256
        )
    case.db.operation.targets = ["changed-index"]
    with pytest.raises(AliasRecoveryError, match="snapshot_changed|binding_mismatch"):
        await case.service.recover_not_dispatched(claim)


async def test_sql_gate_admission_and_dispatch_cas_are_real_predicates(case):
    await freeze(case)
    journal = AliasJournal(case.db)
    with pytest.raises(IndexTrackingError):
        await journal.dispatch(case.db.operation.id)
    with pytest.raises(IndexTrackingError):
        await journal.reserve(IndexBinding("rag", "cluster"), "other-active", uuid4(), uuid4(), ())
    assert case.db.operation.phase == "reserved"
    compiled = [str(s.compile(dialect=postgresql.dialect())) for s in case.db.statements]
    assert any("ON CONFLICT (cluster_uuid) DO NOTHING" in s for s in compiled)
    assert any(
        "rag_alias_cluster_gates.cluster_uuid =" in s and "FOR UPDATE" in s for s in compiled
    )


async def test_closed_or_legacy_operations_cannot_dispatch(case):
    journal = AliasJournal(case.db)
    for state, phase in [("closed", "reserved"), ("open", "legacy_unknown")]:
        case.db.operation.state, case.db.operation.phase = state, phase
        with pytest.raises(IndexTrackingError):
            await journal.dispatch(case.db.operation.id)


def proof_for(claim):
    from ai_workshop.labs.rag.indexing.alias_recovery_types import TerminationProof

    start = datetime(2026, 9, 30, tzinfo=UTC)
    return TerminationProof(
        request_id=claim.request_id,
        operation_id=claim.snapshot.operation_id,
        snapshot_sha256=claim.snapshot.sha256,
        cluster_uuid=claim.snapshot.cluster_uuid,
        container_id="a" * 64,
        protected_mount_sha256="b" * 64,
        config_sha256="c" * 64,
        client_inventory_sha256="d" * 64,
        deployment_history_sha256="e" * 64,
        stable_node_id="node",
        old_ephemeral_id="old",
        new_ephemeral_id="new",
        old_jvm_start_at=start,
        clients_terminated_at=start + timedelta(seconds=1),
        server_stopped_at=start + timedelta(seconds=2),
        server_started_at=start + timedelta(seconds=3),
        new_jvm_start_at=start + timedelta(seconds=3),
        verified_at=start + timedelta(seconds=4),
        schema_version=1,
    )


async def test_terminated_proof_is_typed_bound_and_revalidated(case):
    case.db.operation.phase = "legacy_unknown"
    claim = await freeze(case)
    proof = proof_for(claim)

    class Collector:
        async def collect_verified_end(self, requested):
            assert requested == claim
            return proof

        async def revalidate(self, requested, evidence):
            assert requested == claim and evidence == proof

    case.service.proof_port = Collector()
    receipt = await case.service.recover_terminated(claim)
    assert receipt.result_code == "recovered_terminated"
    assert receipt.proof == proof and receipt.proof_sha256 == proof.sha256
    assert await case.service.recover_terminated(claim) == receipt


async def test_reserved_termination_rejects_before_disruptive_collector_io(case):
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    claim = await freeze(case)
    before = await case.service.readback(
        claim.snapshot.operation_id, claim.actor_id, claim.request_id
    )
    calls = []

    class Collector:
        async def collect_verified_end(self, requested):
            calls.append("collect")
            return proof_for(requested)

        async def revalidate(self, requested, proof):
            calls.append("revalidate")

    case.service.proof_port = Collector()
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_required"):
        await case.service.recover_terminated(claim)
    assert calls == [], "An ineligible request must never initiate a controlled restart"
    after = await case.service.readback(
        claim.snapshot.operation_id, claim.actor_id, claim.request_id
    )
    assert after == before
    assert after.state == "open" and after.snapshot.phase == "reserved"
    assert after.gate_state == "frozen" and after.claim == claim and after.receipt is None


@pytest.mark.parametrize(
    "bad", ["json", "wrong_request", "same_incarnation", "bad_order", "predates_request"]
)
async def test_incomplete_or_caller_written_proof_keeps_open(case, bad):
    from dataclasses import replace

    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    case.db.operation.phase = "legacy_unknown"
    claim = await freeze(case)
    proof = proof_for(claim)
    if bad == "wrong_request":
        proof = replace(proof, request_id=uuid4())
    elif bad == "same_incarnation":
        proof = replace(proof, new_ephemeral_id=proof.old_ephemeral_id)
    elif bad == "bad_order":
        proof = replace(proof, server_stopped_at=proof.server_started_at)
    elif bad == "predates_request":
        proof = replace(
            proof,
            old_jvm_start_at=proof.old_jvm_start_at - timedelta(days=30),
            clients_terminated_at=proof.clients_terminated_at - timedelta(days=30),
            server_stopped_at=proof.server_stopped_at - timedelta(days=30),
            server_started_at=proof.server_started_at - timedelta(days=30),
            new_jvm_start_at=proof.new_jvm_start_at - timedelta(days=30),
            verified_at=proof.verified_at - timedelta(days=30),
        )
    else:
        proof = {"terminated": True}

    class Collector:
        async def collect_verified_end(self, requested):
            return proof

        async def revalidate(self, requested, evidence):
            pass

    case.service.proof_port = Collector()
    with pytest.raises(AliasRecoveryError, match="proof_invalid"):
        await case.service.recover_terminated(claim)
    assert case.db.operation.state == "open"


@pytest.mark.parametrize("change", ["binding", "environment"])
async def test_configuration_change_after_freeze_keeps_operation_open(case, change):
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    claim = await freeze(case)
    if change == "binding":
        case.service.settings.rag_index_store_id = "renamed_store"
    else:
        case.service.settings.environment = "production"
    with pytest.raises(AliasRecoveryError):
        await case.service.recover_not_dispatched(claim)
    assert case.db.operation.state == "open"


async def test_collector_revocation_is_rechecked_in_final_atomic_transaction(case):
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    case.db.operation.phase = "dispatching"
    claim = await freeze(case)

    class Collector:
        async def collect_verified_end(self, requested):
            return proof_for(requested)

        async def revalidate(self, requested, proof):
            case.db.rows[UserRecord, case.db.actor].is_active = False

    case.service.proof_port = Collector()
    with pytest.raises(AliasRecoveryError, match="actor_denied"):
        await case.service.recover_terminated(claim)
    assert case.db.operation.state == "open"


async def test_changed_receipt_evidence_conflicts_and_release_requires_closed(case):
    from ai_workshop.labs.rag.indexing.alias_models import AliasRecoveryReceiptRecord
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    claim = await freeze(case)
    with pytest.raises(AliasRecoveryError, match="operation_open"):
        await case.service.release(claim)
    await case.service.recover_not_dispatched(claim)
    case.db.rows[AliasRecoveryReceiptRecord, claim.request_id].actor_id = uuid4()
    with pytest.raises(AliasRecoveryError, match="claim_conflict"):
        await case.service.recover_not_dispatched(claim)


async def test_sql_dispatch_commits_once_and_never_replays_after_unknown_commit(case):
    journal = AliasJournal(case.db)
    case.db.commit_fault = "lost_response"
    with pytest.raises(IndexTrackingError, match="writer_unconfirmed"):
        await journal.dispatch(case.db.operation.id)
    compiled = [str(s.compile(dialect=postgresql.dialect())) for s in case.db.statements]
    assert any(
        "rag_alias_operations.id =" in sql
        and "rag_alias_operations.state =" in sql
        and "rag_alias_operations.phase =" in sql
        and "FOR UPDATE" in sql
        for sql in compiled
    )
    assert case.db.operation.phase == "dispatching"
    case.db.commit_fault = None
    with pytest.raises(IndexTrackingError, match="writer_unconfirmed"):
        await journal.dispatch(case.db.operation.id)


@pytest.mark.parametrize(
    "field",
    [
        "alias",
        "targets",
        "indexing_profile_id",
        "document_processing_profile_id",
        "created_at",
        "phase",
    ],
)
async def test_exact_snapshot_comparison_protects_every_scope_field(case, field):
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    claim = await freeze(case)
    values = {
        "alias": "other-active",
        "targets": [],
        "indexing_profile_id": uuid4(),
        "document_processing_profile_id": uuid4(),
        "created_at": datetime(2026, 9, 21, tzinfo=UTC),
        "phase": "legacy_unknown",
    }
    setattr(case.db.operation, field, values[field])
    with pytest.raises(AliasRecoveryError, match="snapshot_changed|binding_mismatch"):
        await case.service.recover_not_dispatched(claim)


@pytest.mark.parametrize("change", ["alias", "target", "profile_kind", "build_membership"])
async def test_noncanonical_scope_is_rejected_before_freeze_or_proof(case, change):
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

    if change == "alias":
        case.db.operation.alias = "foreign-active"
    elif change == "target":
        case.db.operation.targets = ["foreign-index"]
    elif change == "profile_kind":
        case.db.rows[ProfileRecord, case.db.operation.indexing_profile_id].kind = "search"
    else:
        build_id = next(key for (kind, key) in case.db.rows if kind is RagIndexBuildRecord)
        case.db.rows[RagIndexBuildRecord, build_id].document_processing_profile_id = uuid4()
    with pytest.raises(AliasRecoveryError, match="binding_mismatch"):
        await case.service.preview(case.db.operation.id, case.db.actor)


async def test_closed_receipt_replay_does_not_depend_on_later_build_inventory(case):
    claim = await freeze(case)
    receipt = await case.service.recover_not_dispatched(claim)
    for kind, key in list(case.db.rows):
        if kind in {ProfileRecord, RagIndexBuildRecord}:
            del case.db.rows[kind, key]
    assert await case.service.recover_not_dispatched(claim) == receipt
