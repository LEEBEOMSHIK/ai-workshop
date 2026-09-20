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
from ai_workshop.platform.assets.intake_inventory import UploadIntakeInventory
from ai_workshop.platform.assets.intake_models import UploadIntakeRecord
from ai_workshop.platform.assets.intake_repository import UploadIntakeJournal
from ai_workshop.platform.assets.models import DocumentRecord
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.storage import StoredObject
from ai_workshop.platform.assets.temporary_contracts import TemporaryBinding
from ai_workshop.platform.assets.upload_contracts import (
    OriginalStoreBinding,
    UploadClaim,
    UploadOwnershipError,
)
from ai_workshop.platform.assets.upload_models import UploadAttemptRecord
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
        command.downgrade(db.config, "0046_document_temporary")
        command.upgrade(db.config, "head")
        yield db


async def seed(sessions):
    user, workspace = uuid4(), uuid4()
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
        session.add(WorkspaceMembershipRecord(workspace_id=workspace, user_id=user, role="owner"))
    return user, workspace


def original(intake):
    return UploadClaim(
        uuid4(),
        intake.source,
        intake.user_id,
        None,
        intake.new_document,
        OriginalStoreBinding("originals", uuid4()),
        ".txt",
        intake.generation,
    )


async def attach(sessions, journal, intake, claim, *, rollback=False):
    uploads = UploadJournal(sessions)
    stored = StoredObject(claim.canonical_key, 5, "a" * 64)
    async with sessions() as session:
        await journal.prepare_attachment(session, intake, claim)
        await uploads.prepare_attachment(session, claim)
        doc = Document(claim.source.document_id, claim.source.workspace_id, None, "synthetic.txt")
        doc.new_version(
            object_key=stored.key,
            sha256=stored.sha256,
            media_type="text/plain",
            size=stored.size,
            version_id=claim.source.asset_version_id,
        )
        await SqlAlchemyAssetRepository(session).save(doc)
        await uploads.attach(session, claim, stored)
        attached = await journal.attach(session, intake, claim)
        if rollback:
            await session.rollback()
        else:
            await session.commit()
        return attached


