from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ai_workshop.platform.learning.domain import LearningRecord, RecordKind
from ai_workshop.platform.learning.repository import (
    LearningCursor,
    LearningListFilters,
    SqlAlchemyLearningRepository,
)
from ai_workshop.platform.learning.schemas import ExperimentFields, LearningDraft
from ai_workshop.shared.db import create_session_factory
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.learning_support import isolated_learning_database

pytestmark = pytest.mark.integration


def _draft(
    title: str,
    *,
    body: str | None = None,
    kind: RecordKind = RecordKind.NOTE,
    topics: tuple[str, ...] = (),
) -> LearningDraft:
    return LearningDraft(
        title=title,
        body=body or f"private body for {title}",
        kind=kind,
        topic_keys=topics,
        experiment=ExperimentFields() if kind is RecordKind.EXPERIMENT else None,
    )


def _record(
    owner_id: UUID,
    title: str,
    *,
    record_id: UUID | None = None,
    now: datetime | None = None,
    kind: RecordKind = RecordKind.NOTE,
    topics: tuple[str, ...] = (),
) -> LearningRecord:
    timestamp = now or datetime.now(UTC)
    return LearningRecord(
        id=record_id or uuid4(),
        owner_id=owner_id,
        draft=_draft(title, kind=kind, topics=topics),
        revision=1,
        created_at=timestamp,
        updated_at=timestamp,
    )


async def _add_owner(session: object, owner_id: UUID) -> None:
    await session.execute(  # type: ignore[attr-defined]
        text(
            """
            INSERT INTO users (
                id, display_name, email, normalized_email, password_hash,
                role, is_active
            ) VALUES (
                :id, 'Fixture owner', :email, :email, 'fixture-hash', 'owner', true
            )
            """
        ),
        {"id": owner_id, "email": f"{owner_id}@example.test"},
    )


@pytest.fixture
def migrated_learning_database(
    monkeypatch: pytest.MonkeyPatch,
):
    with isolated_learning_database(monkeypatch) as database:
        command.upgrade(database.config, "0024_learning_records")
        yield database


async def test_owner_isolation_revision_round_trip_and_archive_restore(
    migrated_learning_database,
) -> None:
    engine = create_engine_from_url(migrated_learning_database.database_url)
    sessions = create_session_factory(engine)
    owner_a, owner_b = uuid4(), uuid4()
    original = _record(owner_a, "note v1", topics=("rag",))
    try:
        async with sessions.begin() as session:
            await _add_owner(session, owner_a)
            await _add_owner(session, owner_b)
            await SqlAlchemyLearningRepository(session).create(original)

        async with sessions.begin() as session:
            repository = SqlAlchemyLearningRepository(session)
            assert await repository.get_owned(original.id, owner_b) is None
            current = await repository.get_owned(original.id, owner_a)
            assert current == original
            revised = current.revise(
                _draft(
                    "experiment v2",
                    body="experiment body only",
                    kind=RecordKind.EXPERIMENT,
                    topics=("fine-tuning",),
                ),
                expected_revision=1,
            )
            await repository.save_revision(revised, expected_revision=1)

        async with sessions.begin() as session:
            repository = SqlAlchemyLearningRepository(session)
            revision_1 = await repository.get_revision_owned(original.id, 1, owner_a)
            current = await repository.get_owned(original.id, owner_a)
            assert revision_1 == original
            assert revision_1 is not None
            assert revision_1.draft.body == "private body for note v1"
            assert current is not None
            assert current.revision == 2
            assert current.draft.kind is RecordKind.EXPERIMENT
            assert current.draft.body == "experiment body only"
            archived = current.archive(expected_revision=2)
            await repository.save_revision(archived, expected_revision=2)

        async with sessions.begin() as session:
            repository = SqlAlchemyLearningRepository(session)
            current = await repository.get_owned(original.id, owner_a)
            assert current is not None and current.archived_at is not None
            with pytest.raises(AppError) as stale:
                await repository.save_revision(current, expected_revision=1)
            assert stale.value.code == "learning_revision_conflict"
            restored = current.restore(expected_revision=3)
            await repository.save_revision(restored, expected_revision=3)

        async with sessions.begin() as session:
            repository = SqlAlchemyLearningRepository(session)
            assert await repository.get_revision_owned(original.id, 1, owner_b) is None
            revisions = [
                await repository.get_revision_owned(original.id, revision, owner_a)
                for revision in range(1, 5)
            ]
            assert [item.revision for item in revisions if item is not None] == [1, 2, 3, 4]
            assert [item.archived_at is not None for item in revisions if item is not None] == [
                False,
                False,
                True,
                False,
            ]
            assert revisions[0] is not None
            assert revisions[0].draft.kind is RecordKind.NOTE
            assert revisions[1] is not None
            assert revisions[1].draft.kind is RecordKind.EXPERIMENT
    finally:
        await engine.dispose()


