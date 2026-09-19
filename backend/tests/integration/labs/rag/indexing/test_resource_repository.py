from uuid import uuid4

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord, RagProjectionRecord
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.indexing.resource_models import (
    RagIndexAttemptRecord,
    RagIndexResourceRecord,
)
from ai_workshop.labs.rag.indexing.resource_repository import SqlAlchemyRagIndexRepository
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding, IndexTrackingError
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.models.document_processing import (
    index_namespace_document_processing_profile_id,
)
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from tests.integration.labs.rag.ingestion.test_artifact_repository import (
    _seed_official_ingestion,
)
from tests.integration.labs.rag.ingestion.test_artifact_repository import (
    ensure_legacy_document_processing_profile as ensure_legacy_document_processing_profile,
)
from tests.integration.labs.rag.ingestion.test_artifact_repository import (
    migrated_database as migrated_database,
)

BINDING = IndexBinding("rag", "test-cluster")


async def seed_resource(session):
    seed = await _seed_official_ingestion(session, label="index")
    projection = await session.get(RagProjectionRecord, seed.projection_id)
    build = RagIndexBuildRecord(
        id=uuid4(),
        projection_id=seed.projection_id,
        document_processing_profile_id=projection.document_processing_profile_id,
        indexing_profile_id=projection.indexing_profile_id,
        status="building",
        is_active=False,
    )
    session.add(build)
    await session.flush()
    ingestion = await session.get(RagIngestionJobRecord, seed.job_id)
    ingestion.index_build_id = build.id
    await session.flush()
    descriptor = IndexDescriptor(3, "cosine")
    name = descriptor.concrete_index_name(
        "test",
        build.indexing_profile_id,
        build.id,
        document_processing_profile_id=index_namespace_document_processing_profile_id(
            build.document_processing_profile_id
        ),
    )
    alias = descriptor.active_alias(
        "test",
        build.indexing_profile_id,
        document_processing_profile_id=index_namespace_document_processing_profile_id(
            build.document_processing_profile_id
        ),
    )
    return await SqlAlchemyRagIndexRepository(session).register(
        build.id, BINDING, descriptor, name, alias
    )


