import asyncio
from collections.abc import Iterator
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.platform.assets.domain import Document
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.platform.jobs.models import JobRecord, JobSourceRecord
from ai_workshop.platform.jobs.ownership import JobOwnershipError
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from alembic import command
from tests.integration.platform.assets.original_upload_support import (
    require_explicit_original_test_database,
)
from tests.integration.platform.assets.test_tracked_uploads import seed
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@pytest.fixture(autouse=True)
def ensure_legacy_document_processing_profile() -> None:
    pass


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[IsolatedPublishingDatabase]:
    require_explicit_original_test_database()
    with isolated_publishing_database(monkeypatch) as db:
        command.upgrade(db.config, "head")
        command.downgrade(db.config, "0047_http_upload_intake")
        command.upgrade(db.config, "head")
        yield db


async def candidate(sessions):
    user, workspace = await seed(sessions)
    document = Document(uuid4(), workspace, None, "Synthetic jobs.txt")
    version = document.new_version(
        object_key="synthetic/job-source", sha256="a" * 64, media_type="text/plain", size=5
    )
    async with sessions.begin() as session:
        await SqlAlchemyAssetRepository(session).save(document)
    return Job.create(
        user_id=user.id,
        workspace_id=workspace,
        asset_version_id=version.id,
        type=JobType.VERIFY_ASSET,
        idempotency_key=str(uuid4()),
    ), document.id


