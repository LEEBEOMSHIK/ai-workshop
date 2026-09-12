from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.config import LearningLimits
from ai_workshop.platform.learning.domain import LearningRecord, RecordKind
from ai_workshop.platform.learning.references import (
    ReferenceResolver,
    ReferenceStatus,
    ReferenceView,
)
from ai_workshop.platform.learning.repository import (
    LearningCursor,
    LearningListFilters,
    LearningPage,
    LearningRepository,
    LearningSummary,
)
from ai_workshop.platform.learning.schemas import (
    ExperimentFields,
    LearningDraft,
    ReferenceKey,
)
from ai_workshop.platform.learning.service import LearningCursorCodec, LearningService
from ai_workshop.shared.errors import AppError


class MemoryLearningRepository(LearningRepository):
    def __init__(self, *records: LearningRecord) -> None:
        self.records = {record.id: record for record in records}
        self.revisions = {(record.id, record.revision): record for record in records}
        self.create_calls = 0
        self.list_cursor: LearningCursor | None = None
        self.list_limits: list[int] = []

    async def create(self, record: LearningRecord) -> LearningRecord:
        self.create_calls += 1
        self.records[record.id] = record
        self.revisions[(record.id, record.revision)] = record
        return record

    async def get_owned(
        self, record_id: UUID, actor_id: UUID
    ) -> LearningRecord | None:
        record = self.records.get(record_id)
        return record if record is not None and record.owner_id == actor_id else None

    async def get_revision_owned(
        self, record_id: UUID, revision: int, actor_id: UUID
    ) -> LearningRecord | None:
        record = self.revisions.get((record_id, revision))
        return record if record is not None and record.owner_id == actor_id else None

    async def save_revision(
        self, record: LearningRecord, expected_revision: int
    ) -> LearningRecord:
        current = self.records.get(record.id)
        if current is None or current.revision != expected_revision:
            raise AppError(
                "learning_revision_conflict",
                "The learning record has changed.",
                409,
            )
        self.records[record.id] = record
        self.revisions[(record.id, record.revision)] = record
        return record

    async def list_owned(
        self,
        actor_id: UUID,
        filters: LearningListFilters,
        cursor: LearningCursor | None,
        limit: int,
    ) -> LearningPage:
        del filters
        self.list_cursor = cursor
        self.list_limits.append(limit)
        items = tuple(
            LearningSummary(
                id=record.id,
                title=record.draft.title,
                kind=record.draft.kind,
                topic_keys=record.draft.topic_keys,
                revision=record.revision,
                created_at=record.created_at,
                updated_at=record.updated_at,
                archived_at=record.archived_at,
            )
            for record in self.records.values()
            if record.owner_id == actor_id
        )
        return LearningPage(items=items, next_cursor=None)


class MutableReferenceResolver(ReferenceResolver):
    def __init__(self) -> None:
        self.available = True
        self.calls: list[tuple[UUID, ReferenceKey]] = []

    async def resolve(self, actor_id: UUID, key: ReferenceKey) -> ReferenceView:
        self.calls.append((actor_id, key))
        if not self.available:
            return ReferenceView.unavailable()
        return ReferenceView(
            status=ReferenceStatus.AVAILABLE,
            label="Visible evaluation",
            href=None,
            key=key,
        )


def limits(**changes: int) -> LearningLimits:
    return LearningLimits(**changes)


def test_page_default_cannot_exceed_page_max() -> None:
    with pytest.raises(ValidationError) as caught:
        LearningLimits(page_default=3, page_max=2)

    assert caught.value.errors()[0]["type"] == "value_error"


def service_for(
    repository: MemoryLearningRepository,
    resolver: MutableReferenceResolver,
    *,
    configured_limits: LearningLimits | None = None,
    commit: Callable[[], Awaitable[None]] | None = None,
) -> LearningService:
    return LearningService(
        repository,
        resolver,
        configured_limits or limits(),
        LearningCursorCodec("cursor-secret-" * 4, max_length=4096),
        commit=commit,
    )