def test_atomic_link_attachment_cas_and_source_pins(database):
    async def run():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            journal = UploadIntakeJournal(sessions)
            intake = await journal.reserve(
                user_id=user,
                workspace_id=workspace,
                document_id=None,
                binding=TemporaryBinding("temporary", uuid4()),
            )
            claim = original(intake)
            linked = await journal.reserve_original(intake, claim)
            assert linked.source == claim.source and linked.revision == 2
            with pytest.raises(UploadOwnershipError):
                await journal.reserve_original(intake, original(intake))
            async with sessions() as session:
                assert len((await session.scalars(select(UploadAttemptRecord))).all()) == 1
                assert await session.get(DocumentRecord, intake.source.document_id) is None
            await UploadJournal(sessions).published(
                claim, StoredObject(claim.canonical_key, 5, "a" * 64)
            )
            await attach(sessions, journal, linked, claim, rollback=True)
            async with sessions() as session:
                row = await session.get(UploadIntakeRecord, intake.id)
                assert not row.attached and row.revision == 2
            attached = await attach(sessions, journal, linked, claim)
            assert attached.attached and attached.revision == 3
            with pytest.raises(UploadOwnershipError):
                await journal.transition(linked, expected_state="open")
            current = attached
            for state in ["open", "closed", "cleaning"]:
                current = await journal.transition(current, expected_state=state)
            assert current.state == "cleaned" and current.revision == 6
            async with sessions() as session:
                relation = await session.scalar(
                    select(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.participant == "platform_http_uploads"
                    )
                )
                assert relation.resource_revision == 6
            with pytest.raises(IntegrityError):
                async with sessions.begin() as session:
                    await session.execute(
                        delete(DocumentRecord).where(DocumentRecord.id == intake.source.document_id)
                    )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_parallel_replay_wrong_identity_and_capability_rejected(database):
    async def run():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            journal = UploadIntakeJournal(sessions)
            intake = await journal.reserve(
                user_id=user,
                workspace_id=workspace,
                document_id=None,
                binding=TemporaryBinding("temporary", uuid4()),
            )
            for changed in [
                replace(original(intake), user_id=uuid4()),
                replace(original(intake), source=replace(intake.source, asset_version_id=uuid4())),
            ]:
                with pytest.raises(UploadOwnershipError):
                    await journal.reserve_original(intake, changed)
            first, second = original(intake), original(intake)
            results = await asyncio.gather(
                journal.reserve_original(intake, first),
                journal.reserve_original(intake, second),
                return_exceptions=True,
            )
            assert sum(not isinstance(r, BaseException) for r in results) == 1
            winner = first if not isinstance(results[0], BaseException) else second
            linked = next(r for r in results if not isinstance(r, BaseException))
            await UploadJournal(sessions).published(
                winner, StoredObject(winner.canonical_key, 5, "a" * 64)
            )
            async with sessions() as session:
                await journal.prepare_attachment(session, linked, winner)
                await session.rollback()
                with pytest.raises(UploadOwnershipError, match="attachment_mismatch"):
                    await journal.attach(session, linked, winner)
            async with sessions() as session:
                await journal.prepare_attachment(session, linked, winner)
                async with session.begin_nested():
                    with pytest.raises(UploadOwnershipError, match="attachment_mismatch"):
                        await journal.attach(session, linked, winner)
            with pytest.raises(AppError):
                await journal.reserve(
                    user_id=uuid4(),
                    workspace_id=workspace,
                    document_id=None,
                    binding=intake.binding,
                )
            async with sessions() as session:
                assert len((await session.scalars(select(UploadIntakeRecord))).all()) == 1
                assert len((await session.scalars(select(UploadAttemptRecord))).all()) == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_existing_document_pin_named_link_and_attachment_constraints(database):
    async def run():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            document_id = uuid4()
            async with sessions.begin() as session:
                await SqlAlchemyAssetRepository(session).save(
                    Document(document_id, workspace, None, "synthetic.txt")
                )
            journal = UploadIntakeJournal(sessions)
            intake = await journal.reserve(
                user_id=user,
                workspace_id=None,
                document_id=document_id,
                binding=TemporaryBinding("temporary", uuid4()),
            )
            assert intake.generation == 1 and not intake.new_document
            with pytest.raises(IntegrityError, match="fk_intake_existing_document"):
                async with sessions.begin() as session:
                    await session.execute(
                        delete(DocumentRecord).where(DocumentRecord.id == document_id)
                    )
            candidate = original(intake)
            linked = await journal.reserve_original(intake, candidate)
            other = await journal.reserve(
                user_id=user, workspace_id=workspace, document_id=None, binding=intake.binding
            )
            with pytest.raises(IntegrityError, match="fk_intake_original_source"):
                async with sessions.begin() as session:
                    row = await session.get(UploadIntakeRecord, linked.id)
                    row.asset_version_id = uuid4()
            with pytest.raises(IntegrityError, match="uq_intake_original_attempt"):
                async with sessions.begin() as session:
                    row = await session.get(UploadIntakeRecord, other.id)
                    row.new_document = False
                    row.document_id = document_id
                    row.existing_document_id = document_id
                    row.generation = 1
                    row.asset_version_id = intake.source.asset_version_id
                    row.original_attempt_id = candidate.attempt_id
                    row.revision = 2
            with pytest.raises(IntegrityError, match="ck_intake_attachment"):
                async with sessions.begin() as session:
                    row = await session.get(UploadIntakeRecord, linked.id)
                    row.attached = True
                    row.revision = 3
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_inventory_unattached_authorization_freshness_and_opaque_output(database):
    async def run():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            journal = UploadIntakeJournal(sessions)
            binding = TemporaryBinding("temporary", uuid4())
            intake = await journal.reserve(
                user_id=user, workspace_id=workspace, document_id=None, binding=binding
            )

            class Store:
                def __init__(self):
                    self.binding = binding

                def observe(self, claim):
                    return False

            inventory = UploadIntakeInventory(sessions, Store())
            listed = await inventory.list_unattached(user, workspace)
            assert listed.items[0].intake_id == intake.id
            assert "writer_unconfirmed" in listed.blockers
            assert not hasattr(listed.items[0], "source")
            assert not hasattr(listed.items[0], "binding")
            with pytest.raises(AppError):
                await inventory.list_unattached(uuid4(), workspace)
            current = intake
            for state in ["open", "closed", "cleaning"]:
                current = await journal.transition(current, expected_state=state)
            result = await inventory.collect(workspace, intake.source.document_id)
            assert not result.complete and result.resources[0].revision == 4
            assert result.blockers == ("legacy_untracked",)

            class ChangingInventory(UploadIntakeInventory):
                async def _snapshot(self, *args, **kwargs):
                    snapshot = await super()._snapshot(*args, **kwargs)
                    if not getattr(self, "changed", False):
                        self.changed = True
                        await journal.reserve(
                            user_id=user, workspace_id=workspace, document_id=None, binding=binding
                        )
                    return snapshot

            changed = await ChangingInventory(sessions, Store()).list_unattached(user, workspace)
            assert "inventory_changed" in changed.blockers
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_unknown_commit_keeps_durable_ownership_and_rejects_old_snapshot(database):
    async def run():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        class UnknownCommit:
            @asynccontextmanager
            async def begin(self):
                async with sessions.begin() as session:
                    yield session
                raise RuntimeError("synthetic_commit_ack_lost")

        try:
            user, workspace = await seed(sessions)
            journal = UploadIntakeJournal(sessions)
            binding = TemporaryBinding("temporary", uuid4())
            uncertain = UploadIntakeJournal(UnknownCommit())
            with pytest.raises(RuntimeError, match="synthetic_commit_ack_lost"):
                await uncertain.reserve(
                    user_id=user, workspace_id=workspace, document_id=None, binding=binding
                )
            async with sessions() as session:
                rows = (await session.scalars(select(UploadIntakeRecord))).all()
                assert len(rows) == 1 and rows[0].revision == 1
            intake = await journal.reserve(
                user_id=user, workspace_id=workspace, document_id=None, binding=binding
            )
            claim = original(intake)
            with pytest.raises(RuntimeError, match="synthetic_commit_ack_lost"):
                await uncertain.reserve_original(intake, claim)
            async with sessions() as session:
                row = await session.get(UploadIntakeRecord, intake.id)
                assert row.original_attempt_id == claim.attempt_id and row.revision == 2
                assert await session.get(UploadAttemptRecord, claim.attempt_id) is not None
            with pytest.raises(UploadOwnershipError):
                await journal.transition(intake, expected_state="open")
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_current_authority_and_generation_rechecked_before_original_link(database):
    async def run():
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            document_id = uuid4()
            async with sessions.begin() as session:
                await SqlAlchemyAssetRepository(session).save(
                    Document(document_id, workspace, None, "synthetic.txt")
                )
            journal = UploadIntakeJournal(sessions)
            intake = await journal.reserve(
                user_id=user,
                workspace_id=None,
                document_id=document_id,
                binding=TemporaryBinding("temporary", uuid4()),
            )
            async with sessions.begin() as session:
                await session.execute(
                    update(DocumentRecord)
                    .where(DocumentRecord.id == document_id)
                    .values(lifecycle_generation=2)
                )
            with pytest.raises(UploadOwnershipError, match="generation_mismatch"):
                await journal.reserve_original(intake, original(intake))
            newer = await journal.reserve(
                user_id=user, workspace_id=None, document_id=document_id, binding=intake.binding
            )
            async with sessions.begin() as session:
                await session.execute(
                    delete(WorkspaceMembershipRecord).where(
                        WorkspaceMembershipRecord.workspace_id == workspace,
                        WorkspaceMembershipRecord.user_id == user,
                    )
                )
            with pytest.raises(AppError):
                await journal.reserve_original(newer, original(newer))
            async with sessions() as session:
                assert not (await session.scalars(select(UploadAttemptRecord))).all()
        finally:
            await engine.dispose()

    asyncio.run(run())
