import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord, RagProjectionRecord
from ai_workshop.labs.rag.indexing.alias_journal import AliasJournal
from ai_workshop.labs.rag.indexing.fence_models import RagIndexWriteFenceRecord
from ai_workshop.labs.rag.indexing.resource_repository import SqlAlchemyRagIndexRepository
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding, IndexTrackingError
from ai_workshop.labs.rag.indexing.write_fence import block_index_writes, inspect_index_writers
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from alembic import command
from tests.integration.labs.rag.indexing.test_resource_repository import (
    ensure_legacy_document_processing_profile as ensure_legacy_document_processing_profile,
)
from tests.integration.labs.rag.indexing.test_resource_repository import (
    migrated_database as migrated_database,
)
from tests.integration.labs.rag.indexing.test_resource_repository import seed_resource
from tests.integration.labs.rag.ingestion.test_artifact_repository import _isolated_database_at


@pytest.mark.asyncio
async def test_fence_exact_generation_idempotence_and_immutable(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
        args = sessions, resource.workspace_id, resource.document_id, 1
        assert not await inspect_index_writers(*args)
        with pytest.raises(IndexTrackingError, match="inventory_changed"):
            await block_index_writes(sessions, resource.workspace_id, resource.document_id, 2)
        with pytest.raises(IndexTrackingError, match="inventory_incomplete"):
            await block_index_writes(sessions, uuid4(), resource.document_id, 1)
        await block_index_writes(*args)
        await block_index_writes(*args)
        assert await inspect_index_writers(*args)
        async with sessions() as session:
            fence = await session.get(RagIndexWriteFenceRecord, resource.document_id)
            assert fence.generation == 1
            with pytest.raises(IntegrityError):
                await session.execute(
                    update(RagIndexWriteFenceRecord)
                    .where(RagIndexWriteFenceRecord.document_id == resource.document_id)
                    .values(generation=2)
                )
            await session.rollback()
            with pytest.raises(IntegrityError):
                await session.execute(
                    delete(DocumentRecord).where(DocumentRecord.id == resource.document_id)
                )
            await session.rollback()
        async with sessions.begin() as session:
            await session.execute(
                update(DocumentRecord)
                .where(DocumentRecord.id == resource.document_id)
                .values(lifecycle_generation=2)
            )
        assert not await inspect_index_writers(*args)
        with pytest.raises(IndexTrackingError, match="inventory_changed"):
            await block_index_writes(sessions, resource.workspace_id, resource.document_id, 2)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_open_prepare_and_legacy_build_prevent_drain(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
        args = sessions, resource.workspace_id, resource.document_id, 1
        await block_index_writes(*args)
        async with sessions.begin() as session:
            claim = await SqlAlchemyRagIndexRepository(session).reserve(
                resource.build_id, "a" * 64, chunk_ids_sha256="b" * 64
            )
        assert not await inspect_index_writers(*args)
        async with sessions.begin() as session:
            await SqlAlchemyRagIndexRepository(session).finish(
                claim, "rag_index_observation_failed"
            )
        assert await inspect_index_writers(*args)
        async with sessions.begin() as session:
            version_id, projection_id = uuid4(), uuid4()
            session.add(
                AssetVersionRecord(
                    id=version_id,
                    document_id=resource.document_id,
                    number=2,
                    object_key=f"synthetic/fence/{version_id}",
                    sha256="b" * 64,
                    media_type="text/plain",
                    size=2,
                    status="stored",
                )
            )
            await session.flush()
            session.add(
                RagProjectionRecord(
                    id=projection_id,
                    asset_version_id=version_id,
                    document_processing_profile_id=resource.document_processing_profile_id,
                    indexing_profile_id=resource.indexing_profile_id,
                    status=ProjectionStatus.PENDING,
                )
            )
            await session.flush()
            session.add(
                RagIndexBuildRecord(
                    id=uuid4(),
                    projection_id=projection_id,
                    document_processing_profile_id=resource.document_processing_profile_id,
                    indexing_profile_id=resource.indexing_profile_id,
                    status="building",
                    is_active=False,
                )
            )
        assert not await inspect_index_writers(*args)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_open_alias_blocks_across_bindings_but_not_unrelated_scope(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
        args = sessions, resource.workspace_id, resource.document_id, 1
        await block_index_writes(*args)
        journal = AliasJournal(sessions)
        await journal.reserve(
            IndexBinding("other", "other-cluster"),
            "unrelated-alias",
            uuid4(),
            resource.document_processing_profile_id,
            (),
        )
        assert await inspect_index_writers(*args)
        operation = await journal.reserve(
            IndexBinding("other", "other-cluster"),
            "other-alias",
            resource.indexing_profile_id,
            resource.document_processing_profile_id,
            (),
        )
        assert not await inspect_index_writers(*args)
        await journal.finish(operation)
        assert await inspect_index_writers(*args)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_block_waits_for_existing_profile_writer(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
        args = sessions, resource.workspace_id, resource.document_id, 1
        async with sessions.begin() as writer:
            await writer.scalar(
                select(ProfileRecord.id)
                .where(ProfileRecord.id == resource.indexing_profile_id)
                .with_for_update()
            )
            block = asyncio.create_task(block_index_writes(*args))
            await asyncio.sleep(0.1)
            assert not block.done()
            async with sessions() as observer:
                assert await observer.get(RagIndexWriteFenceRecord, resource.document_id) is None
        await asyncio.wait_for(block, timeout=5)
        assert await inspect_index_writers(*args)
    finally:
        await engine.dispose()


def test_empty_migration_reversible_and_fence_prevents_downgrade():
    with _isolated_database_at("0043_rag_alias_operations") as database:
        command.upgrade(database.config, "0044_rag_index_write_fences")
        command.downgrade(database.config, "0043_rag_alias_operations")
        command.upgrade(database.config, "0044_rag_index_write_fences")

        async def seed():
            engine = create_async_engine(database.database_url)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with sessions.begin() as session:
                    resource = await seed_resource(session)
                await block_index_writes(sessions, resource.workspace_id, resource.document_id, 1)
            finally:
                await engine.dispose()

        asyncio.run(seed())
        with pytest.raises(RuntimeError, match="write_fence_downgrade_blocked"):
            command.downgrade(database.config, "0043_rag_alias_operations")
