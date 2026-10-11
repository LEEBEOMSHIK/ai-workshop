"""Real repository transactions over a deterministic SQL transport double."""

from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from ai_workshop.labs.rag.indexing.access_epoch_repository import SqlAlchemyAccessEpochRepository
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    ControlSettlement,
    CutoverActionKind,
    OriginalDeploymentIdentity,
)
from ai_workshop.labs.rag.indexing.alias_models import AliasClusterGateRecord
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError
from tests.unit.labs.rag.indexing.test_alias_recovery import Database


class EpochDatabase(Database):
    def __init__(self):
        super().__init__(phase="legacy_unknown")
        self.lose_next_commit_response = False

    def add(self, row):
        keys = inspect(type(row)).primary_key
        key = tuple(getattr(row, column.key) for column in keys)
        self.rows[type(row), key] = row

    @asynccontextmanager
    async def begin(self):
        before = deepcopy(self.rows)
        try:
            yield self
        except BaseException:
            self.rows = before
            raise
        if self.lose_next_commit_response:
            self.lose_next_commit_response = False
            raise OperationalError("synthetic", {}, Exception("must-not-leak"))

    async def scalars(self, statement):
        params = statement.compile(dialect=postgresql.dialect()).params
        entity = statement.column_descriptions[0]["entity"]
        rows = [
            r
            for (kind, _), r in self.rows.items()
            if kind is entity
            and all(getattr(r, name.rsplit("_", 1)[0]) == value for name, value in params.items())
        ]
        return type("Rows", (), {"all": lambda _: rows})()