def test_atomic_add_repeat_update_rollback_and_legacy(database):
    async def run():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            job, document_id = await candidate(sessions)
            async with sessions() as session:
                await SqlAlchemyJobRepository(session).add(job)
                await session.rollback()
            async with sessions() as session:
                assert await session.get(JobRecord, job.id) is None
                assert await session.get(JobSourceRecord, job.id) is None
                assert not list(await session.scalars(select(AssetSourceRelationRecord)))
            async with sessions.begin() as session:
                repo = SqlAlchemyJobRepository(session)
                await repo.add(job)
                assert job.revision == 1
                job.start(stage="verifying")
                await repo.update(job)
                assert job.revision == 2
                job.succeed(stage="ready")
                await repo.update(job)
                assert job.revision == 3
            async with sessions() as session:
                owner = await session.get(JobSourceRecord, job.id)
                assert owner.document_id == document_id
                current = await session.scalar(
                    select(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.resource_id == job.id
                    )
                )
                assert (
                    current.participant,
                    current.kind,
                    current.resource_revision,
                    current.relation_kind,
                ) == ("platform_jobs", "job", 3, "derived_artifact")
                loaded = await SqlAlchemyJobRepository(session).find_by_id(job.id)
                loaded.stage = "rollback"
                await SqlAlchemyJobRepository(session).update(loaded)
                await session.rollback()
            async with sessions.begin() as session:
                assert (await session.get(JobRecord, job.id)).revision == 3
                legacy = replace(job, id=uuid4(), idempotency_key=str(uuid4()), revision=None)
                session.add(
                    JobRecord(
                        id=legacy.id,
                        user_id=legacy.user_id,
                        workspace_id=legacy.workspace_id,
                        asset_version_id=legacy.asset_version_id,
                        type=legacy.type,
                        idempotency_key=legacy.idempotency_key,
                        status=legacy.status,
                        stage=legacy.stage,
                        attempt=legacy.attempt,
                        revision=None,
                    )
                )
            async with sessions.begin() as session:
                repo = SqlAlchemyJobRepository(session)
                loaded = await repo.find_by_id(legacy.id)
                loaded.stage = "legacy updated"
                await repo.update(loaded)
                assert loaded.revision is None
                assert await session.get(JobSourceRecord, loaded.id) is None
                assert (
                    await session.scalar(
                        select(AssetSourceRelationRecord).where(
                            AssetSourceRelationRecord.resource_id == loaded.id
                        )
                    )
                    is None
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_stale_concurrent_identity_and_provenance_rejected(database):
    async def run():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            job, _ = await candidate(sessions)
            async with sessions.begin() as session:
                await SqlAlchemyJobRepository(session).add(job)

            async def mutate(value):
                async with sessions.begin() as session:
                    return await SqlAlchemyJobRepository(session).update(replace(job, stage=value))

            results = await asyncio.gather(mutate("one"), mutate("two"), return_exceptions=True)
            assert sum(isinstance(result, JobOwnershipError) for result in results) == 1
            stale = next(result for result in results if isinstance(result, JobOwnershipError))
            assert stale.code == "job_revision_conflict"
            async with sessions() as session:
                repo = SqlAlchemyJobRepository(session)
                current = await repo.find_by_id(job.id)
                for changes in [
                    {"user_id": uuid4()},
                    {"workspace_id": uuid4()},
                    {"asset_version_id": uuid4()},
                    {"type": JobType.RAG_INGESTION},
                    {"idempotency_key": "changed"},
                ]:
                    with pytest.raises(JobOwnershipError, match="job_identity_mismatch"):
                        await repo.update(replace(current, **changes))
            async with sessions.begin() as session:
                await session.execute(
                    update(AssetSourceRelationRecord)
                    .where(AssetSourceRelationRecord.resource_id == job.id)
                    .values(resource_revision=99)
                )
            async with sessions.begin() as session:
                repo = SqlAlchemyJobRepository(session)
                current = await repo.find_by_id(job.id)
                with pytest.raises(JobOwnershipError, match="job_relation_mismatch"):
                    await repo.update(current)
                assert current.revision == 2
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_owner_blocks_job_source_and_parent_cascade_deletion(database):
    async def run():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            job, document_id = await candidate(sessions)
            async with sessions.begin() as session:
                await SqlAlchemyJobRepository(session).add(job)
            # Even absent generic provenance, the stable source owner is a retention pin.
            async with sessions.begin() as session:
                await session.execute(
                    delete(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.resource_id == job.id
                    )
                )
            for model, identity in [
                (JobRecord, job.id),
                (AssetVersionRecord, job.asset_version_id),
                (DocumentRecord, document_id),
                (UserRecord, job.user_id),
                (WorkspaceRecord, job.workspace_id),
            ]:
                with pytest.raises(IntegrityError):
                    async with sessions.begin() as session:
                        await session.execute(delete(model).where(model.id == identity))
            with pytest.raises(IntegrityError, match="fk_job_source_job"):
                async with sessions.begin() as session:
                    await session.execute(
                        update(JobSourceRecord)
                        .where(JobSourceRecord.job_id == job.id)
                        .values(workspace_id=uuid4())
                    )
            with pytest.raises(IntegrityError, match="ck_jobs_revision"):
                async with sessions.begin() as session:
                    await session.execute(
                        update(JobRecord).where(JobRecord.id == job.id).values(revision=0)
                    )
            async with sessions() as session:
                with pytest.raises(JobOwnershipError, match="job_source_mismatch"):
                    await SqlAlchemyJobRepository(session).add(
                        replace(job, id=uuid4(), workspace_id=uuid4())
                    )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_additional_kind_relation_cannot_be_ignored_during_update(database):
    async def run():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            job, document_id = await candidate(sessions)
            async with sessions.begin() as session:
                await SqlAlchemyJobRepository(session).add(job)
                session.add(
                    AssetSourceRelationRecord(
                        workspace_id=job.workspace_id,
                        document_id=document_id,
                        asset_version_id=job.asset_version_id,
                        participant="platform_jobs",
                        kind="unexpected",
                        resource_id=job.id,
                        resource_revision=1,
                        relation_kind="derived_artifact",
                    )
                )
            async with sessions.begin() as session:
                with pytest.raises(JobOwnershipError, match="job_relation_mismatch"):
                    await SqlAlchemyJobRepository(session).update(job)
                assert job.revision == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_migration_preserves_legacy_rows_without_adopting_sources(database):
    async def create_legacy():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            job, _ = await candidate(sessions)
            async with sessions.begin() as session:
                session.add(
                    JobRecord(
                        id=job.id,
                        user_id=job.user_id,
                        workspace_id=job.workspace_id,
                        asset_version_id=job.asset_version_id,
                        type=job.type,
                        idempotency_key=job.idempotency_key,
                        status=job.status,
                        stage=job.stage,
                        attempt=0,
                        revision=None,
                    )
                )
            return job.id
        finally:
            await engine.dispose()

    job_id = asyncio.run(create_legacy())
    command.downgrade(database.config, "0047_http_upload_intake")
    command.upgrade(database.config, "head")

    async def verify_legacy():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as session:
                row = await session.get(JobRecord, job_id)
                assert row is not None and row.revision is None
                assert await session.get(JobSourceRecord, job_id) is None
                assert not list(
                    await session.scalars(
                        select(AssetSourceRelationRecord).where(
                            AssetSourceRelationRecord.resource_id == job_id
                        )
                    )
                )
        finally:
            await engine.dispose()

    asyncio.run(verify_legacy())