@pytest.mark.asyncio
async def test_revision_attempts_identity_and_rollback(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
        async with sessions.begin() as session:
            repo = SqlAlchemyRagIndexRepository(session)
            claim = await repo.reserve(resource.build_id, "a" * 64, chunk_ids_sha256="c" * 64)
            assert claim.resource.revision == 2
        async with sessions.begin() as session:
            repo = SqlAlchemyRagIndexRepository(session)
            with pytest.raises(IndexTrackingError, match="attempt_busy"):
                await repo.reserve(resource.build_id, "a" * 64, chunk_ids_sha256="c" * 64)
            claim = await repo.observe_uuid(claim, "uuid-one")
            assert claim.resource.revision == 3
        async with sessions.begin() as session:
            repo = SqlAlchemyRagIndexRepository(session)
            assert (await repo.observe_uuid(claim, "uuid-one")).resource.revision == 3
            with pytest.raises(IndexTrackingError, match="identity_conflict"):
                await repo.observe_uuid(claim, "uuid-two")
            await repo.finish(claim, "prepared")
            await repo.advance([resource.build_id])
            assert (await repo.get(resource.build_id)).revision == 4
        async with sessions() as session:
            repo = SqlAlchemyRagIndexRepository(session)
            with pytest.raises(IndexTrackingError, match="input_conflict"):
                await repo.reserve(resource.build_id, "b" * 64, chunk_ids_sha256="c" * 64)
            await session.rollback()
            await repo.advance([resource.build_id])
            await session.rollback()
            assert (await repo.get(resource.build_id)).revision == 4
        async with sessions.begin() as session:
            repo = SqlAlchemyRagIndexRepository(session)
            retry = await repo.reserve(resource.build_id, "a" * 64, chunk_ids_sha256="c" * 64)
            assert retry.attempt_id != claim.attempt_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_current_relation_conflict_blocks_reservation(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
            await session.execute(
                update(AssetSourceRelationRecord)
                .where(AssetSourceRelationRecord.resource_id == resource.build_id)
                .values(resource_revision=8)
            )
        async with sessions.begin() as session:
            with pytest.raises(IndexTrackingError, match="inventory_incomplete"):
                await SqlAlchemyRagIndexRepository(session).reserve(
                    resource.build_id, "a" * 64, chunk_ids_sha256="c" * 64
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_restrict_open_unique_and_cross_profile(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
        for model, key in [
            (RagIndexBuildRecord, resource.build_id),
            (RagProjectionRecord, resource.projection_id),
        ]:
            async with sessions() as session:
                with pytest.raises(IntegrityError):
                    await session.execute(delete(model).where(model.id == key))
                await session.rollback()
        async with sessions.begin() as session:
            await SqlAlchemyRagIndexRepository(session).reserve(
                resource.build_id, "a" * 64, chunk_ids_sha256="c" * 64
            )
        async with sessions() as session:
            session.add(
                RagIndexAttemptRecord(
                    id=uuid4(), build_id=resource.build_id, operation="prepare", state="open"
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()
        async with sessions() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    update(RagIndexResourceRecord)
                    .where(RagIndexResourceRecord.build_id == resource.build_id)
                    .values(indexing_profile_id=uuid4())
                )
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_registration_identity_and_savepoint_revision(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
        async with sessions.begin() as session:
            repo = SqlAlchemyRagIndexRepository(session)
            same = await repo.register(
                resource.build_id,
                BINDING,
                IndexDescriptor(3, "cosine"),
                resource.index_name,
                resource.alias,
            )
            assert same == resource
            with pytest.raises(IndexTrackingError):
                await repo.register(
                    resource.build_id,
                    IndexBinding("other", "cluster-two"),
                    IndexDescriptor(3, "cosine"),
                    resource.index_name,
                    resource.alias,
                )
            savepoint = await session.begin_nested()
            await repo.advance([resource.build_id])
            assert (await repo.get(resource.build_id)).revision == 2
            await savepoint.rollback()
            assert (await repo.get(resource.build_id)).revision == 1
            await repo.advance([resource.build_id])
            assert (await repo.get(resource.build_id)).revision == 2
        async with sessions.begin() as session:
            repo = SqlAlchemyRagIndexRepository(session)
            claim = await repo.reserve(resource.build_id, "a" * 64, chunk_ids_sha256="c" * 64)
            await repo.finish(claim, "rag_index_observation_failed")
        async with sessions.begin() as session:
            repo = SqlAlchemyRagIndexRepository(session)
            with pytest.raises(IndexTrackingError, match="input_conflict"):
                await repo.reserve(resource.build_id, "a" * 64, chunk_ids_sha256="d" * 64)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_source_delete_and_identity_mutation_restricted(migrated_database):
    from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
    from ai_workshop.platform.jobs.models import JobRecord

    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
        for model, key in [
            (DocumentRecord, resource.document_id),
            (AssetVersionRecord, resource.asset_version_id),
            (JobRecord, resource.job_id),
        ]:
            async with sessions() as session:
                with pytest.raises(IntegrityError):
                    await session.execute(delete(model).where(model.id == key))
                await session.rollback()
        for values in [
            {"index_name": "other"},
            {"cluster_uuid": "other"},
            {"job_id": uuid4()},
            {"workspace_id": uuid4()},
            {"revision": 0},
            {"input_fingerprint": "a" * 64},
        ]:
            async with sessions() as session:
                with pytest.raises(IntegrityError):
                    await session.execute(
                        update(RagIndexResourceRecord)
                        .where(RagIndexResourceRecord.build_id == resource.build_id)
                        .values(**values)
                    )
                await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_reserve_has_exactly_one_writer(migrated_database):
    import asyncio

    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)

        async def reserve():
            try:
                async with sessions.begin() as session:
                    return await SqlAlchemyRagIndexRepository(session).reserve(
                        resource.build_id, "a" * 64, chunk_ids_sha256="c" * 64
                    )
            except IndexTrackingError as exc:
                return exc.code

        results = await asyncio.gather(reserve(), reserve())
        assert results.count("rag_index_attempt_busy") == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_stale_open_claim_cannot_finalize_after_other_transaction_advance(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
        async with sessions.begin() as session:
            claim = await SqlAlchemyRagIndexRepository(session).reserve(
                resource.build_id, "a" * 64, chunk_ids_sha256="c" * 64
            )
        async with sessions.begin() as session:
            await SqlAlchemyRagIndexRepository(session).advance([resource.build_id])
        async with sessions.begin() as session:
            with pytest.raises(IndexTrackingError, match="inventory_changed"):
                await SqlAlchemyRagIndexRepository(session).finish(
                    claim, "rag_index_observation_failed"
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_composite_foreign_keys_reject_cross_source_profile_and_job(migrated_database):
    from sqlalchemy import insert

    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            first = await seed_resource(session)
            second = await seed_resource(session)
            second_row = await session.get(RagIndexResourceRecord, second.build_id)
            values = {
                column.name: getattr(second_row, column.name)
                for column in RagIndexResourceRecord.__table__.columns
            }
            await session.execute(
                delete(RagIndexResourceRecord).where(
                    RagIndexResourceRecord.build_id == second.build_id
                )
            )
        for changes in [
            {"indexing_profile_id": first.indexing_profile_id},
            {"projection_id": first.projection_id},
            {"job_id": first.job_id},
            {"asset_version_id": first.asset_version_id},
            {"document_id": first.document_id},
            {"workspace_id": first.workspace_id},
        ]:
            async with sessions() as session:
                with pytest.raises(IntegrityError) as raised:
                    await session.execute(
                        insert(RagIndexResourceRecord).values(**(values | changes))
                    )
                assert "fk_rag_index_resources_" in str(raised.value.orig)
                await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_finalization_rollback_preserves_open_attempt_and_revision(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
        async with sessions.begin() as session:
            claim = await SqlAlchemyRagIndexRepository(session).reserve(
                resource.build_id, "a" * 64, chunk_ids_sha256="c" * 64
            )
        async with sessions.begin() as session:
            claim = await SqlAlchemyRagIndexRepository(session).observe_uuid(claim, "uuid-one")
        async with sessions() as session:
            repo = SqlAlchemyRagIndexRepository(session)
            build = await session.get(RagIndexBuildRecord, resource.build_id)
            build.status = "prepared"
            build.indexed_document_count = 3
            await repo.finish(claim, "prepared")
            await repo.advance([resource.build_id])
            assert (await repo.get(resource.build_id)).revision == claim.resource.revision + 1
            await session.rollback()
        async with sessions.begin() as session:
            repo = SqlAlchemyRagIndexRepository(session)
            assert (await repo.get(resource.build_id)).revision == claim.resource.revision
            attempt = await session.get(RagIndexAttemptRecord, claim.attempt_id)
            assert attempt.state == "open"
            build = await session.get(RagIndexBuildRecord, resource.build_id)
            assert build.status == "building"
            assert build.indexed_document_count is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_open_attempt_is_busy_before_changed_input_comparison(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await seed_resource(session)
        async with sessions.begin() as session:
            claim = await SqlAlchemyRagIndexRepository(session).reserve(
                resource.build_id, "a" * 64, chunk_ids_sha256="c" * 64
            )
        async with sessions.begin() as session:
            repo = SqlAlchemyRagIndexRepository(session)
            with pytest.raises(IndexTrackingError, match="rag_index_attempt_busy"):
                await repo.reserve(resource.build_id, "b" * 64, chunk_ids_sha256="d" * 64)
            assert await repo.get(resource.build_id) == claim.resource
            attempt = await session.get(RagIndexAttemptRecord, claim.attempt_id)
            assert attempt.state == "open"
            assert attempt.result_code is None
        async with sessions.begin() as session:
            await SqlAlchemyRagIndexRepository(session).finish(
                claim, "rag_index_observation_failed"
            )
        async with sessions.begin() as session:
            with pytest.raises(IndexTrackingError, match="rag_index_input_conflict"):
                await SqlAlchemyRagIndexRepository(session).reserve(
                    resource.build_id, "b" * 64, chunk_ids_sha256="d" * 64
                )
    finally:
        await engine.dispose()
