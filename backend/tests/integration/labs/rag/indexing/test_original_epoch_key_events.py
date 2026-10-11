"""Opt-in0064 DDL and role key guards on the original DB; always outer rollback.

The existing account/claim are reused. Synthetic public key identities exercise
storage guards only: no key, native process, ES request, release or parity.
SAVEPOINTs here cannot establish committed multi-connection concurrency.
"""

import importlib.util
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from ai_workshop.labs.rag.indexing.access_epoch_keys import (
    KeyResult,
    SqlAlchemyEpochKeyRepository,
)
from ai_workshop.labs.rag.indexing.access_epoch_models import AccessEpochKeyEventRecord
from ai_workshop.labs.rag.indexing.access_epoch_repository import SqlAlchemyAccessEpochRepository
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    ControlSettlement,
    CutoverActionKind,
    OriginalDeploymentIdentity,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_models import AliasOperationRecord
from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
from ai_workshop.labs.rag.indexing.alias_recovery_repository import (
    SqlAlchemyAliasRecoveryRepository,
    snapshot,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import FrozenAliasClaim, utc_text
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding
from ai_workshop.shared.db import create_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("TASK_VERIFY_ORIGINAL_EPOCH_KEYS") != "1",
        reason="Explicit original0064 outer rollback verification is required",
    ),
]


@pytest.fixture
async def original_keys() -> AsyncIterator[SimpleNamespace]:
    root = Path(__file__).resolve().parents[6]
    settings = load_original_settings(root)
    engine = create_engine(settings)
    engine.sync_engine.hide_parameters = True
    db_errors = []

    @event.listens_for(engine.sync_engine, "handle_error")
    def capture_guard_error(context):
        # Only the controlled trigger's primary diagnostic; no SQL/parameters.
        diag = getattr(context.original_exception, "diag", None)
        db_errors.append(getattr(diag, "message_primary", "database_error"))

    @event.listens_for(engine.sync_engine, "commit")
    def deny_commit(_connection: Connection) -> None:
        raise AssertionError("Original key verification cannot COMMIT")

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "0063_rag_numeric_proof"
                )
                assert (
                    await connection.scalar(
                        text("SELECT to_regclass('rag_access_epoch_key_events')")
                    )
                    is None
                )
                spec = importlib.util.spec_from_file_location(
                    "epoch_key_migration",
                    root / "backend/alembic/versions/0064_rag_epoch_key_events.py",
                )
                assert spec is not None and spec.loader is not None
                migration = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(migration)
                # psycopg executes this trusted fixed DDL as one unparameterized
                # command. Its transaction remains the guarded outer transaction.
                await connection.execute(text(migration.SCHEMA))
                sessions = async_sessionmaker(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )
                binding = IndexBinding(settings.rag_index_store_id, settings.rag_index_cluster_uuid)
                recovery = SqlAlchemyAliasRecoveryRepository(
                    sessions, binding, settings.elasticsearch_index_prefix
                )
                async with sessions() as session:
                    operations = (
                        await session.scalars(
                            select(AliasOperationRecord).where(
                                AliasOperationRecord.cluster_uuid == binding.cluster_uuid,
                                AliasOperationRecord.state == "open",
                            )
                        )
                    ).all()
                    assert len(operations) == 1
                    snap = snapshot(operations[0])
                    gate = await connection.execute(
                        text(
                            "SELECT request_id,actor_id,revision FROM rag_alias_cluster_gates "
                            "WHERE cluster_uuid=:cluster AND state='frozen'"
                        ),
                        {"cluster": binding.cluster_uuid},
                    )
                    row = gate.mappings().one()
                    claim = FrozenAliasClaim(
                        snap, row["request_id"], row["actor_id"], row["revision"]
                    )
                assert (
                    await recovery.readback(snap.operation_id, claim.actor_id, claim.request_id)
                ).claim == claim
                repo = SqlAlchemyAccessEpochRepository(
                    sessions, binding, settings.elasticsearch_index_prefix
                )
                identity = OriginalDeploymentIdentity(
                    "a" * 64,
                    "b" * 64,
                    binding.cluster_uuid,
                    "synthetic-stable",
                    "synthetic-ephemeral",
                    *(["c" * 64] * 5),
                    datetime(2026, 1, 1, tzinfo=UTC),
                )
                epoch = await repo.acquire(claim, identity)
                for kind in CutoverActionKind:
                    if kind == CutoverActionKind.START_REGISTERED_APPS:
                        continue
                    state = await repo.readback(claim)
                    seq = state.actions[-1].event_sequence if state.actions else 0
                    parent = await repo.reserve_action(
                        epoch, kind, ControlExpectedIdentity("{}", seq)
                    )
                    if kind == CutoverActionKind.ISSUE_ROLE_KEY:
                        break
                    now = datetime.now(UTC)
                    manifest = {"container_id": identity.container_id}
                    if kind == CutoverActionKind.STOP_OLD:
                        manifest["finished_at"] = utc_text(now)
                    if kind == CutoverActionKind.RETIRE_OLD:
                        manifest["retired_at"] = utc_text(now)
                    await repo.settle_action(
                        parent,
                        ControlSettlement(
                            parent.action_id,
                            parent.execution_id,
                            parent.executor_generation,
                            "settled",
                            canonical_json(manifest),
                            now,
                        ),
                    )
                yield SimpleNamespace(
                    sessions=sessions,
                    connection=connection,
                    epoch=epoch,
                    parent=parent,
                    repo=repo,
                    keys=SqlAlchemyEpochKeyRepository(repo),
                    db_errors=db_errors,
                )
                assert connection.in_transaction()
            finally:
                if transaction.is_active:
                    await transaction.rollback()
            assert (
                await connection.scalar(text("SELECT to_regclass('rag_access_epoch_key_events')"))
                is None
            )
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "0063_rag_numeric_proof"
            )
            await connection.rollback()
    finally:
        await engine.dispose()


