import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.platform.assets.dispatch import SqlAlchemyAssetVerificationDispatchRepository
from ai_workshop.platform.assets.domain import Document
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.platform.jobs.inventory import JobMetadataInventory
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.platform.assets.original_upload_support import (
    require_explicit_original_test_database,
)
from tests.integration.platform.assets.test_intake_repository import seed
from tests.integration.publishing_support import isolated_publishing_database


@pytest.fixture(autouse=True)
def ensure_legacy_document_processing_profile():
    pass


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    require_explicit_original_test_database()
    monkeypatch = pytest.MonkeyPatch()
    try:
        with isolated_publishing_database(monkeypatch) as database:
            command.upgrade(database.config, "head")
            yield database.database_url
    finally:
        monkeypatch.undo()


async def create_source(sessions, *, versions=1):
    user, workspace = await seed(sessions)
    document = Document.create(workspace_id=workspace, folder_id=None, name="synthetic.txt")
    jobs = []
    async with sessions.begin() as session:
        for number in range(versions):
            version = document.new_version(
                object_key=f"synthetic/{uuid4()}.txt",
                sha256="a" * 64,
                media_type="text/plain",
                size=5,
            )
            if number == 0:
                await SqlAlchemyAssetRepository(session).save(document)
            else:
                await SqlAlchemyAssetRepository(session).save_version(document, version)
            job = Job.create(
                user_id=user,
                workspace_id=workspace,
                asset_version_id=version.id,
                type=JobType.VERIFY_ASSET,
                idempotency_key=str(uuid4()),
            )
            jobs.append(await SqlAlchemyJobRepository(session).add(job))
    return user, document, jobs


async def revision(sessions, job_id):
    async with sessions() as session:
        job = await session.get(JobRecord, job_id)
        relation = await session.scalar(
            select(AssetSourceRelationRecord).where(
                AssetSourceRelationRecord.participant == "platform_jobs",
                AssetSourceRelationRecord.resource_id == job_id,
            )
        )
        assert job.revision == relation.resource_revision
        return job.revision


def test_dispatch_claim_failure_and_stale_claim_keep_current_relation(database_url):
    async def run():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            _, _, jobs = await create_source(sessions)
            repository = SqlAlchemyAssetVerificationDispatchRepository(sessions)
            now = datetime.now(UTC)
            claims = await repository.claim_recoverable(
                now=now, stale_before=now - timedelta(minutes=2), limit=1, job_id=jobs[0].id
            )
            assert len(claims) == 1
            assert await revision(sessions, jobs[0].id) == 2
            await repository.mark_send_failed(claims[0], error="private synthetic connection")
            assert await revision(sessions, jobs[0].id) == 3
            await repository.mark_send_failed(claims[0], error="must be stale")
            assert await revision(sessions, jobs[0].id) == 3
            async with sessions() as session:
                row = await session.get(JobRecord, jobs[0].id)
                assert "private synthetic" not in row.error_message
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_inventory_all_versions_auth_and_freshness(database_url):
    async def run():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, document, jobs = await create_source(sessions, versions=2)
            inventory = JobMetadataInventory(sessions)
            result = await inventory.collect(document.workspace_id, document.id, user_id=user)
            assert {resource.resource_id for resource in result.resources} == {
                job.id for job in jobs
            }
            assert result.blockers == ("writer_unconfirmed",)
            assert not result.complete
            with pytest.raises(AppError):
                await inventory.collect(document.workspace_id, document.id, user_id=uuid4())

            class ChangingInventory(JobMetadataInventory):
                calls = 0

                async def _snapshot(self, *args, **kwargs):
                    current = await super()._snapshot(*args, **kwargs)
                    self.calls += 1
                    if self.calls == 1:
                        async with sessions.begin() as session:
                            repo = SqlAlchemyJobRepository(session)
                            job = await repo.find_by_id_for_update(jobs[0].id)
                            job.start(stage="synthetic")
                            await repo.update(job)
                    return current

            changed = await ChangingInventory(sessions).collect(document.workspace_id, document.id)
            assert "inventory_changed" in changed.blockers
            async with sessions.begin() as session:
                await session.execute(
                    update(AssetSourceRelationRecord)
                    .where(
                        AssetSourceRelationRecord.participant == "platform_jobs",
                        AssetSourceRelationRecord.resource_id == jobs[0].id,
                    )
                    .values(resource_revision=99)
                )
            mismatched = await inventory.collect(document.workspace_id, document.id)
            assert "relation_mismatch" in mismatched.blockers
        finally:
            await engine.dispose()

    asyncio.run(run())