@pytest.mark.asyncio
async def test_create_validates_all_references_before_persisting_and_commits_once() -> None:
    actor_id = uuid4()
    repository = MemoryLearningRepository()
    resolver = MutableReferenceResolver()
    commits = 0

    async def commit() -> None:
        nonlocal commits
        commits += 1

    service = service_for(repository, resolver, commit=commit)
    top_level = ReferenceKey(kind="service", target="rag.search")
    dataset = ReferenceKey(kind="rag.evaluation", target=str(uuid4()))
    draft = LearningDraft(
        title="Retrieval experiment",
        body="Compare fixed evidence.",
        kind="experiment",
        references=(top_level,),
        experiment=ExperimentFields(dataset_snapshot=dataset),
    )

    result = await service.create(actor_id, draft)

    assert result.revision == 1
    assert repository.create_calls == 1
    assert resolver.calls == [(actor_id, top_level), (actor_id, dataset)]
    assert commits == 1


@pytest.mark.asyncio
async def test_unavailable_write_reference_is_rejected_without_persistence() -> None:
    repository = MemoryLearningRepository()
    resolver = MutableReferenceResolver()
    resolver.available = False
    service = service_for(repository, resolver)
    private_target = "private-target-that-must-not-leak"
    draft = LearningDraft(
        title="Reference",
        body="Body",
        kind="note",
        references=(ReferenceKey(kind="service", target=private_target),),
    )

    with pytest.raises(AppError) as caught:
        await service.create(uuid4(), draft)

    assert caught.value.code == "learning_reference_unavailable"
    assert private_target not in caught.value.message
    assert repository.create_calls == 0


@pytest.mark.asyncio
async def test_revoked_references_are_removed_from_current_and_historical_drafts() -> None:
    actor_id = uuid4()
    private_target = "private-evaluation-id"
    reference = ReferenceKey(kind="rag.evaluation", target=private_target)
    dataset = ReferenceKey(kind="rag.evaluation", target=str(uuid4()))
    draft = LearningDraft(
        title="Safe title",
        body="Safe body",
        kind="experiment",
        references=(reference,),
        experiment=ExperimentFields(dataset_snapshot=dataset),
    )
    record = LearningRecord.create(owner_id=actor_id, draft=draft)
    repository = MemoryLearningRepository(record)
    resolver = MutableReferenceResolver()
    resolver.available = False
    service = service_for(repository, resolver)

    current = await service.detail(actor_id, record.id)
    historical = await service.detail(actor_id, record.id, revision=1)

    for result in (current, historical):
        assert result.draft.references == ()
        assert result.draft.experiment is not None
        assert result.draft.experiment.dataset_snapshot is None
        assert result.reference_views == (ReferenceView.unavailable(),)
        assert result.dataset_reference_view == ReferenceView.unavailable()
        assert result.unavailable_reference_count == 2
    assert repository.records[record.id].draft.references == (reference,)
    assert repository.records[record.id].draft.experiment == draft.experiment


@pytest.mark.asyncio
async def test_other_owner_is_not_found_without_resolving_private_references() -> None:
    owner_id = uuid4()
    other_id = uuid4()
    record = LearningRecord.create(
        owner_id=owner_id,
        draft=LearningDraft(title="Private", body="Secret", kind="note"),
    )
    repository = MemoryLearningRepository(record)
    resolver = MutableReferenceResolver()

    with pytest.raises(AppError) as caught:
        await service_for(repository, resolver).detail(other_id, record.id)

    assert caught.value.code == "not_found"
    assert resolver.calls == []


@pytest.mark.asyncio
async def test_nested_limits_are_enforced_before_reference_resolution() -> None:
    repository = MemoryLearningRepository()
    resolver = MutableReferenceResolver()
    service = service_for(
        repository,
        resolver,
        configured_limits=limits(max_text_field_chars=10),
    )
    draft = LearningDraft(
        title="Title",
        body="Body",
        kind="experiment",
        experiment=ExperimentFields(purpose="12345678901"),
    )

    with pytest.raises(AppError) as caught:
        await service.create(uuid4(), draft)

    assert caught.value.code == "learning_invalid_input"
    assert resolver.calls == []
    assert repository.create_calls == 0


@pytest.mark.parametrize(
    ("configured_limits", "draft"),
    (
        (
            limits(title_max_chars=4),
            LearningDraft(title="12345", body="Body", kind="note"),
        ),
        (
            limits(body_max_chars=4),
            LearningDraft(title="Title", body="12345", kind="note"),
        ),
        (
            limits(max_references=1),
            LearningDraft(
                title="Title",
                body="Body",
                kind="note",
                references=(
                    ReferenceKey(kind="service", target="one"),
                    ReferenceKey(kind="service", target="two"),
                ),
            ),
        ),
        (
            limits(max_collection_items=1),
            LearningDraft(
                title="Title",
                body="Body",
                kind="note",
                domain_labels=("one", "two"),
            ),
        ),
        (
            limits(aggregate_draft_max_bytes=1),
            LearningDraft(title="Title", body="Body", kind="note"),
        ),
    ),
)
@pytest.mark.asyncio
async def test_each_draft_limit_rejects_input_before_side_effects(
    configured_limits: LearningLimits,
    draft: LearningDraft,
) -> None:
    repository = MemoryLearningRepository()
    resolver = MutableReferenceResolver()

    with pytest.raises(AppError) as caught:
        await service_for(
            repository,
            resolver,
            configured_limits=configured_limits,
        ).create(uuid4(), draft)

    assert caught.value.code == "learning_invalid_input"
    assert repository.create_calls == 0
    assert resolver.calls == []


