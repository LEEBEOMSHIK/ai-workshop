import asyncio
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.platform.assets.domain import Document
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.temporary_contracts import (
    TemporaryBinding,
    TemporaryClaim,
    TemporaryContext,
    TemporaryOwnershipError,
)
from ai_workshop.platform.assets.temporary_inventory import TemporaryWorkspaceInventory
from ai_workshop.platform.assets.temporary_models import TemporaryWorkspaceRecord
from ai_workshop.platform.assets.temporary_repository import TemporaryJournal
from ai_workshop.platform.assets.trash_models import (
    AssetRetentionPolicyRecord,
    AssetTrashBatchRecord,
)
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from alembic import command
from tests.integration.platform.assets.original_upload_support import (
    require_explicit_original_test_database,
)
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
        command.downgrade(db.config, "0045_original_upload_ownership")
        command.upgrade(db.config, "head")
        yield db


async def seed(sessions):
    user, workspace, document, version, job = [uuid4() for _ in range(5)]
    async with sessions.begin() as session:
        session.add(
            UserRecord(
                id=user,
                display_name="Synthetic",
                email=f"{user}@example.test",
                normalized_email=f"{user}@example.test",
                password_hash="synthetic",
                role="member",
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            WorkspaceRecord(id=workspace, name="Synthetic", kind="company", created_by=user)
        )
        await session.flush()
        doc = Document(document, workspace, None, "synthetic.txt")
        doc.new_version(
            object_key=f"synthetic/{version}",
            sha256="a" * 64,
            media_type="text/plain",
            size=5,
            version_id=version,
        )
        await SqlAlchemyAssetRepository(session).save(doc)
        await session.flush()
        session.add(
            JobRecord(
                id=job,
                user_id=user,
                workspace_id=workspace,
                asset_version_id=version,
                type="rag_ingestion",
                idempotency_key=str(job),
                status="running",
                stage="parsing",
                attempt=1,
            )
        )
    return TemporaryContext(SourceIdentity(workspace, document, version), job)


class Store:
    def __init__(self, binding):
        self.binding = binding
        self.exists = False

    def observe(self, claim: TemporaryClaim) -> bool:
        return self.exists


def test_commit_cas_provenance_source_gate_and_restrict(database):
    async def run():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            context = await seed(sessions)
            binding = TemporaryBinding("temporary", uuid4())
            journal = TemporaryJournal(sessions)
            claim = await journal.reserve(context, "parsing", binding, coverage="bounded")
            async with sessions() as request:
                await request.rollback()
            async with sessions() as session:
                row = await session.get(TemporaryWorkspaceRecord, claim.id)
                assert row.state == "open" and row.revision == 1
            for field in [
                dict(generation=2),
                dict(binding=TemporaryBinding("other", uuid4())),
                dict(context=replace(context, job_id=None)),
                dict(purpose="pdf_preview"),
            ]:
                with pytest.raises(TemporaryOwnershipError, match="invalid_claim"):
                    await journal.transition(replace(claim, **field), expected_state="open")
            await journal.transition(claim, expected_state="open")
            with pytest.raises(TemporaryOwnershipError, match="state_conflict"):
                await journal.transition(claim, expected_state="open")
            async with sessions() as session:
                relation = await session.scalar(
                    select(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.resource_id == claim.id
                    )
                )
                assert relation.resource_revision == 2
            for model, key in [
                (JobRecord, context.job_id),
                (AssetVersionRecord, context.source.asset_version_id),
                (DocumentRecord, context.source.document_id),
            ]:
                with pytest.raises(IntegrityError):
                    async with sessions.begin() as session:
                        await session.execute(delete(model).where(model.id == key))
            other = await seed(sessions)
            with pytest.raises(TemporaryOwnershipError, match="job_mismatch"):
                await journal.reserve(
                    replace(context, job_id=other.job_id), "parsing", binding, coverage="bounded"
                )
            with pytest.raises(TemporaryOwnershipError, match="source_mismatch"):
                await journal.reserve(
                    TemporaryContext(replace(context.source, document_id=other.source.document_id)),
                    "pdf_preview",
                    binding,
                    coverage="bounded",
                )
            # Document-only gate locks cannot add job/version locks afterwards.
            async with sessions.begin() as gate:
                await gate.get(DocumentRecord, context.source.document_id, with_for_update=True)
                pending = asyncio.create_task(
                    journal.reserve(context, "parsing", binding, coverage="bounded")
                )
                await asyncio.sleep(0.05)
                assert not pending.done()
                await gate.execute(
                    update(DocumentRecord)
                    .where(DocumentRecord.id == context.source.document_id)
                    .values(lifecycle_generation=2)
                )
            fresh = await asyncio.wait_for(pending, 5)
            assert fresh.generation == 2
            worker_locked = asyncio.Event()

            async def worker():
                async with sessions.begin() as session:
                    await session.get(JobRecord, context.job_id, with_for_update=True)
                    await session.get(
                        AssetVersionRecord, context.source.asset_version_id, with_for_update=True
                    )
                    worker_locked.set()
                    await session.get(
                        DocumentRecord, context.source.document_id, with_for_update=True
                    )

            async with sessions.begin() as gate:
                await gate.get(DocumentRecord, context.source.document_id, with_for_update=True)
                worker_task = asyncio.create_task(worker())
                await asyncio.wait_for(worker_locked.wait(), 5)
                reservation_task = asyncio.create_task(
                    journal.reserve(context, "parsing", binding, coverage="bounded")
                )
                await asyncio.sleep(0.05)
                assert not worker_task.done() and not reservation_task.done()
            await asyncio.wait_for(asyncio.gather(worker_task, reservation_task), 5)
            policy, batch, actor = uuid4(), uuid4(), uuid4()
            now = datetime.now(UTC)
            async with sessions.begin() as gate:
                gate.add(
                    AssetRetentionPolicyRecord(
                        id=policy,
                        workspace_id=context.source.workspace_id,
                        version=1,
                        days=1,
                        created_by=actor,
                    )
                )
                await gate.flush()
                gate.add(
                    AssetTrashBatchRecord(
                        id=batch,
                        workspace_id=context.source.workspace_id,
                        actor_id=actor,
                        policy_version_id=policy,
                        trashed_at=now,
                        purge_after=now + timedelta(days=1),
                    )
                )
                await gate.flush()
                await gate.get(DocumentRecord, context.source.document_id, with_for_update=True)
                rejected = asyncio.create_task(
                    journal.reserve(context, "parsing", binding, coverage="bounded")
                )
                await asyncio.sleep(0.05)
                assert not rejected.done()
                await gate.execute(
                    update(DocumentRecord)
                    .where(DocumentRecord.id == context.source.document_id)
                    .values(
                        lifecycle="trashed",
                        lifecycle_generation=3,
                        trash_batch_id=batch,
                        trashed_at=now,
                        purge_after=now + timedelta(days=1),
                    )
                )
            with pytest.raises(TemporaryOwnershipError, match="writes_blocked"):
                await asyncio.wait_for(rejected, 5)
            # Reservation holds job then version while gate holds document; no cycle.
            await journal.transition(claim, expected_state="closed")
            await journal.transition(claim, expected_state="cleaning")
            # A failed provenance CAS rolls the row state back as well.
            async with sessions.begin() as session:
                await session.execute(
                    delete(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.resource_id == fresh.id
                    )
                )
            with pytest.raises(Exception, match="asset_provenance_current_conflict"):
                await journal.transition(fresh, expected_state="open")
            async with sessions() as session:
                row = await session.get(TemporaryWorkspaceRecord, fresh.id)
                assert row.state == "open" and row.revision == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_inventory_retains_historical_runtime_and_changed_blockers(database):
    async def run():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            context = await seed(sessions)
            binding = TemporaryBinding("temporary", uuid4())
            store = Store(binding)
            inventory = TemporaryWorkspaceInventory(sessions, store)
            empty = await inventory.collect(context.source.workspace_id, context.source.document_id)
            assert not empty.complete and "legacy_untracked" in empty.blockers
            journal = TemporaryJournal(sessions)
            claim = await journal.reserve(
                context, "parsing", binding, coverage="runtime_unverified"
            )
            store.exists = True
            opened = await inventory.collect(
                context.source.workspace_id, context.source.document_id
            )
            assert {"runtime_unverified", "temporary_present", "writer_unconfirmed"} <= set(
                opened.blockers
            )
            for state in ["open", "closed", "cleaning"]:
                await journal.transition(claim, expected_state=state)
            store.exists = False
            cleaned = await inventory.collect(
                context.source.workspace_id, context.source.document_id
            )
            assert not cleaned.complete and "runtime_unverified" in cleaned.blockers
            assert "writer_unconfirmed" not in cleaned.blockers
            assert cleaned.resources[0].revision == 4
            original_snapshot = inventory._snapshot
            calls = 0

            async def changed_snapshot(workspace, document):
                nonlocal calls
                calls += 1
                if calls == 2:
                    await journal.reserve(context, "pdf_preview", binding, coverage="bounded")
                return await original_snapshot(workspace, document)

            inventory._snapshot = changed_snapshot
            changed = await inventory.collect(
                context.source.workspace_id, context.source.document_id
            )
            assert "inventory_changed" in changed.blockers
        finally:
            await engine.dispose()

    asyncio.run(run())
