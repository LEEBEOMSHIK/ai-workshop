from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import load_only

from ai_workshop.labs.rag.evaluation.generative import PrivateGenerativeResult
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_read import run_detail
from ai_workshop.labs.rag.evaluation.generative_repository import unavailable
from ai_workshop.labs.rag.executions.domain import STAGES, ExecutionState, StageObservation
from ai_workshop.labs.rag.executions.models import ExecutionRecord
from ai_workshop.labs.rag.executions.read_repository import SqlAlchemyMonitoringRepository
from ai_workshop.labs.rag.executions.schemas import (
    ExecutionDetailResponse,
    ExecutionSummary,
    MonitoringGeneration,
)
from ai_workshop.labs.rag.search.schemas import EvidenceAnswerResponse, GeneratedCitationResponse
from ai_workshop.shared.errors import AppError


class GenerativeMonitoringReader:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def summaries(self, actor_id: UUID) -> list[ExecutionSummary]:
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(ExecutionRecord, GenerativeAttemptRecord.run_id)
                    .options(
                        load_only(
                            ExecutionRecord.id,
                            ExecutionRecord.evaluation_attempt_id,
                            ExecutionRecord.created_at,
                            ExecutionRecord.ended_at,
                            ExecutionRecord.status,
                            ExecutionRecord.complete,
                        )
                    )
                    .join(
                        GenerativeAttemptRecord,
                        GenerativeAttemptRecord.id == ExecutionRecord.evaluation_attempt_id,
                    )
                    .join(
                        GenerativeRunRecord,
                        GenerativeRunRecord.id == GenerativeAttemptRecord.run_id,
                    )
                    .where(
                        ExecutionRecord.actor_id == actor_id,
                        GenerativeRunRecord.owner_id == actor_id,
                    )
                )
            ).all()
        grouped: dict[UUID, list[ExecutionRecord]] = {}
        for execution, run_id in rows:
            grouped.setdefault(run_id, []).append(execution)
        result = []
        for run_id, executions in grouped.items():
            # Request-local grouping only: run_detail rechecks the current owner and
            # source authority before and after reading the run. Never cache across requests.
            async with self.sessions() as session:
                try:
                    view = await run_detail(session, actor_id, run_id)
                except AppError as exc:
                    if exc.code != "not_found":
                        raise
                    continue
            attempts = {item.id: item for item in view.attempts}
            for execution in executions:
                if execution.evaluation_attempt_id is None:
                    continue
                item = attempts.get(execution.evaluation_attempt_id)
                if item is None or item.execution_id != execution.id:
                    continue
                observation = item.observation
                result.append(
                    ExecutionSummary(
                        id=execution.id,
                        record_kind="execution",
                        kind="evaluation",
                        conversation_id=None,
                        turn_id=None,
                        domain_id=None,
                        domain_slug=None,
                        query=item.query,
                        created_at=execution.created_at,
                        status=cast(ExecutionState, execution.status),
                        answer_status=observation.generation_status if observation else None,
                        quality_status=item.metrics.correctness if item.metrics else "unreviewed",
                        failed_stage=observation.failure_stage if observation else None,
                        error_code=item.error_code,
                        duration_ms=(execution.ended_at - execution.created_at).total_seconds()
                        * 1000
                        if execution.ended_at
                        else None,
                        document_count=len({source.document_id for source in item.sources}),
                        observation_complete=execution.complete,
                        configuration_version_id=item.configuration_version_id,
                    )
                )
        return result

    async def detail(self, actor_id: UUID, execution_id: UUID) -> ExecutionDetailResponse:
        async with self.sessions() as session:
            pair = (
                await session.execute(
                    select(ExecutionRecord, GenerativeAttemptRecord)
                    .join(
                        GenerativeAttemptRecord,
                        GenerativeAttemptRecord.id == ExecutionRecord.evaluation_attempt_id,
                    )
                    .where(ExecutionRecord.id == execution_id, ExecutionRecord.actor_id == actor_id)
                )
            ).one_or_none()
            if pair is None:
                raise unavailable()
            execution, attempt = pair
            view = await run_detail(session, actor_id, attempt.run_id)
            item = next(a for a in view.attempts if a.id == attempt.id)
            result = (
                PrivateGenerativeResult.model_validate(attempt.result) if attempt.result else None
            )
            stages = [
                StageObservation.model_validate(execution.stages[name])
                if name in execution.stages
                else StageObservation(stage=name, state="unrecorded")
                for name in STAGES
            ]
            return ExecutionDetailResponse(
                id=execution.id,
                record_kind="execution",
                kind="evaluation",
                conversation_id=None,
                turn_id=None,
                domain_id=None,
                domain_slug=None,
                query=item.query,
                created_at=execution.created_at,
                status=execution.status,
                answer_status=result.observation.generation_status if result else None,
                quality_status=item.metrics.correctness if item.metrics else "unreviewed",
                failed_stage=result.observation.failure_stage if result else None,
                error_code=attempt.error_code,
                duration_ms=(execution.ended_at - execution.created_at).total_seconds() * 1000
                if execution.ended_at
                else None,
                document_count=len({source.document_id for source in item.sources}),
                observation_complete=execution.complete,
                configuration_version_id=attempt.configuration_version_id,
                stages=stages,
                generation=MonitoringGeneration(
                    status=result.observation.generation_status or "not_requested",
                    text=result.answer,
                    citations=[
                        GeneratedCitationResponse(
                            claim_index=c.claim_index, evidence_ids=list(c.evidence_ids)
                        )
                        for c in result.citations
                    ],
                )
                if result
                else None,
                evidence=[EvidenceAnswerResponse.model_validate(e) for e in result.evidence]
                if result
                else [],
                usage=await SqlAlchemyMonitoringRepository(self.sessions).usage(
                    actor_id, execution_id
                ),
                evaluation_run_id=attempt.run_id,
                evaluation_case_id=attempt.case_id,
            )