async def test_concurrent_compare_and_swap_has_one_winner(
    migrated_learning_database,
) -> None:
    engine = create_engine_from_url(migrated_learning_database.database_url)
    sessions = create_session_factory(engine)
    owner_id = uuid4()
    original = _record(owner_id, "initial")
    try:
        async with sessions.begin() as session:
            await _add_owner(session, owner_id)
            await SqlAlchemyLearningRepository(session).create(original)

        ready = asyncio.Event()
        loaded = 0
        loaded_lock = asyncio.Lock()

        async def contender(title: str) -> str:
            nonlocal loaded
            try:
                async with sessions.begin() as session:
                    repository = SqlAlchemyLearningRepository(session)
                    current = await repository.get_owned(original.id, owner_id)
                    assert current is not None
                    candidate = current.revise(_draft(title), expected_revision=1)
                    async with loaded_lock:
                        loaded += 1
                        if loaded == 2:
                            ready.set()
                    await ready.wait()
                    await repository.save_revision(candidate, expected_revision=1)
                return "saved"
            except AppError as exc:
                return exc.code

        outcomes = await asyncio.gather(contender("winner a"), contender("winner b"))
        assert sorted(outcomes) == ["learning_revision_conflict", "saved"]

        async with sessions.begin() as session:
            repository = SqlAlchemyLearningRepository(session)
            current = await repository.get_owned(original.id, owner_id)
            assert current is not None
            assert current.revision == 2
            assert current.draft.title in {"winner a", "winner b"}
            assert await repository.get_revision_owned(original.id, 1, owner_id) == original
            assert await session.scalar(
                text(
                    "SELECT count(*) FROM learning_record_revisions "
                    "WHERE record_id = :record_id"
                ),
                {"record_id": original.id},
            ) == 2
    finally:
        await engine.dispose()


async def test_revision_insert_failure_rolls_back_current_pointer_even_if_caught(
    migrated_learning_database,
) -> None:
    engine = create_engine_from_url(migrated_learning_database.database_url)
    sessions = create_session_factory(engine)
    owner_id = uuid4()
    original = _record(owner_id, "unchanged")
    try:
        async with sessions.begin() as session:
            await _add_owner(session, owner_id)
            await SqlAlchemyLearningRepository(session).create(original)

        async with sessions.begin() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO learning_record_revisions (
                        record_id, revision, draft, archived_at, created_at, updated_at
                    ) VALUES (
                        :record_id, 2, CAST(:draft AS jsonb), NULL, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "record_id": original.id,
                    "draft": original.draft.model_dump_json(),
                    "created_at": original.created_at,
                    "updated_at": original.updated_at + timedelta(seconds=1),
                },
            )

        async with sessions.begin() as session:
            repository = SqlAlchemyLearningRepository(session)
            candidate = original.revise(_draft("must not commit"), expected_revision=1)
            with pytest.raises(IntegrityError):
                await repository.save_revision(candidate, expected_revision=1)
            assert await repository.get_owned(original.id, owner_id) == original

        async with sessions.begin() as session:
            repository = SqlAlchemyLearningRepository(session)
            assert await repository.get_owned(original.id, owner_id) == original
            assert await session.scalar(
                text("SELECT current_revision FROM learning_records WHERE id = :record_id"),
                {"record_id": original.id},
            ) == 1
    finally:
        await engine.dispose()


