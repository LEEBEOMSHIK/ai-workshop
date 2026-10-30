from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.conversations.models import ConversationRecord, ConversationTurnRecord
from ai_workshop.labs.rag.executions.agent_trace import (
    TRACE_STORAGE_KEY,
    AgentTrace,
    next_agent_trace,
    read_agent_trace,
)
from ai_workshop.labs.rag.executions.domain import (
    STAGES,
    ExecutionIdentity,
    ExecutionOutcome,
    StageObservation,
)
from ai_workshop.labs.rag.executions.execution_content import storage_stages
from ai_workshop.labs.rag.executions.history_selection import validate_history_binding
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
            else:
                from ai_workshop.labs.rag.evaluation.generative_models import (
                    GenerativeAttemptRecord,
                    GenerativeRunRecord,
                )

                attempt = await session.scalar(
                    select(GenerativeAttemptRecord)
                    .join(
                        GenerativeRunRecord,
                        GenerativeRunRecord.id == GenerativeAttemptRecord.run_id,
                    )
                    .where(
                        GenerativeAttemptRecord.id == identity.evaluation_attempt_id,
                        GenerativeAttemptRecord.execution_id == identity.execution_id,
                        GenerativeAttemptRecord.status == "running",
                        GenerativeRunRecord.owner_id == identity.actor_id,
                        GenerativeRunRecord.status == "running",
                        GenerativeAttemptRecord.claim_token == GenerativeRunRecord.claim_token,
                    )
                    .with_for_update()
                )
                if attempt is None:
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
            if row.status != "running" and not await _can_close_terminal_persistence(
                session, row, observation,
            ):
                return
            previous = row.stages.get(observation.stage)
            if isinstance(previous, dict) and previous.get("state") in {
                "completed",
                "failed",
                "skipped",
            }:
                return
            if observation.history_selection is not None:
                parent = (
                    await session.get(ConversationTurnRecord, row.turn_id) if row.turn_id else None
                )
                validate_history_binding(
                    observation.history_selection,
                    tuple(UUID(str(value)) for value in parent.dependencies) if parent else (),
                )
            row.stages = storage_stages({
                **row.stages, observation.stage: observation.model_dump(mode="json"),
            })

    async def finish(self, execution_id: UUID, outcome: ExecutionOutcome) -> None:
        async with self.sessions.begin() as session:
            await finish_execution(session, execution_id, outcome)

    async def record_agent_trace(self, execution_id: UUID, trace: AgentTrace) -> None:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(ExecutionRecord).where(ExecutionRecord.id == execution_id).with_for_update()
            )
            if row is None:
                raise LookupError("Execution record unavailable")
            if row.status != "running":
                return
            value = next_agent_trace(row.stages.get(TRACE_STORAGE_KEY), trace)
            if value is not None:
                row.stages = storage_stages({**row.stages, TRACE_STORAGE_KEY: value})


async def _can_close_terminal_persistence(
    session: AsyncSession,
    row: ExecutionRecord,
    observation: StageObservation,
) -> bool:
    # The parent commit's trigger closes the execution before its persistence end
    # observation arrives. Only this already-started metadata operation may finish.
    previous = row.stages.get("persistence")
    if (
        row.status not in {"completed", "failed", "cancelled", "interrupted"}
        or (row.turn_id is None) == (row.evaluation_attempt_id is None)
        or observation.stage != "persistence"
        or observation.state != "completed"
        or not isinstance(previous, dict)
        or previous.get("state") != "running"
        or observation.started_at is None
        or observation.ended_at is None
        or observation.duration_ms is None
        or previous.get("started_at") != observation.model_dump(mode="json")["started_at"]
        or observation.ended_at < observation.started_at
        or observation.selection is not None
        or observation.history_selection is not None
        or observation.contextualization is not None
        or observation.operations not in (None, [])
    ):
        return False
    if row.turn_id is None:
        from ai_workshop.labs.rag.evaluation.generative_models import (
            GenerativeAttemptRecord,
            GenerativeRunRecord,
        )

        # Evaluation cancellation is only valid before an execution has started.
        if row.status == "cancelled":
            return False
        attempt = await session.scalar(
            select(GenerativeAttemptRecord)
            .join(GenerativeRunRecord, GenerativeRunRecord.id == GenerativeAttemptRecord.run_id)
            .where(
                GenerativeAttemptRecord.id == row.evaluation_attempt_id,
                GenerativeAttemptRecord.execution_id == row.id,
                GenerativeRunRecord.owner_id == row.actor_id,
            )
        )
        return attempt is not None and attempt.status == row.status
    parent = await session.scalar(
        select(ConversationTurnRecord)
        .join(ConversationRecord, ConversationRecord.id == ConversationTurnRecord.conversation_id)
        .where(
            ConversationTurnRecord.id == row.turn_id,
            ConversationRecord.owner_id == row.actor_id,
            ConversationRecord.deleted_at.is_(None),
        )
    )
    return parent is not None and parent.status == row.status


async def finish_execution(
    session: AsyncSession,
    execution_id: UUID,
    outcome: ExecutionOutcome,
) -> None:
    row = await session.scalar(
        select(ExecutionRecord).where(ExecutionRecord.id == execution_id).with_for_update()
    )
    if row is not None:
        try:
            storage_stages(row.stages)
            agent_trace = read_agent_trace(row.stages)
            trace_complete = agent_trace is None or (
                agent_trace.observation_complete and not agent_trace.truncated
                and all(span.state != "running" for span in agent_trace.spans)
            )
        except (ValidationError, ValueError, TypeError):
            trace_complete = False
        row.complete = outcome.complete and trace_complete and all(
            isinstance(value, dict) and value.get("state") in {"completed", "failed", "skipped"}
            for value in (row.stages.get(stage) for stage in STAGES)
        )
    if row is not None and row.status == "running":
        row.status, row.answer_status = outcome.state, outcome.answer_status
        row.error_code = outcome.error_code
        row.ended_at = datetime.now(UTC)
