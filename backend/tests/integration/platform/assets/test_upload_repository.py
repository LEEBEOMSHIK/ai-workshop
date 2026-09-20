import asyncio
from collections.abc import Iterator
from contextlib import asynccontextmanager
from dataclasses import replace
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
from ai_workshop.platform.assets.storage import StoredObject
from ai_workshop.platform.assets.upload_contracts import (
    OriginalFileObservation,
    OriginalStoreBinding,
    UploadClaim,
    UploadOwnershipError,
)
from ai_workshop.platform.assets.upload_models import OriginalResourceRecord, UploadAttemptRecord
from ai_workshop.platform.assets.upload_repository import UploadJournal
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.shared.errors import AppError
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
        yield db


def test_journal_atomicity_permissions_and_restrict(database: IsolatedPublishingDatabase) -> None:
    async def run() -> None:
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        user, workspace = uuid4(), uuid4()
        claim = UploadClaim(
            uuid4(),
            SourceIdentity(workspace, uuid4(), uuid4()),
            user,
            None,
            True,
            OriginalStoreBinding("originals", uuid4()),
            ".txt",
        )
        stored = StoredObject(claim.canonical_key, 5, "a" * 64)
        journal = UploadJournal(sessions)
        try:
            async with sessions.begin() as session:
                session.add(
                    UserRecord(
                        id=user,
                        display_name="Synthetic owner",
                        email=f"{user}@example.test",
                        normalized_email=f"{user}@example.test",
                        password_hash="synthetic",
                        role="member",
                        is_active=True,
                    )
                )
                await session.flush()
                session.add(
                    WorkspaceRecord(
                        id=workspace, name="Synthetic originals", kind="company", created_by=user
                    )
                )
                await session.flush()
                session.add(
                    WorkspaceMembershipRecord(
                        id=uuid4(), workspace_id=workspace, user_id=user, role="owner"
                    )
                )
            assert await journal.reserve(claim) == claim
            async with sessions() as request:
                await request.rollback()
            async with sessions() as independent:
                assert await independent.get(UploadAttemptRecord, claim.attempt_id)
                assert await independent.get(DocumentRecord, claim.source.document_id) is None
            await journal.published(claim, stored)
            with pytest.raises(UploadOwnershipError):
                await journal.published(claim, stored)
            async with sessions() as session:
                with pytest.raises(UploadOwnershipError, match="attachment_mismatch"):
                    await journal.attach(session, claim, stored)
                await journal.prepare_attachment(session, claim)
                await session.rollback()
                with pytest.raises(UploadOwnershipError, match="attachment_mismatch"):
                    await journal.attach(session, claim, stored)
            async with sessions() as session:
                assert await journal.prepare_attachment(session, claim) is None
                doc = Document(claim.source.document_id, workspace, None, "synthetic.txt")
                doc.new_version(
                    object_key=stored.key,
                    sha256=stored.sha256,
                    media_type="text/plain",
                    size=stored.size,
                    version_id=claim.source.asset_version_id,
                )
                await SqlAlchemyAssetRepository(session).save(doc)
                await journal.attach(session, claim, stored)
                await session.rollback()
            async with sessions() as session:
                attempt = await session.get(UploadAttemptRecord, claim.attempt_id)
                assert attempt is not None and attempt.state == "published"
                assert await session.get(OriginalResourceRecord, claim.attempt_id) is None
            async with sessions.begin() as session:
                await journal.prepare_attachment(session, claim)
                doc = Document(claim.source.document_id, workspace, None, "synthetic.txt")
                doc.new_version(
                    object_key=stored.key,
                    sha256=stored.sha256,
                    media_type="text/plain",
                    size=stored.size,
                    version_id=claim.source.asset_version_id,
                )
                await SqlAlchemyAssetRepository(session).save(doc)
                await journal.attach(session, claim, stored)
            async with sessions() as session:
                relation = await session.scalar(
                    select(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.resource_id == claim.attempt_id
                    )
                )
                assert relation is not None and relation.participant == "platform_originals"
            for model, key in [
                (UploadAttemptRecord, claim.attempt_id),
                (AssetVersionRecord, claim.source.asset_version_id),
                (DocumentRecord, claim.source.document_id),
            ]:
                with pytest.raises(IntegrityError):
                    async with sessions.begin() as session:
                        await session.execute(delete(model).where(model.id == key))
            with pytest.raises(UploadOwnershipError):
                await journal.abandoned(claim, expected_state="published")
            callbacks = []
            with pytest.raises(UploadOwnershipError):
                await journal.cleanup(
                    claim,
                    expected_state="published",
                    discard=lambda: callbacks.append("deleted"),
                    observe=lambda: OriginalFileObservation(None, False),
                )
            assert callbacks == []
            next_claim = replace(
                claim,
                attempt_id=uuid4(),
                new_document=False,
                source=replace(claim.source, asset_version_id=uuid4()),
            )
            reserved = await journal.reserve(next_claim)
            assert reserved.generation == 1
            for values in (
                {"canonical_key": "unregistered"},
                {"revision": 8},
                {"generation": None},
            ):
                with pytest.raises(IntegrityError):
                    async with sessions.begin() as session:
                        await session.execute(
                            update(UploadAttemptRecord)
                            .where(UploadAttemptRecord.id == reserved.attempt_id)
                            .values(**values)
                        )
            next_stored = StoredObject(reserved.canonical_key, 5, "b" * 64)
            outcomes = await asyncio.gather(
                journal.published(reserved, next_stored),
                journal.published(reserved, next_stored),
                return_exceptions=True,
            )
            assert sum(item is None for item in outcomes) == 1
            assert sum(isinstance(item, UploadOwnershipError) for item in outcomes) == 1
            async with sessions() as stale:
                cached = await stale.get(DocumentRecord, claim.source.document_id)
                assert cached is not None and cached.metadata_revision == 1
                async with sessions.begin() as session:
                    await session.execute(
                        update(DocumentRecord)
                        .where(DocumentRecord.id == claim.source.document_id)
                        .values(name="fresh-name.txt", metadata_revision=2)
                    )
                fresh = await journal.prepare_attachment(stale, reserved)
                assert fresh is not None and fresh.name == "fresh-name.txt"
                assert fresh.metadata_revision == 2 and len(fresh.versions) == 1
                await stale.rollback()
            failed_claim = await journal.reserve(
                replace(
                    next_claim,
                    attempt_id=uuid4(),
                    source=replace(next_claim.source, asset_version_id=uuid4()),
                )
            )
            await journal.published(
                failed_claim, StoredObject(failed_claim.canonical_key, 5, "c" * 64)
            )

            class LostCommitSessions:
                @asynccontextmanager
                async def begin(self):
                    async with sessions.begin() as current:
                        yield current
                    raise RuntimeError("commit_response_lost")

            uncertain = UploadJournal(LostCommitSessions())
            with pytest.raises(RuntimeError, match="commit_response_lost"):
                await uncertain.cleanup(
                    failed_claim,
                    expected_state="published",
                    discard=lambda: callbacks.append("deleted"),
                    observe=lambda: OriginalFileObservation(None, False),
                )
            assert callbacks == []
            async with sessions() as session:
                row = await session.get(UploadAttemptRecord, failed_claim.attempt_id)
                assert row is not None and (row.state, row.revision) == ("discarding", 3)
                with pytest.raises(UploadOwnershipError):
                    await journal.prepare_attachment(session, failed_claim)

            class FinalRollbackSessions:
                count = 0

                @asynccontextmanager
                async def begin(self):
                    self.count += 1
                    async with sessions.begin() as current:
                        yield current
                        if self.count == 2:
                            raise RuntimeError("terminal_commit_failed")

            terminal_claim = await journal.reserve(
                replace(
                    next_claim,
                    attempt_id=uuid4(),
                    source=replace(next_claim.source, asset_version_id=uuid4()),
                )
            )
            terminal_stored = StoredObject(terminal_claim.canonical_key, 5, "d" * 64)
            await journal.published(terminal_claim, terminal_stored)
            deleted = []
            with pytest.raises(RuntimeError, match="terminal_commit_failed"):
                await UploadJournal(FinalRollbackSessions()).cleanup(
                    terminal_claim,
                    expected_state="published",
                    discard=lambda: deleted.append(True),
                    observe=lambda: OriginalFileObservation(None, False),
                )
            assert deleted == [True]
            async with sessions() as session:
                row = await session.get(UploadAttemptRecord, terminal_claim.attempt_id)
                assert row is not None and (row.state, row.revision) == ("discarding", 3)
                with pytest.raises(UploadOwnershipError):
                    await journal.prepare_attachment(session, terminal_claim)
            with pytest.raises(UploadOwnershipError):
                await journal.published(terminal_claim, terminal_stored)

            open_claim = await journal.reserve(
                replace(
                    next_claim,
                    attempt_id=uuid4(),
                    source=replace(next_claim.source, asset_version_id=uuid4()),
                )
            )
            with pytest.raises(UploadOwnershipError):
                await journal.cleanup(
                    open_claim,
                    expected_state="open",
                    discard=lambda: None,
                    observe=lambda: OriginalFileObservation(None, True),
                )
            await journal.cleanup(
                open_claim,
                expected_state="open",
                discard=lambda: None,
                observe=lambda: OriginalFileObservation(None, False),
            )
            async with sessions() as session:
                row = await session.get(UploadAttemptRecord, open_claim.attempt_id)
                assert row is not None and (row.state, row.revision) == ("abandoned", 2)

            async with sessions.begin() as session:
                await session.execute(
                    update(DocumentRecord)
                    .where(DocumentRecord.id == claim.source.document_id)
                    .values(lifecycle_generation=2)
                )
            with pytest.raises(UploadOwnershipError):
                async with sessions() as session:
                    await journal.prepare_attachment(session, reserved)
            async with sessions.begin() as session:
                await session.execute(
                    delete(WorkspaceMembershipRecord).where(
                        WorkspaceMembershipRecord.user_id == user
                    )
                )
            with pytest.raises(AppError):
                await journal.reserve(replace(claim, attempt_id=uuid4()))
            await journal.cleanup(
                reserved,
                expected_state="published",
                discard=lambda: callbacks.append("deleted"),
                observe=lambda: OriginalFileObservation(None, False),
            )
            assert callbacks == ["deleted"]
            async with sessions() as session:
                record = await session.get(UploadAttemptRecord, reserved.attempt_id)
                assert record is not None and (record.state, record.revision) == ("abandoned", 4)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_migration_roundtrip(database: IsolatedPublishingDatabase) -> None:
    command.downgrade(database.config, "0044_rag_index_write_fences")
    command.upgrade(database.config, "head")
