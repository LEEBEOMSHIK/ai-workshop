"""Durable alias reservations use an independent transaction."""

# ruff: noqa: F811
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.labs.rag.indexing.alias_journal import AliasJournal
from ai_workshop.labs.rag.indexing.alias_models import AliasOperationRecord
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding, IndexTrackingError
from ai_workshop.labs.rag.models.models import ProfileRecord
from alembic import command
from tests.integration.labs.rag.indexing.test_resource_repository import seed_resource
from tests.integration.labs.rag.ingestion.test_artifact_repository import (
    _isolated_database_at,
)
from tests.integration.labs.rag.ingestion.test_artifact_repository import (
    ensure_legacy_document_processing_profile as ensure_legacy_document_processing_profile,
)
from tests.integration.labs.rag.ingestion.test_artifact_repository import (
    migrated_database as migrated_database,
)


async def reserve(journal, *, alias="test-alias", store="rag"):
    return await journal.reserve(
        IndexBinding(store, "synthetic-cluster"), alias, uuid4(), uuid4(), ("test-index",)
    )


@pytest.mark.asyncio
async def test_durable_reservation_busy_and_exact_finish(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    journal = AliasJournal(sessions)
    try:
        operation_id = await reserve(journal)
        async with sessions() as session:
            row = await session.get(AliasOperationRecord, operation_id)
            assert row.state == "open"
            assert row.targets == ["test-index"]
            await session.rollback()
        with pytest.raises(IndexTrackingError, match="rag_index_attempt_busy"):
            await reserve(journal, store="other")
        with pytest.raises(IndexTrackingError, match="rag_index_writer_unconfirmed"):
            await journal.finish(uuid4())
        await journal.finish(operation_id)
        await journal.finish(operation_id)
        async with sessions() as session:
            row = await session.get(AliasOperationRecord, operation_id)
            assert (row.state, row.result_code) == ("closed", "confirmed")
            assert row.closed_at is not None
        assert await reserve(journal) != operation_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_competing_reservations_only_one_open(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        results = await asyncio.gather(
            reserve(AliasJournal(sessions), alias="race-alias"),
            reserve(AliasJournal(sessions), alias="race-alias"),
            return_exceptions=True,
        )
        errors = [r for r in results if isinstance(r, IndexTrackingError)]
        assert len(errors) == 1
        assert errors[0].code == "rag_index_attempt_busy"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reservation_survives_server_prepared_generic_plan(migrated_database):
    # Force repeated INSERTs through one connection beyond psycopg's prepare threshold.
    engine = create_async_engine(
        migrated_database.database_url,
        pool_size=1,
        max_overflow=0,
        connect_args={"prepare_threshold": 0},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        journal = AliasJournal(sessions)
        for number in range(15):
            operation_id = await reserve(journal, alias=f"prepared-plan-{number}")
            await journal.finish(operation_id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_profile_lock_does_not_block_independent_reservation(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
        async with sessions.begin() as outer:
            await outer.scalar(
                select(ProfileRecord)
                .where(ProfileRecord.id == resource.indexing_profile_id)
                .with_for_update()
            )
            operation_id = await asyncio.wait_for(
                AliasJournal(sessions).reserve(
                    resource.binding,
                    resource.alias,
                    resource.indexing_profile_id,
                    resource.document_processing_profile_id,
                    (resource.index_name,),
                ),
                timeout=5,
            )
            await outer.rollback()
        async with sessions() as session:
            assert (await session.get(AliasOperationRecord, operation_id)).state == "open"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"alias": "changed"},
        {"targets": ["changed"]},
        {"state": "closed"},
        {"targets": {"bad": "shape"}},
    ],
)
async def test_database_rejects_invalid_or_mutated_rows(migrated_database, changes):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        operation_id = await reserve(AliasJournal(sessions), alias=f"guard-{uuid4().hex}")
        with pytest.raises(DBAPIError):
            async with sessions.begin() as session:
                await session.execute(
                    update(AliasOperationRecord)
                    .where(AliasOperationRecord.id == operation_id)
                    .values(**changes)
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_closed_operation_cannot_reopen(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        journal = AliasJournal(sessions)
        operation_id = await reserve(journal, alias="closed-alias")
        await journal.finish(operation_id)
        with pytest.raises(DBAPIError):
            async with sessions.begin() as session:
                await session.execute(
                    text(
                        "UPDATE rag_alias_operations SET state='open', result_code=NULL, "
                        "closed_at=NULL WHERE id=:id"
                    ),
                    {"id": operation_id},
                )
    finally:
        await engine.dispose()


def test_alias_migration_empty_roundtrip_and_populated_refusal(migrated_database):
    # The module fixture keeps the inherited autouse fixture off the configured root DB.
    with _isolated_database_at("0042_rag_index_resources") as database:
        command.upgrade(database.config, "0043_rag_alias_operations")
        command.downgrade(database.config, "0042_rag_index_resources")
        command.upgrade(database.config, "0043_rag_alias_operations")

        async def seed():
            engine = create_async_engine(database.database_url)
            try:
                await reserve(AliasJournal(async_sessionmaker(engine)))
            finally:
                await engine.dispose()

        asyncio.run(seed())
        with pytest.raises(DBAPIError, match="alias operations must be resolved"):
            command.downgrade(database.config, "0042_rag_index_resources")