async def forbidden(case, sql, params):
    with pytest.raises(DBAPIError):
        async with case.sessions.begin() as session:
            await session.execute(text(sql), params)
    assert case.connection.in_transaction()


async def issued(case, action, result="issued"):
    try:
        await case.keys.settle(
            case.epoch,
            action,
            KeyResult(
                result,
                "synthetic-" + action.issuance_id.hex,
                action.role,
                action.issuance_id,
                action.permissions_sha256,
                datetime.now(UTC),
            ),
        )
    except Exception:
        raise AssertionError(
            case.db_errors[-1] if case.db_errors else "key_settlement_failed"
        ) from None


async def test_original_ddl_enforces_three_role_parent_and_append_only_events(original_keys):
    case = original_keys
    parent_sql = """
INSERT INTO rag_access_epoch_events(id,execution_id,action_id,sequence,action_sequence,
 kind,outcome,expected_json,executor_generation,manifest_json,observed_at)
SELECT :id,execution_id,action_id,sequence+1,action_sequence,kind,'settled',expected_json,
 executor_generation,'{}',clock_timestamp() FROM rag_access_epoch_events WHERE action_id=:parent
 AND outcome='pending'
"""
    await forbidden(case, parent_sql, {"id": uuid4(), "parent": case.parent.action_id})
    for role in ("reader", "writer", "collector"):
        action = await case.keys.reserve_issue(case.epoch, case.parent, role, "c" * 64)
        await forbidden(
            case,
            "UPDATE rag_access_epoch_key_events SET role='writer' WHERE action_id=:id",
            {"id": action.action_id},
        )
        await forbidden(
            case,
            "DELETE FROM rag_access_epoch_key_events WHERE action_id=:id",
            {"id": action.action_id},
        )
        await issued(case, action)
        if role != "collector":
            await forbidden(case, parent_sql, {"id": uuid4(), "parent": case.parent.action_id})
    manifest = await case.keys.complete_manifest(case.epoch, case.parent)
    assert manifest is not None
    assert (
        await case.connection.scalar(
            text("SELECT rag_access_epoch_key_group(:exec,:parent)"),
            {"exec": case.parent.execution_id, "parent": case.parent.action_id},
        )
        == manifest
    )
    await case.repo.settle_action(
        case.parent,
        ControlSettlement(
            case.parent.action_id,
            case.parent.execution_id,
            case.parent.executor_generation,
            "settled",
            canonical_json(manifest),
            datetime.now(UTC),
        ),
    )
    assert (await case.repo.readback(case.epoch.binding.claim)).actions[-1].outcome == "settled"


async def test_original_ddl_requires_invalidation_and_no_unknown_reissue(original_keys):
    case = original_keys
    issue = await case.keys.reserve_issue(case.epoch, case.parent, "reader", "c" * 64)
    await case.keys.mark_unknown(case.epoch, issue)
    async with case.sessions() as session:
        pending = await session.scalar(
            select(AccessEpochKeyEventRecord).where(
                AccessEpochKeyEventRecord.action_id == issue.action_id,
                AccessEpochKeyEventRecord.outcome == "pending",
            )
        )
        assert pending is not None
    bypass = """
INSERT INTO rag_access_epoch_key_events(id,execution_id,parent_action_id,action_id,sequence,
 action_sequence,executor_generation,role,issuance_id,kind,key_id,replaces_issuance_id,
 permissions_sha256,outcome,manifest_json,observed_at)
SELECT :id,execution_id,parent_action_id,:action,
 (SELECT max(sequence)+1 FROM rag_access_epoch_key_events),
 (SELECT max(sequence)+1 FROM rag_access_epoch_key_events),executor_generation,role,:issuance,
 kind,NULL,:replaces,permissions_sha256,'pending',NULL,clock_timestamp()
FROM rag_access_epoch_key_events WHERE action_id=:old AND outcome='pending'
"""
    values = {
        "id": uuid4(),
        "action": uuid4(),
        "issuance": uuid4(),
        "replaces": None,
        "old": issue.action_id,
    }
    await forbidden(case, bypass, values)
    await issued(case, issue, "issued_inaccessible")
    await forbidden(case, bypass, values | {"id": uuid4(), "replaces": issue.issuance_id})
    revoke = await case.keys.reserve_invalidation(
        case.epoch, case.parent, issue.issuance_id, "synthetic-" + issue.issuance_id.hex
    )
    await issued(case, revoke, "invalidated")
    replacement = await case.keys.reserve_issue(
        case.epoch, case.parent, "reader", "c" * 64, replaces=issue.issuance_id
    )
    assert replacement.issuance_id != issue.issuance_id