@pytest.mark.asyncio
async def test_update_archive_and_restore_each_commit_after_persistence() -> None:
    actor_id = uuid4()
    record = LearningRecord.create(
        owner_id=actor_id,
        draft=LearningDraft(title="Title", body="Body", kind="note"),
    )
    repository = MemoryLearningRepository(record)
    resolver = MutableReferenceResolver()
    commits = 0

    async def commit() -> None:
        nonlocal commits
        commits += 1

    service = service_for(repository, resolver, commit=commit)
    updated = await service.update(
        actor_id,
        record.id,
        1,
        LearningDraft(title="Updated", body="Body", kind="note"),
    )
    archived = await service.archive(actor_id, record.id, updated.revision)
    restored = await service.restore(actor_id, record.id, archived.revision)

    assert (updated.revision, archived.revision, restored.revision) == (2, 3, 4)
    assert commits == 3
    assert repository.records[record.id].archived_at is None


@pytest.mark.parametrize("operation", ("create", "update", "archive", "restore"))
@pytest.mark.asyncio
async def test_mutations_persist_before_committing(operation: str) -> None:
    actor_id = uuid4()
    active = LearningRecord.create(
        owner_id=actor_id,
        draft=LearningDraft(title="Title", body="Body", kind="note"),
    )
    initial = active.archive(expected_revision=1) if operation == "restore" else active
    events: list[str] = []

    class EventRepository(MemoryLearningRepository):
        async def create(self, record: LearningRecord) -> LearningRecord:
            events.append("persist")
            return await super().create(record)

        async def save_revision(
            self, record: LearningRecord, expected_revision: int
        ) -> LearningRecord:
            events.append("persist")
            return await super().save_revision(record, expected_revision)

    async def commit() -> None:
        events.append("commit")

    repository = EventRepository(initial)
    service = service_for(repository, MutableReferenceResolver(), commit=commit)
    if operation == "create":
        await service.create(
            actor_id, LearningDraft(title="Created", body="Body", kind="note")
        )
    elif operation == "update":
        await service.update(
            actor_id,
            initial.id,
            initial.revision,
            LearningDraft(title="Updated", body="Body", kind="note"),
        )
    elif operation == "archive":
        await service.archive(actor_id, initial.id, initial.revision)
    else:
        await service.restore(actor_id, initial.id, initial.revision)

    assert events == ["persist", "commit"]


@pytest.mark.parametrize("operation", ("create", "update", "archive", "restore"))
@pytest.mark.asyncio
async def test_repository_failure_prevents_commit_for_every_mutation(
    operation: str,
) -> None:
    actor_id = uuid4()
    active = LearningRecord.create(
        owner_id=actor_id,
        draft=LearningDraft(title="Title", body="Body", kind="note"),
    )
    initial = active.archive(expected_revision=1) if operation == "restore" else active
    events: list[str] = []

    class FailingRepository(MemoryLearningRepository):
        async def create(self, record: LearningRecord) -> LearningRecord:
            del record
            events.append("persist")
            raise RuntimeError("persistence failed")

        async def save_revision(
            self, record: LearningRecord, expected_revision: int
        ) -> LearningRecord:
            del record, expected_revision
            events.append("persist")
            raise RuntimeError("persistence failed")

    async def commit() -> None:
        events.append("commit")

    service = service_for(
        FailingRepository(initial), MutableReferenceResolver(), commit=commit
    )
    with pytest.raises(RuntimeError, match="persistence failed"):
        if operation == "create":
            await service.create(
                actor_id, LearningDraft(title="Created", body="Body", kind="note")
            )
        elif operation == "update":
            await service.update(
                actor_id,
                initial.id,
                initial.revision,
                LearningDraft(title="Updated", body="Body", kind="note"),
            )
        elif operation == "archive":
            await service.archive(actor_id, initial.id, initial.revision)
        else:
            await service.restore(actor_id, initial.id, initial.revision)

    assert events == ["persist"]


