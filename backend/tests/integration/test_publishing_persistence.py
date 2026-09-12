from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_workshop.config import PublishingLimits
from ai_workshop.platform.publishing.delivery import LocalPublicationDelivery
from ai_workshop.platform.publishing.domain import PublicationAction
from ai_workshop.platform.publishing.models import (
    PublishingCommandRow,
    PublishingRevisionRow,
)
from ai_workshop.platform.publishing.package import (
    StudyContent,
    StudySnapshot,
    canonical_bytes,
    snapshot_digest,
)
from ai_workshop.platform.publishing.public_store import (
    PublicationReceipt,
    SqlitePublicStudyReader,
    SqlitePublicStudyWriter,
)
from ai_workshop.platform.publishing.repository import (
    PublishingStudy,
    SqlAlchemyPublishingRepository,
)
from ai_workshop.platform.publishing.service import PublishingService
from ai_workshop.shared.errors import AppError
from alembic import command as alembic_command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)

pytestmark = pytest.mark.integration


class FailFirstAcknowledgeRepository(SqlAlchemyPublishingRepository):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(sessions)
        self.fail_next_acknowledgement = True

    async def acknowledge(self, receipt: PublicationReceipt) -> PublishingStudy:
        if self.fail_next_acknowledgement:
            self.fail_next_acknowledgement = False
            raise AppError(
                "publishing_private_store_unavailable",
                "The publishing store is unavailable.",
                503,
            )
        return await super().acknowledge(receipt)


def content(slug: str = "example-study", *, title: str = "Example") -> StudyContent:
    return StudyContent(
        slug=slug,
        title=title,
        summary="Public summary.",
        topic_keys=("rag",),
        body="Public body.",
        verification="Fixture verification.",
        limitations="Synthetic data only.",
    )


@pytest.fixture
def migrated_publishing_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[IsolatedPublishingDatabase]:
    with isolated_publishing_database(monkeypatch) as database:
        alembic_command.upgrade(database.config, "0025_publishing")
        yield database


