from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.learning.domain import LearningRecord, RecordKind
from ai_workshop.platform.learning.models import (
    LearningRecordRevisionRow,
    LearningRecordRow,
)
from ai_workshop.platform.learning.schemas import LearningDraft
from ai_workshop.shared.errors import AppError


@dataclass(frozen=True, slots=True)
class LearningListFilters:
    topic_key: str | None = None
    kind: RecordKind | None = None
    archived: bool | None = None


@dataclass(frozen=True, slots=True)
class LearningCursor:
    updated_at: datetime
    record_id: UUID


@dataclass(frozen=True, slots=True)
class LearningSummary:
    id: UUID
    title: str
    kind: RecordKind
    topic_keys: tuple[str, ...]
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True, slots=True)
class LearningPage:
    items: tuple[LearningSummary, ...]
    next_cursor: LearningCursor | None


class LearningRepository(Protocol):
    async def create(self, record: LearningRecord) -> LearningRecord: ...

    async def get_owned(self, record_id: UUID, actor_id: UUID) -> LearningRecord | None: ...

    async def get_revision_owned(
        self,
        record_id: UUID,
        revision: int,
        actor_id: UUID,
    ) -> LearningRecord | None: ...

    async def save_revision(
        self,
        record: LearningRecord,
        expected_revision: int,
    ) -> LearningRecord: ...

    async def list_owned(
        self,
        actor_id: UUID,
        filters: LearningListFilters,
        cursor: LearningCursor | None,
        limit: int,
    ) -> LearningPage: ...


def _revision_values(record: LearningRecord) -> dict[str, object]:
    return {
        "record_id": record.id,
        "revision": record.revision,
        "draft": record.draft.model_dump(mode="json"),
        "archived_at": record.archived_at,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _to_domain(
    current: LearningRecordRow,
    revision: LearningRecordRevisionRow,
) -> LearningRecord:
    return LearningRecord(
        id=current.id,
        owner_id=current.owner_id,
        draft=LearningDraft.model_validate(revision.draft),
        revision=revision.revision,
        created_at=revision.created_at,
        updated_at=revision.updated_at,
        archived_at=revision.archived_at,
    )


class SqlAlchemyLearningRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, record: LearningRecord) -> LearningRecord:
        async with self.session.begin_nested():
            await self.session.execute(
                insert(LearningRecordRow).values(
                    id=record.id,
                    owner_id=record.owner_id,
                    title=record.draft.title,
                    kind=record.draft.kind.value,
                    topic_keys=list(record.draft.topic_keys),
                    current_revision=record.revision,
                    archived_at=record.archived_at,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )
            await self.session.execute(
                insert(LearningRecordRevisionRow).values(**_revision_values(record))
            )
            await self.session.flush()
        return record

    async def get_owned(
        self,
        record_id: UUID,
        actor_id: UUID,
    ) -> LearningRecord | None:
        row = (
            await self.session.execute(
                select(LearningRecordRow, LearningRecordRevisionRow)
                .join(
                    LearningRecordRevisionRow,
                    and_(
                        LearningRecordRevisionRow.record_id == LearningRecordRow.id,
                        LearningRecordRevisionRow.revision
                        == LearningRecordRow.current_revision,
                    ),
                )
                .where(
                    LearningRecordRow.id == record_id,
                    LearningRecordRow.owner_id == actor_id,
                )
            )
        ).one_or_none()
        return _to_domain(*row) if row is not None else None

    async def get_revision_owned(
        self,
        record_id: UUID,
        revision: int,
        actor_id: UUID,
    ) -> LearningRecord | None:
        row = (
            await self.session.execute(
                select(LearningRecordRow, LearningRecordRevisionRow)
                .join(
                    LearningRecordRevisionRow,
                    LearningRecordRevisionRow.record_id == LearningRecordRow.id,
                )
                .where(
                    LearningRecordRow.id == record_id,
                    LearningRecordRow.owner_id == actor_id,
                    LearningRecordRevisionRow.revision == revision,
                )
            )
        ).one_or_none()
        return _to_domain(*row) if row is not None else None

    async def save_revision(
        self,
        record: LearningRecord,
        expected_revision: int,
    ) -> LearningRecord:
        async with self.session.begin_nested():
            updated_id = await self.session.scalar(
                update(LearningRecordRow)
                .where(
                    LearningRecordRow.id == record.id,
                    LearningRecordRow.owner_id == record.owner_id,
                    LearningRecordRow.current_revision == expected_revision,
                )
                .values(
                    title=record.draft.title,
                    kind=record.draft.kind.value,
                    topic_keys=list(record.draft.topic_keys),
                    current_revision=record.revision,
                    archived_at=record.archived_at,
                    updated_at=record.updated_at,
                )
                .returning(LearningRecordRow.id)
            )
            if updated_id is None:
                raise AppError(
                    "learning_revision_conflict",
                    "The learning record has changed.",
                    409,
                )
            await self.session.execute(
                insert(LearningRecordRevisionRow).values(**_revision_values(record))
            )
            await self.session.flush()
        return record

    async def list_owned(
        self,
        actor_id: UUID,
        filters: LearningListFilters,
        cursor: LearningCursor | None,
        limit: int,
    ) -> LearningPage:
        if limit < 1:
            raise ValueError("limit must be positive")
        statement = select(LearningRecordRow).where(LearningRecordRow.owner_id == actor_id)
        if filters.topic_key is not None:
            statement = statement.where(
                LearningRecordRow.topic_keys.contains([filters.topic_key])
            )
        if filters.kind is not None:
            statement = statement.where(LearningRecordRow.kind == filters.kind.value)
        if filters.archived is True:
            statement = statement.where(LearningRecordRow.archived_at.is_not(None))
        elif filters.archived is False:
            statement = statement.where(LearningRecordRow.archived_at.is_(None))
        if cursor is not None:
            statement = statement.where(
                or_(
                    LearningRecordRow.updated_at < cursor.updated_at,
                    and_(
                        LearningRecordRow.updated_at == cursor.updated_at,
                        LearningRecordRow.id < cursor.record_id,
                    ),
                )
            )
        rows = (
            await self.session.scalars(
                statement.order_by(
                    LearningRecordRow.updated_at.desc(),
                    LearningRecordRow.id.desc(),
                ).limit(limit + 1)
            )
        ).all()
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        items = tuple(
            LearningSummary(
                id=row.id,
                title=row.title,
                kind=RecordKind(row.kind),
                topic_keys=tuple(row.topic_keys),
                revision=row.current_revision,
                created_at=row.created_at,
                updated_at=row.updated_at,
                archived_at=row.archived_at,
            )
            for row in visible_rows
        )
        next_cursor = None
        if has_more and visible_rows:
            last = visible_rows[-1]
            next_cursor = LearningCursor(updated_at=last.updated_at, record_id=last.id)
        return LearningPage(items=items, next_cursor=next_cursor)