@pytest.mark.asyncio
async def test_commit_failure_is_surfaced_instead_of_reporting_success() -> None:
    repository = MemoryLearningRepository()
    resolver = MutableReferenceResolver()

    async def fail_commit() -> None:
        raise RuntimeError("commit failed")

    service = service_for(repository, resolver, commit=fail_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        await service.create(
            uuid4(), LearningDraft(title="Title", body="Body", kind="note")
        )


@pytest.mark.asyncio
async def test_cursor_is_bound_to_actor_and_normalized_filters_and_detects_tampering() -> None:
    actor_id = uuid4()
    record = LearningRecord.create(
        owner_id=actor_id,
        draft=LearningDraft(title="Title", body="Body", kind="note"),
    )
    repository = MemoryLearningRepository(record)
    resolver = MutableReferenceResolver()
    codec = LearningCursorCodec("cursor-secret-" * 4, max_length=4096)
    cursor = codec.encode(
        actor_id,
        LearningListFilters(topic_key="rag", kind=RecordKind.NOTE, archived=False),
        LearningCursor(
            updated_at=datetime(2026, 9, 7, 1, 2, 3, tzinfo=UTC),
            record_id=uuid4(),
        ),
    )
    service = LearningService(repository, resolver, limits(), codec)

    await service.list_for(
        actor_id,
        LearningListFilters(topic_key="rag", kind=RecordKind.NOTE, archived=False),
        cursor,
        20,
    )
    assert repository.list_cursor is not None

    encoded_payload, signature = cursor.split(".", maxsplit=1)
    # The first character changes decoded signature bits, never just padding bits.
    replacement = "B" if signature[0] == "A" else "A"
    tampered_cursor = f"{encoded_payload}.{replacement}{signature[1:]}"

    for wrong_actor, wrong_filters, invalid_cursor in (
        (uuid4(), LearningListFilters("rag", RecordKind.NOTE, False), cursor),
        (actor_id, LearningListFilters("fine-tuning", RecordKind.NOTE, False), cursor),
        (actor_id, LearningListFilters("rag", RecordKind.NOTE, False), tampered_cursor),
    ):
        with pytest.raises(AppError) as caught:
            await service.list_for(
                wrong_actor,
                wrong_filters,
                invalid_cursor,
                20,
            )
        assert caught.value.code == "learning_invalid_input"


@pytest.mark.asyncio
async def test_cursor_length_and_page_limit_are_checked_before_decoding_or_querying() -> None:
    repository = MemoryLearningRepository()
    resolver = MutableReferenceResolver()
    service = LearningService(
        repository,
        resolver,
        limits(page_default=2, page_max=2, cursor_max_chars=8),
        LearningCursorCodec("cursor-secret-" * 4, max_length=8),
    )

    await service.list_for(uuid4(), LearningListFilters(), None, 1)
    await service.list_for(uuid4(), LearningListFilters(), None, 2)

    for cursor, limit in (("x" * 9, 1), (None, 3)):
        with pytest.raises(AppError) as caught:
            await service.list_for(uuid4(), LearningListFilters(), cursor, limit)
        assert caught.value.code == "learning_invalid_input"
    assert repository.list_limits == [1, 2]


@pytest.mark.asyncio
async def test_next_cursor_is_produced_and_consumed_as_the_same_typed_position() -> None:
    actor_id = uuid4()
    position = LearningCursor(
        updated_at=datetime(2026, 9, 7, 1, 2, 3, tzinfo=UTC),
        record_id=uuid4(),
    )

    class PagingRepository(MemoryLearningRepository):
        async def list_owned(
            self,
            actor_id: UUID,
            filters: LearningListFilters,
            cursor: LearningCursor | None,
            limit: int,
        ) -> LearningPage:
            del actor_id, filters, limit
            self.list_cursor = cursor
            return LearningPage(
                items=(),
                next_cursor=position if cursor is None else None,
            )

    repository = PagingRepository()
    service = service_for(repository, MutableReferenceResolver())
    filters = LearningListFilters(topic_key="rag", kind=RecordKind.NOTE, archived=False)

    first = await service.list_for(actor_id, filters, None, 1)
    assert first.next_cursor is not None
    second = await service.list_for(actor_id, filters, first.next_cursor, 1)

    assert repository.list_cursor == position
    assert second.next_cursor is None
