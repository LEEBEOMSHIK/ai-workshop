from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.conversations.models import ConversationRecord, ConversationTurnRecord
from ai_workshop.labs.rag.executions.domain import (
    STAGES,
    ExecutionIdentity,
    ExecutionOutcome,
    StageObservation,
)
from ai_workshop.labs.rag.executions.models import ExecutionRecord


class SqlAlchemyExecutionRecorder:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def start(self, identity: ExecutionIdentity) -> None:
        async with self.sessions.begin() as session:
            if identity.turn_id is not None:
                turn = await session.scalar(
                    select(ConversationTurnRecord)
                    .join(
                        ConversationRecord,
                        ConversationRecord.id == ConversationTurnRecord.conversation_id,
                    )
                    .where(
                        ConversationTurnRecord.id == identity.turn_id,
                        ConversationRecord.owner_id == identity.actor_id,
                        ConversationRecord.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
                if turn is None or turn.status != "running":
                    raise LookupError("Execution parent unavailable")
            await session.execute(
                insert(ExecutionRecord)
                .values(
                    id=identity.execution_id,
                    actor_id=identity.actor_id,
                    turn_id=identity.turn_id,
                    evaluation_attempt_id=identity.evaluation_attempt_id,
                    status="running",
                    complete=False,
                    stages={},
                )
                .on_conflict_do_nothing()
            )

            if await session.get(ExecutionRecord, identity.execution_id) is None:
                raise ValueError("Execution parent already reserved")

    async def record(self, execution_id: UUID, observation: StageObservation) -> None:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(ExecutionRecord).where(ExecutionRecord.id == execution_id).with_for_update()
            )
            if row is None:
                raise LookupError("Execution record unavailable")
            previous = row.stages.get(observation.stage)
            if isinstance(previous, dict) and previous.get("state") in {
                "completed",
                "failed",
                "skipped",
            }:
                return
            row.stages = {**row.stages, observation.stage: observation.model_dump(mode="json")}

    async def finish(self, execution_id: UUID, outcome: ExecutionOutcome) -> None:
        async with self.sessions.begin() as session:
            await finish_execution(session, execution_id, outcome)


async def finish_execution(
    session: AsyncSession,
    execution_id: UUID,
    outcome: ExecutionOutcome,
) -> None:
    row = await session.scalar(
        select(ExecutionRecord).where(ExecutionRecord.id == execution_id).with_for_update()
    )
    if row is not None:
        row.complete = outcome.complete and all(
            isinstance(value, dict) and value.get("state") in {"completed", "failed", "skipped"}
            for value in (row.stages.get(stage) for stage in STAGES)
        )
    if row is not None and row.status == "running":
        row.status, row.answer_status = outcome.state, outcome.answer_status
        row.error_code, row.complete = outcome.error_code, outcome.complete
        row.ended_at = datetime.now(UTC)