async def setup():
    from ai_workshop.config import Settings
    from ai_workshop.labs.rag.indexing.alias_recovery import AliasRecoveryService
    from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding

    db = EpochDatabase()
    settings = Settings(
        _env_file=None,
        secret_key="synthetic-test-secret-value-00000000",
        rag_index_store_id="rag",
        rag_index_cluster_uuid="cluster",
    )
    recovery = AliasRecoveryService(db, settings)
    snap = await recovery.preview(db.operation_id, db.actor)
    claim = await recovery.freeze(db.operation_id, db.actor, UUID(int=101), snap.sha256)
    original = OriginalDeploymentIdentity(
        "c" * 64,
        "a" * 64,
        "cluster",
        "stable",
        "old",
        "d" * 64,
        "e" * 64,
        "f" * 64,
        "1" * 64,
        "2" * 64,
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    repo = SqlAlchemyAccessEpochRepository(
        db, IndexBinding("rag", "cluster"), settings.elasticsearch_index_prefix
    )
    return db, repo, claim, original


async def settle_key_group(repo, epoch, parent, moment):
    from ai_workshop.labs.rag.indexing.access_epoch_keys import (
        KeyResult,
        SqlAlchemyEpochKeyRepository,
    )

    keys = SqlAlchemyEpochKeyRepository(repo, clock=lambda: moment)
    for role in ("reader", "writer", "collector"):
        child = await keys.reserve_issue(epoch, parent, role, "c" * 64)
        await keys.settle(
            epoch,
            child,
            KeyResult(
                "issued", f"key-{role}", role, child.issuance_id, child.permissions_sha256, moment
            ),
        )
    manifest = await keys.complete_manifest(epoch, parent)
    assert manifest is not None
    return manifest


async def test_acquire_exact_replay_and_competing_claim_refusal():
    db, repo, claim, original = await setup()
    first = await repo.acquire(claim, original)
    assert await repo.acquire(claim, original) == first
    with pytest.raises(AliasRecoveryError, match="rag_alias_claim_conflict"):
        await repo.acquire(replace(claim, request_id=UUID(int=102)), original)
    assert db.operation.state == "open"


async def test_unknown_action_cannot_be_reissued_or_bypass_predecessor():
    db, repo, claim, original = await setup()
    epoch = await repo.acquire(claim, original)
    action = await repo.reserve_action(
        epoch, CutoverActionKind.STOP_REGISTERED_APPS, ControlExpectedIdentity("{}", 0)
    )
    await repo.settle_action(
        action,
        ControlSettlement(
            action.action_id,
            action.execution_id,
            action.executor_generation,
            "unknown",
            "{}",
            datetime.now(UTC),
        ),
    )
    with pytest.raises(AliasRecoveryError, match="rag_alias_claim_conflict"):
        await repo.reserve_action(
            epoch, CutoverActionKind.STOP_OLD, ControlExpectedIdentity("{}", action.sequence)
        )
    state = await repo.readback(claim)
    assert state.phase == "prepared" and state.actions[-1].outcome == "unknown"
    assert state.gate_state == "frozen" and db.operation.state == "open"


async def test_lost_reservation_ack_reads_same_execution_without_reissue():
    db, repo, claim, original = await setup()
    epoch = await repo.acquire(claim, original)
    db.lose_next_commit_response = True
    with pytest.raises(AliasRecoveryError, match="rag_alias_commit_unknown"):
        await repo.reserve_action(
            epoch, CutoverActionKind.STOP_REGISTERED_APPS, ControlExpectedIdentity("{}", 0)
        )
    state = await repo.readback(claim)
    assert len(state.actions) == 1 and state.actions[0].outcome == "pending"
    assert state.prepared == epoch
    assert next(r for (k, _), r in db.rows.items() if k is AliasClusterGateRecord).state == "frozen"


async def closure_case():
    import json
    from hashlib import sha256

    from ai_workshop.labs.rag.indexing.access_epoch_types import (
        VerifiedAccessEpoch,
        decode_termination_proof,
    )
    from ai_workshop.labs.rag.indexing.alias_recovery_types import utc_text
    from tests.unit.labs.rag.indexing.access_epoch_fixtures import case

    db, repo, claim, original = await setup()
    c = case()
    manifest_sha = sha256(b'{"generation":"synthetic"}').hexdigest()
    original = replace(
        original,
        daemon_sha256=manifest_sha,
        volume_sha256=manifest_sha,
        mount_sha256=manifest_sha,
        image_sha256=manifest_sha,
        config_sha256=manifest_sha,
        deployment_sha256=manifest_sha,
    )
    epoch = await repo.acquire(claim, original)
    now = datetime.now(UTC)
    from datetime import timedelta

    facts = c.facts | {
        "request_id": str(claim.request_id),
        "operation_id": str(claim.snapshot.operation_id),
        "actor_id": str(claim.actor_id),
        "snapshot_sha256": claim.snapshot.sha256,
        "access_epoch_id": epoch.binding.access_epoch_id,
        "execution_id": epoch.binding.execution_id,
        "old_jvm_start_at": utc_text(original.jvm_start_at),
        "old_server_stopped_at": utc_text(now - timedelta(seconds=60)),
        "old_container_retired_at": utc_text(now - timedelta(seconds=50)),
        "new_server_started_at": utc_text(now - timedelta(seconds=40)),
        "new_jvm_start_at": utc_text(now - timedelta(seconds=30)),
        "access_verified_at": utc_text(now - timedelta(seconds=20)),
        "verified_at": utc_text(now - timedelta(seconds=10)),
    }
    order = tuple(k for k in CutoverActionKind if k != CutoverActionKind.START_REGISTERED_APPS)
    sequence = 0
    for position, kind in enumerate(order):
        moment = now - timedelta(seconds=100 - position)
        repo.clock = lambda moment=moment: moment
        action = await repo.reserve_action(epoch, kind, ControlExpectedIdentity("{}", sequence))
        manifest = {"generation": "synthetic"}
        if kind == CutoverActionKind.STOP_OLD:
            manifest = {
                "container_id": original.container_id,
                "finished_at": facts["old_server_stopped_at"],
            }
        elif kind == CutoverActionKind.RETIRE_OLD:
            manifest = {
                "container_id": original.container_id,
                "retired_at": facts["old_container_retired_at"],
            }
        elif kind == CutoverActionKind.ISSUE_ROLE_KEY:
            from ai_workshop.labs.rag.indexing.access_epoch_keys import (
                KeyResult,
                SqlAlchemyEpochKeyRepository,
            )

            keys = SqlAlchemyEpochKeyRepository(repo, clock=lambda moment=moment: moment)
            for role in ("reader", "writer", "collector"):
                child = await keys.reserve_issue(epoch, action, role, "c" * 64)
                await keys.settle(
                    epoch,
                    child,
                    KeyResult(
                        "issued",
                        f"key-{role}",
                        role,
                        child.issuance_id,
                        child.permissions_sha256,
                        moment,
                    ),
                )
            manifest = await keys.complete_manifest(epoch, action)
            assert manifest is not None
        await repo.settle_action(
            action,
            ControlSettlement(
                action.action_id,
                action.execution_id,
                action.executor_generation,
                "settled",
                json.dumps(manifest, sort_keys=True, separators=(",", ":")),
                moment + timedelta(microseconds=1),
            ),
        )
        sequence = (await repo.readback(claim)).actions[-1].event_sequence
    repo.clock = lambda: datetime.now(UTC)
    proof = decode_termination_proof(facts)
    verified = VerifiedAccessEpoch(
        epoch.binding,
        0,
        json.dumps(facts, sort_keys=True, separators=(",", ":")),
        c.manifests,
        4,
        6,
    )
    return db, repo, claim, epoch, verified, proof


async def test_verified_floor_requires_exact_protected_anchor_then_atomic_close():
    db, repo, claim, epoch, verified, proof = await closure_case()
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await repo.mark_verified(epoch, verified, anchor=None)
    floor = repo.floor_from_verified(verified)
    await repo.mark_verified(epoch, verified, anchor=floor)
    db.lose_next_commit_response = True
    with pytest.raises(AliasRecoveryError, match="rag_alias_commit_unknown"):
        await repo.close_access_epoch(claim, proof)
    state = await repo.readback(claim)
    assert state.operation_state == "closed" and state.phase == "receipted"
    assert state.receipt.proof == proof and state.gate_state == "frozen"
    assert await repo.close_access_epoch(claim, proof) == state.receipt


async def test_forged_proof_does_not_close_and_original_identity_is_preserved():
    db, repo, claim, epoch, verified, proof = await closure_case()
    floor = repo.floor_from_verified(verified)
    await repo.mark_verified(epoch, verified, anchor=floor)
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await repo.close_access_epoch(claim, replace(proof, protected_image_sha256="9" * 64))
    assert db.operation.state == "open"


async def test_verified_phase_alone_cannot_replace_settled_control_history():
    db, repo, claim, epoch, verified, proof = await closure_case()
    from ai_workshop.labs.rag.indexing.access_epoch_models import AccessEpochEventRecord

    db.rows = {key: row for key, row in db.rows.items() if key[0] is not AccessEpochEventRecord}
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await repo.mark_verified(epoch, verified, anchor=repo.floor_from_verified(verified))
    assert db.operation.state == "open"