@pytest.mark.asyncio
async def test_revision_lock_outbox_replay_and_acknowledgement_are_atomic(
    migrated_publishing_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_publishing_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemyPublishingRepository(sessions)
    try:
        created = await repository.create(content())
        assert created.snapshot.revision == 1

        updates = await asyncio.gather(
            repository.update(
                "example-study",
                expected_revision=1,
                content=content(title="First edit"),
            ),
            repository.update(
                "example-study",
                expected_revision=1,
                content=content(title="Second edit"),
            ),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, Exception) for item in updates) == 1
        conflict = next(item for item in updates if isinstance(item, AppError))
        assert (conflict.code, conflict.status_code) == (
            "publishing_revision_conflict",
            409,
        )
        current = await repository.get("example-study")
        assert current is not None
        assert current.snapshot.revision == 2

        prepared = await repository.prepare_command(
            "example-study",
            action=PublicationAction.PUBLISH,
            expected_revision=2,
            expected_digest=current.digest,
            request_id="publish-two",
        )
        assert prepared.should_deliver is True
        async with sessions() as session:
            command_count = await session.scalar(
                select(func.count()).select_from(PublishingCommandRow)
            )
            revision_count = await session.scalar(
                select(func.count()).select_from(PublishingRevisionRow)
            )
        assert command_count == 1
        assert revision_count == 2

        pending = await repository.record_delivery_failure(
            "publish-two", error_code="publishing_store_unavailable"
        )
        assert pending.delivery_pending is True
        assert pending.delivery_error_code == "publishing_store_unavailable"

        replay = await repository.prepare_command(
            "example-study",
            action=PublicationAction.PUBLISH,
            expected_revision=2,
            expected_digest=current.digest,
            request_id="publish-two",
        )
        assert replay.command == prepared.command
        assert replay.should_deliver is True

        acknowledged = await repository.acknowledge(
            PublicationReceipt(
                slug="example-study",
                sequence=1,
                request_id="publish-two",
                action=PublicationAction.PUBLISH,
            )
        )
        assert acknowledged.applied_sequence == 1
        assert acknowledged.applied_revision == 2
        assert acknowledged.delivery_pending is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_global_request_conflict_and_superseded_replay_cannot_regress_state(
    migrated_publishing_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_publishing_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemyPublishingRepository(sessions)
    try:
        first = await repository.create(content())
        second = await repository.create(content("other-study"))
        results = await asyncio.gather(
            repository.prepare_command(
                "example-study",
                action=PublicationAction.PUBLISH,
                expected_revision=1,
                expected_digest=first.digest,
                request_id="global-request",
            ),
            repository.prepare_command(
                "other-study",
                action=PublicationAction.PUBLISH,
                expected_revision=1,
                expected_digest=second.digest,
                request_id="global-request",
            ),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, Exception) for item in results) == 1
        conflict = next(item for item in results if isinstance(item, AppError))
        assert (conflict.code, conflict.status_code) == (
            "publishing_request_conflict",
            409,
        )

        winner = next(item for item in results if not isinstance(item, Exception))
        winner_slug = winner.command.slug
        winner_digest = first.digest if winner_slug == "example-study" else second.digest
        withdrawn = await repository.prepare_command(
            winner_slug,
            action=PublicationAction.WITHDRAW,
            expected_revision=1,
            expected_digest=winner_digest,
            request_id="withdraw-newer",
        )
        await repository.acknowledge(
            PublicationReceipt(
                slug=winner_slug,
                sequence=withdrawn.command.sequence,
                request_id=withdrawn.command.request_id,
                action=withdrawn.command.action,
            )
        )

        old_replay = await repository.prepare_command(
            winner_slug,
            action=PublicationAction.PUBLISH,
            expected_revision=1,
            expected_digest=winner_digest,
            request_id="global-request",
        )
        assert old_replay.should_deliver is False
        assert old_replay.state.desired_action is PublicationAction.WITHDRAW
        assert old_replay.state.applied_action is PublicationAction.WITHDRAW

        late_old_ack = await repository.acknowledge(
            PublicationReceipt(
                slug=winner_slug,
                sequence=winner.command.sequence,
                request_id=winner.command.request_id,
                action=winner.command.action,
            )
        )
        assert late_old_ack.applied_sequence == withdrawn.command.sequence
        assert late_old_ack.applied_action is PublicationAction.WITHDRAW
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_success_then_private_ack_failure_replays_safely(
    migrated_publishing_database: IsolatedPublishingDatabase,
    tmp_path: Path,
) -> None:
    engine = create_async_engine(migrated_publishing_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = FailFirstAcknowledgeRepository(sessions)
    public_path = tmp_path / "public.sqlite3"
    service = PublishingService(
        repository,
        LocalPublicationDelivery(SqlitePublicStudyWriter(public_path)),
        approved_personas=(),
        limits=PublishingLimits(),
    )
    try:
        created = await service.create(content())
        with pytest.raises(AppError) as failure:
            await service.publish(
                "example-study",
                expected_revision=1,
                expected_digest=created.digest,
                request_id="publish-once",
            )
        assert (failure.value.code, failure.value.status_code) == (
            "publishing_private_store_unavailable",
            503,
        )
        assert SqlitePublicStudyReader(public_path).get("example-study") == created.snapshot
        pending = await repository.get("example-study")
        assert pending is not None
        assert pending.delivery_pending is True
        assert pending.pending_command is not None
        assert pending.pending_command.action is PublicationAction.PUBLISH
        assert pending.pending_command.expected_revision == 1
        assert pending.pending_command.expected_digest == created.digest
        assert pending.pending_command.request_id == "publish-once"

        revised = await repository.update(
            "example-study",
            expected_revision=1,
            content=content(title="New private draft"),
        )
        assert revised.snapshot.revision == 2
        reloaded = await repository.get("example-study")
        assert reloaded is not None
        assert reloaded.snapshot.revision == 2
        assert reloaded.pending_command == pending.pending_command

        replayed = await service.publish(
            "example-study",
            expected_revision=1,
            expected_digest=created.digest,
            request_id="publish-once",
        )

        assert replayed.applied_sequence == replayed.sequence == 1
        assert replayed.applied_revision == 1
        assert replayed.snapshot.revision == 2
        assert replayed.delivery_pending is False
        assert replayed.pending_command is None
        assert SqlitePublicStudyReader(public_path).get("example-study") == created.snapshot
        async with sessions() as session:
            command_count = await session.scalar(
                select(func.count()).select_from(PublishingCommandRow)
            )
        assert command_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pending_withdrawal_survives_edit_and_clears_after_apply(
    migrated_publishing_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_publishing_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemyPublishingRepository(sessions)
    try:
        created = await repository.create(content())
        prepared = await repository.prepare_command(
            "example-study",
            action=PublicationAction.WITHDRAW,
            expected_revision=1,
            expected_digest=created.digest,
            request_id="withdraw-pending",
        )
        await repository.record_delivery_failure(
            "withdraw-pending",
            error_code="publishing_store_unavailable",
        )
        await repository.update(
            "example-study",
            expected_revision=1,
            content=content(title="Edited while withdrawal is pending"),
        )

        reloaded = await repository.get("example-study")
        assert reloaded is not None
        assert reloaded.snapshot.revision == 2
        assert reloaded.pending_command is not None
        assert reloaded.pending_command.action is PublicationAction.WITHDRAW
        assert reloaded.pending_command.expected_revision == 1
        assert reloaded.pending_command.expected_digest == created.digest
        assert reloaded.pending_command.request_id == "withdraw-pending"

        applied = await repository.acknowledge(
            PublicationReceipt(
                slug="example-study",
                sequence=prepared.command.sequence,
                request_id=prepared.command.request_id,
                action=prepared.command.action,
            )
        )

        assert applied.snapshot.revision == 2
        assert applied.applied_action is PublicationAction.WITHDRAW
        assert applied.delivery_pending is False
        assert applied.pending_command is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_publish_receipt_is_exact_and_future_edit_preserves_audit(
    migrated_publishing_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_publishing_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemyPublishingRepository(sessions)
    try:
        created = await repository.create(content())
        with pytest.raises(AppError) as duplicate:
            await repository.create(content())
        assert (duplicate.value.code, duplicate.value.status_code) == (
            "publishing_slug_conflict",
            409,
        )

        prepared = await repository.prepare_command(
            "example-study",
            action=PublicationAction.PUBLISH,
            expected_revision=1,
            expected_digest=created.digest,
            request_id="publish-audit",
        )
        with pytest.raises(AppError) as mismatched:
            await repository.acknowledge(
                PublicationReceipt(
                    slug="example-study",
                    sequence=1,
                    request_id="publish-audit",
                    action=PublicationAction.WITHDRAW,
                )
            )
        assert (mismatched.value.code, mismatched.value.status_code) == (
            "publishing_receipt_conflict",
            409,
        )

        applied = await repository.acknowledge(
            PublicationReceipt(
                slug="example-study",
                sequence=1,
                request_id="publish-audit",
                action=PublicationAction.PUBLISH,
            )
        )
        revised = await repository.update(
            "example-study",
            expected_revision=1,
            content=content(title="Future edit"),
        )

        assert applied.applied_revision == 1
        assert revised.snapshot.revision == 2
        assert revised.draft.approved_digest is None
        assert revised.applied_sequence == 1
        assert revised.applied_action is PublicationAction.PUBLISH
        assert revised.applied_revision == 1
        async with sessions() as session:
            command = await session.get(PublishingCommandRow, "publish-audit")
        assert command is not None
        assert command.expected_revision == 1
        assert command.expected_digest == created.digest
        assert command.export_payload == canonical_bytes(prepared.command.snapshot)
        assert (
            command.receipt_slug,
            command.receipt_sequence,
            command.receipt_request_id,
            command.receipt_action,
        ) == ("example-study", 1, "publish-audit", "publish")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_initial_publication_refuses_pending_withdrawal(
    migrated_publishing_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_publishing_database.database_url)
    repository = SqlAlchemyPublishingRepository(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    try:
        created = await repository.create(content())
        await repository.prepare_command(
            "example-study",
            action=PublicationAction.WITHDRAW,
            expected_revision=1,
            expected_digest=created.digest,
            request_id="owner-withdrawal",
        )

        with pytest.raises(AppError) as failure:
            await repository.prepare_initial_publication(
                content(),
                expected_digest=created.digest,
                request_id="initial-reviewed-example-study",
            )

        assert (failure.value.code, failure.value.status_code) == (
            "publishing_request_conflict",
            409,
        )
        current = await repository.get("example-study")
        assert current is not None
        assert current.sequence == 1
        assert current.desired_action is PublicationAction.WITHDRAW
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_initial_publication_refuses_command_created_after_unlocked_inspection(
    migrated_publishing_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_publishing_database.database_url)
    repository = SqlAlchemyPublishingRepository(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    try:
        inspected = await repository.create(content())
        assert (await repository.get("example-study")) == inspected
        await repository.prepare_command(
            "example-study",
            action=PublicationAction.PUBLISH,
            expected_revision=1,
            expected_digest=inspected.digest,
            request_id="owner-publish-after-inspection",
        )

        with pytest.raises(AppError) as failure:
            await repository.prepare_initial_publication(
                content(),
                expected_digest=inspected.digest,
                request_id="initial-reviewed-example-study",
            )

        assert (failure.value.code, failure.value.status_code) == (
            "publishing_request_conflict",
            409,
        )
        current = await repository.get("example-study")
        assert current is not None
        assert current.sequence == 1
        assert current.last_request_id == "owner-publish-after-inspection"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_interrupted_initial_publication_replays_only_the_exact_request(
    migrated_publishing_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_publishing_database.database_url)
    repository = SqlAlchemyPublishingRepository(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    initial_content = content()
    digest = snapshot_digest(StudySnapshot(revision=1, content=initial_content))
    try:
        prepared = await repository.prepare_initial_publication(
            initial_content,
            expected_digest=digest,
            request_id="initial-reviewed-example-study",
        )
        await repository.record_delivery_failure(
            prepared.command.request_id,
            error_code="publishing_store_unavailable",
        )

        replayed = await repository.prepare_initial_publication(
            initial_content,
            expected_digest=digest,
            request_id="initial-reviewed-example-study",
        )

        assert replayed.command == prepared.command
        assert replayed.should_deliver is True
        assert replayed.state.sequence == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_applied_initial_publication_rerun_does_not_create_or_deliver_a_command(
    migrated_publishing_database: IsolatedPublishingDatabase,
) -> None:
    engine = create_async_engine(migrated_publishing_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlAlchemyPublishingRepository(sessions)
    initial_content = content()
    digest = snapshot_digest(StudySnapshot(revision=1, content=initial_content))
    try:
        prepared = await repository.prepare_initial_publication(
            initial_content,
            expected_digest=digest,
            request_id="initial-reviewed-example-study",
        )
        await repository.acknowledge(
            PublicationReceipt(
                slug=prepared.command.slug,
                sequence=prepared.command.sequence,
                request_id=prepared.command.request_id,
                action=prepared.command.action,
            )
        )

        replayed = await repository.prepare_initial_publication(
            initial_content,
            expected_digest=digest,
            request_id="initial-reviewed-example-study",
        )

        assert replayed.should_deliver is False
        assert replayed.state.applied_action is PublicationAction.PUBLISH
        assert replayed.state.applied_revision == 1
        async with sessions() as session:
            command_count = await session.scalar(
                select(func.count()).select_from(PublishingCommandRow)
            )
        assert command_count == 1
    finally:
        await engine.dispose()
