import asyncio
from typing import cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import load_only

from ai_workshop.labs.rag.evaluation.generative import PrivateGenerativeResult
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_read import run_detail, visible_run
from ai_workshop.labs.rag.evaluation.generative_repository import unavailable
from ai_workshop.labs.rag.evaluation.generative_schemas import GenerativeRunView
from ai_workshop.labs.rag.executions.agent_trace import (
    TRACE_STORAGE_KEY,
    AgentTrace,
    read_agent_trace,
)
from ai_workshop.labs.rag.executions.domain import STAGES, ExecutionState, StageObservation
from ai_workshop.labs.rag.executions.execution_content import storage_stages
from ai_workshop.labs.rag.executions.history_selection import validate_history_binding
from ai_workshop.labs.rag.executions.models import ExecutionRecord
from ai_workshop.labs.rag.executions.read_repository import SqlAlchemyMonitoringRepository
from ai_workshop.labs.rag.executions.schemas import (
    ExecutionDetailResponse,
    ExecutionSummary,
    MonitoringGeneration,
)
from ai_workshop.labs.rag.search.schemas import EvidenceAnswerResponse, GeneratedCitationResponse
from ai_workshop.shared.errors import AppError


def _trace_allowed(trace: AgentTrace | None, snapshot: dict[str, object]) -> bool:
    if trace is None:
        return True
    try:
        allowed = {
            (UUID(str(source["document_id"])), UUID(str(source["asset_version_id"])),
             UUID(str(source["projection_id"])))
            for source in cast(list[dict[str, object]], snapshot.get("sources", []))
        }
    except (KeyError, TypeError, ValueError):
        return False
    return all(
        (source.document_id, source.asset_version_id, source.projection_id) in allowed
        for span in trace.spans for source in span.evidence_refs
    )


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
        views: dict[UUID, GenerativeRunView] = {}
        pending = iter(grouped)

        async def worker() -> None:
            # Request-local grouping only: run_detail rechecks the current owner and
            # source authority before and after reading the run. Never cache across requests.
            for run_id in pending:
                async with self.sessions() as session:
                    try:
                        views[run_id] = await run_detail(session, actor_id, run_id, list_only=True)
                    except AppError as exc:
                        if exc.code != "not_found":
                            raise

        # Only four tasks exist even for a large history. Every worker owns its session.
        workers = [asyncio.create_task(worker()) for _ in range(min(4, len(grouped)))]
        try:
            await asyncio.gather(*workers)
        except BaseException:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            raise

        result = []
        for run_id, executions in grouped.items():
            view = views.get(run_id)
            if view is None:
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
            statement = (
                select(ExecutionRecord, GenerativeAttemptRecord)
                .join(
                    GenerativeAttemptRecord,
                    GenerativeAttemptRecord.id == ExecutionRecord.evaluation_attempt_id,
                )
                .where(ExecutionRecord.id == execution_id, ExecutionRecord.actor_id == actor_id)
                .execution_options(populate_existing=True)
            )
            pair = (
                await session.execute(statement)
            ).one_or_none()
            if pair is None:
                raise unavailable()
            execution, attempt = pair
            run = await session.scalar(
                select(GenerativeRunRecord)
                .where(
                    GenerativeRunRecord.id == attempt.run_id,
                    GenerativeRunRecord.owner_id == actor_id,
                )
                .execution_options(populate_existing=True)
            )
            if run is None:
                raise unavailable()
            binding = (attempt.id, attempt.run_id, attempt.case_id,
                       attempt.configuration_version_id)
            view = await run_detail(session, actor_id, attempt.run_id)
            item = next((a for a in view.attempts if a.id == attempt.id), None)
            if item is None or item.execution_id != execution.id:
                raise unavailable()
            result = (
                PrivateGenerativeResult.model_validate(attempt.result) if attempt.result else None
            )
            trace_complete = execution.complete
            trace_invalid = False
            try:
                agent_trace = read_agent_trace(execution.stages)
            except ValidationError:
                agent_trace = None
                trace_complete = False
                trace_invalid = True
            try:
                safe_stages = storage_stages(
                    execution.stages if not trace_invalid else {
                        key: value for key, value in execution.stages.items()
                        if key != TRACE_STORAGE_KEY
                    }
                )
                if trace_invalid and any(
                    isinstance(value, dict) and value.get("contextualization") is not None
                    for value in safe_stages.values()
                ):
                    # The combined private boundary cannot be validated from a corrupt trace.
                    raise unavailable()
                stages = [
                    StageObservation.model_validate(safe_stages[name])
                    if name in safe_stages
                    else StageObservation(stage=name, state="unrecorded")
                    for name in STAGES
                ]
                for stage in stages:
                    validate_history_binding(stage.history_selection, ())
            except (ValueError, TypeError):
                raise unavailable() from None
            # Citations appear only after generation. Trace authority instead comes
            # from the frozen source manifest that run_detail currently authorizes.
            if not _trace_allowed(agent_trace, run.snapshot):
                raise unavailable()
            usage = await SqlAlchemyMonitoringRepository(self.sessions).usage(
                actor_id, execution_id,
            )
            fresh_pair = (await session.execute(statement)).one_or_none()
            if fresh_pair is None:
                raise unavailable()
            fresh_execution, fresh_attempt = fresh_pair
            if (
                fresh_execution.id != execution_id or fresh_execution.actor_id != actor_id
                or fresh_execution.evaluation_attempt_id != fresh_attempt.id
                or fresh_attempt.execution_id != execution_id
                or (fresh_attempt.id, fresh_attempt.run_id, fresh_attempt.case_id,
                    fresh_attempt.configuration_version_id) != binding
                or fresh_attempt.run_id != run.id
            ):
                raise unavailable()
            final_run = await session.scalar(
                select(GenerativeRunRecord)
                .where(GenerativeRunRecord.id == binding[1],
                       GenerativeRunRecord.owner_id == actor_id)
                .execution_options(populate_existing=True)
            )
            if (
                final_run is None or not _trace_allowed(agent_trace, final_run.snapshot)
                or not await visible_run(session, actor_id, final_run)
            ):
                raise unavailable()
            return ExecutionDetailResponse(
                agent_trace=agent_trace,
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
                observation_complete=trace_complete,
                configuration_version_id=attempt.configuration_version_id,
                stages=stages,
                generation=MonitoringGeneration(
                    status=result.observation.generation_status or "not_requested",
                    text=result.answer,
                    numeric_validation=result.numeric_validation,
                    citations=[
                        GeneratedCitationResponse(
                            claim_index=c.claim_index,
                            evidence_ids=list(c.evidence_ids),
                            claim_text=c.claim_text,
                            calculations=c.calculations,
                        )
                        for c in result.citations
                    ],
                )
                if result
                else None,
                evidence=[EvidenceAnswerResponse.model_validate(e) for e in result.evidence]
                if result
                else [],
                usage=usage,
                evaluation_run_id=attempt.run_id,
                evaluation_case_id=attempt.case_id,
            )
