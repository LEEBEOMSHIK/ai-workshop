from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.conversations.domain import Turn, TurnStatus
from ai_workshop.labs.rag.conversations.models import ConversationRecord, ConversationTurnRecord
from ai_workshop.labs.rag.domains.models import RagDomainRecord
from ai_workshop.labs.rag.executions.models import ExecutionRecord
from ai_workshop.labs.rag.executions.schemas import ExecutionUsage
from ai_workshop.labs.rag.generation.audit_models import GenerationExecutionAuditRecord


@dataclass
class MonitoringEntry:
    owner_id: UUID
    conversation_id: UUID
    domain_id: UUID
    domain_slug: str
    turn: Turn
    execution: ExecutionRecord | None


class MonitoringRepository(Protocol):
    async def usage(self, actor_id: UUID, execution_id: UUID) -> list[ExecutionUsage]: ...
    def entries(self, actor_id: UUID) -> AsyncIterator[MonitoringEntry]: ...
    async def find(
        self,
        actor_id: UUID,
        id: UUID,
        *,
        legacy: bool = False,
    ) -> MonitoringEntry | None: ...


class SqlAlchemyMonitoringRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def usage(self, actor_id: UUID, execution_id: UUID) -> list[ExecutionUsage]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(GenerationExecutionAuditRecord)
                    .where(
                        GenerationExecutionAuditRecord.execution_id == execution_id,
                        GenerationExecutionAuditRecord.actor_id == actor_id,
                    )
                    .order_by(GenerationExecutionAuditRecord.created_at)
                )
            ).all()
            return [
                ExecutionUsage(
                    requested_model=row.provider_model_id,
                    input_tokens=row.provider_reported_input_tokens,
                    output_tokens=row.provider_reported_output_tokens,
                    status=row.status,
                    error_code=row.safe_error_code,
                )
                for row in rows
            ]

    def entries(self, actor_id: UUID) -> AsyncIterator[MonitoringEntry]:
        return self._entries(actor_id)

    async def _entries(
        self, actor_id: UUID, id: UUID | None = None, *, legacy: bool = False
    ) -> AsyncIterator[MonitoringEntry]:
        async with self.sessions() as session:
            query = (
                select(
                    ConversationRecord,
                    ConversationTurnRecord,
                    RagDomainRecord.slug,
                    ExecutionRecord,
                )
                .join(
                    ConversationTurnRecord,
                    ConversationTurnRecord.conversation_id == ConversationRecord.id,
                )
                .join(RagDomainRecord, RagDomainRecord.id == ConversationRecord.domain_id)
                .outerjoin(
                    ExecutionRecord,
                    ExecutionRecord.turn_id == ConversationTurnRecord.id,
                )
                .where(
                    ConversationRecord.owner_id == actor_id, ConversationRecord.deleted_at.is_(None)
                )
            )
            if id is not None:
                query = query.where(
                    ConversationTurnRecord.id == id if legacy else ExecutionRecord.id == id
                )
            result = await session.stream(query.execution_options(yield_per=100))
            async for conversation, row, slug, execution in result:
                yield MonitoringEntry(
                    conversation.owner_id,
                    conversation.id,
                    conversation.domain_id,
                    slug,
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
                        [UUID(v) for v in row.dependencies],
                        row.execution_terminated,
                    ),
                    execution,
                )

    async def find(
        self,
        actor_id: UUID,
        id: UUID,
        *,
        legacy: bool = False,
    ) -> MonitoringEntry | None:
        async for entry in self._entries(actor_id, id, legacy=legacy):
            return entry
        return None
