"""Opt-in existing DB SAVEPOINT verification, with no provisioning or COMMIT.

The main operator applies0061 first. One shared rollback connection cannot prove
committed multi-connection races, physical commit loss or real termination proof.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from ai_workshop.config import Settings
from ai_workshop.labs.rag.indexing.alias_journal import AliasJournal
from ai_workshop.labs.rag.indexing.alias_models import (
    AliasOperationRecord,
    AliasRecoveryReceiptRecord,
)
from ai_workshop.labs.rag.indexing.alias_recovery import AliasRecoveryService
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding, IndexTrackingError
from ai_workshop.labs.rag.models.document_processing import (
    index_namespace_document_processing_profile_id,
)
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.shared.db import create_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_ORIGINAL_ALIAS_RECOVERY") != "1",
        reason="Explicit original alias recovery rollback verification is required",
    ),
]


@pytest.fixture
async def original() -> AsyncIterator[SimpleNamespace]:
    root = Path(__file__).resolve().parents[6]
    settings = Settings(_env_file=root / ".env")
    assert settings.environment == "local"
    engine = create_engine(settings)

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(_connection: Connection) -> None:
        raise AssertionError("Original alias verification must never COMMIT")

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                assert (
                    await connection.scalar(text("SELECT version_num FROM alembic_version"))
                    == "0061_alias_recovery"
                ), "Apply0061 separately before this test"
                sessions = async_sessionmaker(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )
                async with sessions() as session:
                    actor = await session.scalar(
                        select(UserRecord.id)
                        .where(UserRecord.role == "owner", UserRecord.is_active.is_(True))
                        .limit(1)
                    )
                    assert actor is not None, "An existing active owner is required"
                    existing = await session.scalar(
                        select(AliasOperationRecord)
                        .where(
                            AliasOperationRecord.store_id == settings.rag_index_store_id,
                            AliasOperationRecord.cluster_uuid == settings.rag_index_cluster_uuid,
                        )
                        .order_by(AliasOperationRecord.created_at)
                        .limit(1)
                    )
                    assert existing is not None, "An existing exact alias operation is required"
                    profile_ids = (
                        await session.scalars(
                            select(ProfileRecord.id).where(ProfileRecord.kind == "indexing")
                        )
                    ).all()
                    available_profile_id, alias = None, None
                    for profile_id in profile_ids:
                        candidate = IndexDescriptor(1, "cosine").active_alias(
                            settings.elasticsearch_index_prefix,
                            profile_id,
                            document_processing_profile_id=(
                                index_namespace_document_processing_profile_id(
                                    existing.document_processing_profile_id
                                )
                            ),
                        )
                        occupied = await session.scalar(
                            select(AliasOperationRecord.id).where(
                                AliasOperationRecord.cluster_uuid == existing.cluster_uuid,
                                AliasOperationRecord.alias == candidate,
                                AliasOperationRecord.state == "open",
                            )
                        )
                        if occupied is None:
                            available_profile_id, alias = profile_id, candidate
                            break
                    assert available_profile_id is not None and alias is not None, (
                        "An existing indexing profile with an unoccupied canonical alias "
                        "is required"
                    )
                    # Synthetic journal rows borrow only existing scope identities,
                    # and remain inside the guarded outer rollback transaction.
                    yield SimpleNamespace(
                        sessions=sessions,
                        actor=actor,
                        settings=settings,
                        existing=existing,
                        binding=IndexBinding(existing.store_id, existing.cluster_uuid),
                        profile=available_profile_id,
                        alias=alias,
                        service=AliasRecoveryService(sessions, settings),
                        connection=connection,
                    )
                    await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            finally:
                await transaction.rollback()
                assert not connection.in_transaction()
    finally:
        await engine.dispose()


async def reserve(case):
    # Reuse an unoccupied existing immutable profile scope; no new profile or ES resource.
    return await AliasJournal(case.sessions).reserve(
        case.binding,
        case.alias,
        case.profile,
        case.existing.document_processing_profile_id,
        (),
    )


async def claim_for(case, operation_id):
    preview = await case.service.preview(operation_id, case.actor)
    return await case.service.freeze(operation_id, case.actor, uuid4(), preview.sha256)


async def forbidden_sql(case, sql, params):
    with pytest.raises(DBAPIError):
        async with case.sessions.begin() as session:
            await session.execute(text(sql), params)
            await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    assert case.connection.in_transaction()


async def enforce_receipt_integrity(case):
    # SAVEPOINT release does not fire deferred triggers on the outer rollback
    # transaction. Exercise them now, then restore the production deferred mode.
    async with case.sessions.begin() as session:
        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    assert case.connection.in_transaction()


async def test_original_reserved_receipt_atomic_replay_gate_and_immutability(original):
    case = original
    operation_id = await reserve(case)
    claim = await claim_for(case, operation_id)
    journal = AliasJournal(case.sessions)
    with pytest.raises(IndexTrackingError):
        await journal.dispatch(operation_id)
    with pytest.raises(IndexTrackingError):
        await reserve(case)
    recovered = await case.service.recover_not_dispatched(claim)
    await enforce_receipt_integrity(case)
    assert recovered.result_code == "not_dispatched"
    assert await case.service.recover_not_dispatched(claim) == recovered
    async with case.sessions() as session:
        row = await session.get(AliasOperationRecord, operation_id)
        persisted = await session.get(AliasRecoveryReceiptRecord, claim.request_id)
        assert row.state == "closed" and persisted.operation_id == operation_id
    for sql in [
        "UPDATE rag_alias_operations SET state='open', closed_at=NULL, result_code=NULL "
        "WHERE id=:id",
        "UPDATE rag_alias_operations SET targets='[\"changed\"]'::jsonb WHERE id=:id",
        "DELETE FROM rag_alias_operations WHERE id=:id",
    ]:
        await forbidden_sql(case, sql, {"id": operation_id})
    for sql in [
        "UPDATE rag_alias_recovery_receipts SET proof='{}'::jsonb WHERE request_id=:id",
        "DELETE FROM rag_alias_recovery_receipts WHERE request_id=:id",
    ]:
        await forbidden_sql(case, sql, {"id": claim.request_id})
    await case.service.release(claim)
    with pytest.raises(IndexTrackingError):
        await journal.dispatch(operation_id)
    newer = await reserve(case)
    assert await case.service.recover_not_dispatched(claim) == recovered
    async with case.sessions() as session:
        assert (await session.get(AliasOperationRecord, newer)).state == "open"
    assert case.connection.in_transaction()


async def test_original_phase_guard_and_missing_receipt_rollback(original):
    case = original
    operation_id = await reserve(case)
    await forbidden_sql(
        case,
        "UPDATE rag_alias_operations SET phase='legacy_unknown' WHERE id=:id",
        {"id": operation_id},
    )
    await forbidden_sql(
        case,
        "UPDATE rag_alias_operations SET state='closed', result_code='not_dispatched', "
        "closed_at=now() WHERE id=:id",
        {"id": operation_id},
    )
    async with case.sessions() as session:
        assert (await session.get(AliasOperationRecord, operation_id)).state == "open"
        assert (
            await session.scalar(
                select(AliasRecoveryReceiptRecord).where(
                    AliasRecoveryReceiptRecord.operation_id == operation_id
                )
            )
            is None
        )
    journal = AliasJournal(case.sessions)
    await journal.dispatch(operation_id)
    await forbidden_sql(
        case, "UPDATE rag_alias_operations SET phase='reserved' WHERE id=:id", {"id": operation_id}
    )
    claim = await claim_for(case, operation_id)
    with pytest.raises(AliasRecoveryError, match="proof_required"):
        await case.service.recover_not_dispatched(claim)
    # A successful own-invocation finish can win even while the gate is frozen.
    await journal.finish(operation_id)
    with pytest.raises(AliasRecoveryError, match="already_confirmed"):
        await case.service.recover_not_dispatched(claim)
    await case.service.release(claim)
    assert case.connection.in_transaction()


async def test_original_final_authority_revocation_rolls_back(original):
    case = original
    operation_id = await reserve(case)
    claim = await claim_for(case, operation_id)
    async with case.sessions.begin() as session:
        owner = await session.get(UserRecord, case.actor)
        owner.is_active = False
    with pytest.raises(AliasRecoveryError, match="actor_denied"):
        await case.service.recover_not_dispatched(claim)
    async with case.sessions() as session:
        row = await session.get(AliasOperationRecord, operation_id)
        assert row.state == "open"
    assert case.connection.in_transaction()