async def test_list_filters_and_stable_keyset_cursor_exclude_body(
    migrated_learning_database,
) -> None:
    engine = create_engine_from_url(migrated_learning_database.database_url)
    sessions = create_session_factory(engine)
    owner_a, owner_b = uuid4(), uuid4()
    tied_at = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    tied_ids = [
        UUID("00000000-0000-0000-0000-000000000004"),
        UUID("00000000-0000-0000-0000-000000000003"),
        UUID("00000000-0000-0000-0000-000000000002"),
        UUID("00000000-0000-0000-0000-000000000001"),
    ]
    tied = [
        _record(owner_a, f"tie {index}", record_id=record_id, now=tied_at, topics=("rag",))
        for index, record_id in enumerate(tied_ids)
    ]
    experiment = _record(
        owner_a,
        "experiment",
        now=tied_at - timedelta(minutes=1),
        kind=RecordKind.EXPERIMENT,
        topics=("fine-tuning",),
    )
    foreign_active_rag_note = _record(
        owner_b,
        "foreign active rag note",
        now=tied_at + timedelta(days=3),
        topics=("rag",),
    )
    foreign_archived_rag_note = _record(
        owner_b,
        "foreign archived rag note",
        now=tied_at + timedelta(days=2),
        topics=("rag",),
    )
    foreign_active_experiment = _record(
        owner_b,
        "foreign active experiment",
        now=tied_at + timedelta(days=1),
        kind=RecordKind.EXPERIMENT,
        topics=("fine-tuning",),
    )
    try:
        async with sessions.begin() as session:
            await _add_owner(session, owner_a)
            await _add_owner(session, owner_b)
            repository = SqlAlchemyLearningRepository(session)
            for record in (
                *tied,
                experiment,
                foreign_active_rag_note,
                foreign_archived_rag_note,
                foreign_active_experiment,
            ):
                await repository.create(record)
            archived = tied[-1].archive(expected_revision=1)
            await repository.save_revision(archived, expected_revision=1)
            foreign_archived = foreign_archived_rag_note.archive(expected_revision=1)
            await repository.save_revision(foreign_archived, expected_revision=1)

        async with sessions.begin() as session:
            repository = SqlAlchemyLearningRepository(session)
            notes = await repository.list_owned(
                owner_a,
                LearningListFilters(topic_key="rag", kind=RecordKind.NOTE, archived=False),
                cursor=None,
                limit=2,
            )
            assert [item.id for item in notes.items] == tied_ids[:2]
            assert all(item.id != foreign_active_rag_note.id for item in notes.items)
            assert all(
                not hasattr(item, "body") and not hasattr(item, "draft")
                for item in notes.items
            )
            assert notes.next_cursor == LearningCursor(updated_at=tied_at, record_id=tied_ids[1])

            next_page = await repository.list_owned(
                owner_a,
                LearningListFilters(topic_key="rag", kind=RecordKind.NOTE, archived=False),
                cursor=notes.next_cursor,
                limit=2,
            )
            assert [item.id for item in next_page.items] == [tied_ids[2]]
            assert all(item.id != foreign_active_rag_note.id for item in next_page.items)
            assert next_page.next_cursor is None

            archived_page = await repository.list_owned(
                owner_a,
                LearningListFilters(topic_key="rag", archived=True),
                cursor=None,
                limit=10,
            )
            assert [item.id for item in archived_page.items] == [tied_ids[3]]
            assert all(
                item.id != foreign_archived_rag_note.id for item in archived_page.items
            )
            experiment_page = await repository.list_owned(
                owner_a,
                LearningListFilters(kind=RecordKind.EXPERIMENT, archived=False),
                cursor=None,
                limit=10,
            )
            assert [item.id for item in experiment_page.items] == [experiment.id]
            assert all(
                item.id != foreign_active_experiment.id for item in experiment_page.items
            )
    finally:
        await engine.dispose()


def create_engine_from_url(database_url: str):
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )
