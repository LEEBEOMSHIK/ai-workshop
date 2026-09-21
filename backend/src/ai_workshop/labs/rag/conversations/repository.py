from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.conversations.attachment_lifecycle import (
    reconcile_deleted_attachments,
    reconcile_owner_cleanup,
)
from ai_workshop.labs.rag.conversations.domain import Conversation, Turn, TurnStatus
from ai_workshop.labs.rag.conversations.models import ConversationRecord, ConversationTurnRecord
from ai_workshop.labs.rag.domains.models import RagDomainRecord
from ai_workshop.shared.errors import AppError


def missing() -> AppError:
    return AppError("not_found", "The requested conversation was not found.", 404)


class SqlAlchemyConversationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def domain_id(self, slug: str) -> UUID:
        async with self.sessions() as session:
            value = await session.scalar(
                select(RagDomainRecord.id).where(RagDomainRecord.slug == slug)
            )
            if value is None:
                raise missing()
            return value

    async def create(self, item: Conversation) -> None:
        async with self.sessions.begin() as session:
            session.add(
                ConversationRecord(
                    id=item.id,
                    owner_id=item.owner_id,
                    domain_id=item.domain_id,
                    title=item.title,
                    revision=item.revision,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
            )

    async def list(self, owner_id: UUID, domain_id: UUID) -> list[Conversation]:
        async with self.sessions.begin() as session:
            await reconcile_owner_cleanup(session, owner_id, domain_id)
            records = (
                await session.scalars(
                    select(ConversationRecord)
                    .where(
                        ConversationRecord.owner_id == owner_id,
                        ConversationRecord.domain_id == domain_id,
                        ConversationRecord.deleted_at.is_(None),
                    )
                    .order_by(ConversationRecord.updated_at.desc(), ConversationRecord.id)
                )
            ).all()
            return [self._conversation(record) for record in records]

    async def record_termination(
        self,
        owner_id: UUID,
        domain_id: UUID,
        id: UUID,
        turn_id: UUID,
    ) -> None:
        """Only acknowledge termination on an owned tombstone; never restore payloads."""
        async with self.sessions.begin() as session:
            record = await session.scalar(
                select(ConversationRecord)
                .where(
                    ConversationRecord.id == id,
                    ConversationRecord.owner_id == owner_id,
                    ConversationRecord.domain_id == domain_id,
                    ConversationRecord.deleted_at.is_not(None),
                )
                .with_for_update()
            )
            if record is None:
                return
            turn = await session.scalar(
                select(ConversationTurnRecord).where(
                    ConversationTurnRecord.conversation_id == id,
                    ConversationTurnRecord.id == turn_id,
                )
            )
            if turn is not None:
                turn.execution_terminated = True
                await session.flush()
                await reconcile_deleted_attachments(session, record)

    @asynccontextmanager
    async def locked(
        self, owner_id: UUID, domain_id: UUID, id: UUID
    ) -> AsyncIterator[Conversation]:
        async with self.sessions.begin() as session:
            record = await session.scalar(
                select(ConversationRecord)
                .where(
                    ConversationRecord.id == id,
                    ConversationRecord.owner_id == owner_id,
                    ConversationRecord.domain_id == domain_id,
                    ConversationRecord.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if record is None:
                raise missing()
            rows = (
                await session.scalars(
                    select(ConversationTurnRecord)
                    .where(
                        ConversationTurnRecord.conversation_id == id,
                    )
                    .order_by(ConversationTurnRecord.sequence)
                )
            ).all()
            item = self._conversation(record)
            item.turns = [
                Turn(
                    row.id,
                    row.request_id,
                    row.sequence,
                    cast(TurnStatus, row.status),
                    row.query,
                    row.request,
                    row.request_digest,
                    row.scope_identity,
                    row.segment,
                    row.created_at,
                    row.updated_at,
                    row.response,
                    row.error_code,
                    [UUID(value) for value in row.dependencies],
                    row.execution_terminated,
                )
                for row in rows
            ]
            yield item
            record.title, record.revision = item.title, item.revision
            record.updated_at, record.deleted_at = item.updated_at, item.deleted_at
            by_id = {row.id: row for row in rows}
            for turn in item.turns:
                target = by_id.get(turn.id)
                if target is None:
                    target = ConversationTurnRecord(id=turn.id, conversation_id=id)
                    session.add(target)
                target.request_id, target.sequence = turn.request_id, turn.sequence
                target.status, target.query = turn.status, turn.query
                target.request, target.request_digest = turn.request, turn.request_digest
                target.scope_identity, target.segment = turn.scope_identity, turn.segment
                target.created_at, target.updated_at = turn.created_at, turn.updated_at
                target.response, target.error_code = turn.response, turn.error_code
                target.dependencies = [str(value) for value in turn.dependencies]
                target.execution_terminated = turn.execution_terminated
            if item.deleted_at is not None:
                await session.flush()
                await reconcile_deleted_attachments(session, record)

    @staticmethod
    def _conversation(record: ConversationRecord) -> Conversation:
        return Conversation(
            record.id,
            record.owner_id,
            record.domain_id,
            record.title,
            record.revision,
            record.created_at,
            record.updated_at,
            record.deleted_at,
        )
