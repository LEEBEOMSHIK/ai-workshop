"""Durable per-attempt claims; provider delivery is never automatically replayed."""

import asyncio
from contextlib import suppress
from time import perf_counter
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.config import Settings
from ai_workshop.labs.rag.evaluation.domain import load_evaluation_dataset
from ai_workshop.labs.rag.evaluation.generative import (
    ClaimCitation,
    GenerativeObservation,
    PrivateGenerativeResult,
)
from ai_workshop.labs.rag.evaluation.generative_access import FrozenEvaluationAccess
from ai_workshop.labs.rag.evaluation.generative_adapter import FrozenGenerativeAdapter
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_repository import GenerativeRepository
from ai_workshop.labs.rag.evaluation.models import EvaluationDatasetRecord
from ai_workshop.labs.rag.evaluation.service import (
    CandidateExecutionInput,
    CandidateIndexBuildSnapshot,
    capture_worker_runtime,
)
from ai_workshop.labs.rag.evaluation.tasks import ProductionEvaluationSearch
from ai_workshop.labs.rag.executions.domain import ExecutionIdentity, ExecutionOutcome
from ai_workshop.labs.rag.executions.observer import ExecutionObserver
from ai_workshop.labs.rag.executions.repository import SqlAlchemyExecutionRecorder
from ai_workshop.labs.rag.generation.codex_admin_api import CodexInputApprovalRequest
from ai_workshop.labs.rag.generation.codex_composition import codex_services
from ai_workshop.labs.rag.search.api import get_search_configuration_resolver, get_search_service
from ai_workshop.labs.rag.search.schemas import SearchResponse
from ai_workshop.shared.errors import AppError


def candidate_input(run: GenerativeRunRecord, version: UUID) -> CandidateExecutionInput:
    candidates = cast(list[dict[str, object]], run.snapshot["candidates"])
    item = next(c for c in candidates if c["configuration_version_id"] == str(version))
    snapshot = cast(dict[str, object], item["component_snapshot"])
    configuration = cast(dict[str, object], snapshot["configuration"])
    return CandidateExecutionInput(
        id=version,
        configuration_id=UUID(str(configuration["id"])),
        configuration_version_id=version,
        ordinal=candidates.index(item),
        index_builds=tuple(
            CandidateIndexBuildSnapshot(
                asset_version_id=UUID(str(b["asset_version_id"])),
                projection_id=UUID(str(b["projection_id"])),
                index_build_id=UUID(str(b["index_build_id"])),
                index_name=str(b["index_name"]),
                indexing_profile_id=UUID(str(b["indexing_profile_id"])),
                vector_dimension=int(cast(int, b["vector_dimension"])),
                index_uuid=str(b["index_uuid"]),
                mapping_version=int(cast(int, b["mapping_version"])),
                active_at_snapshot=bool(b["active_at_snapshot"]),
            )
            for b in cast(list[dict[str, object]], snapshot["index_builds"])
        ),
        workspace_ids=tuple(UUID(str(v)) for v in cast(list[str], configuration["workspace_ids"])),
        is_system=False,
        component_snapshot=snapshot,
        execution_snapshot=run.snapshot,
        retrieval_k=int(cast(int, run.snapshot.get("retrieval_k", 10))),
    )


class GenerativeWorkflow:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.sessions, self.settings = sessions, settings
        self.repository = GenerativeRepository(sessions)

    async def run(self, run_id: UUID) -> None:
        token = await self.repository.claim_run(
            run_id,
            capture_worker_runtime(environment=self.settings.environment),
        )
        if token is None:
            return
        heartbeat = asyncio.create_task(self._heartbeat(run_id, token))
        try:
            await self._execute_claimed(run_id, token)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat(self, run_id: UUID, token: UUID) -> None:
        while True:
            await asyncio.sleep(30)
            if not await self.repository.heartbeat(run_id, token):
                return

    async def _execute_claimed(self, run_id: UUID, token: UUID) -> None:
        async with self.sessions() as session:
            run = await session.get(GenerativeRunRecord, run_id)
            assert run is not None
            dataset_record = await session.get(EvaluationDatasetRecord, run.dataset_snapshot_id)
            assert dataset_record is not None
            dataset = load_evaluation_dataset(dataset_record.fixture_bytes)
            attempts = (
                await session.scalars(
                    select(GenerativeAttemptRecord.id)
                    .where(
                        GenerativeAttemptRecord.run_id == run_id,
                        GenerativeAttemptRecord.status == "pending",
                    )
                    .order_by(GenerativeAttemptRecord.created_at, GenerativeAttemptRecord.id)
                )
            ).all()
        for attempt_id in attempts:
            attempt = await self.repository.claim_attempt(attempt_id, token)
            if attempt is None:
                continue
            observer = ExecutionObserver(
                ExecutionIdentity(
                    actor_id=run.owner_id,
                    evaluation_attempt_id=attempt.id,
                    execution_id=attempt.execution_id,
                ),
                SqlAlchemyExecutionRecorder(self.sessions),
            )
            await observer.start()
            await observer.begin("request")
            started = perf_counter()
            error: str | None = None
            try:
                case = next(c for c in dataset.cases if c.id == attempt.case_id)
                candidate = candidate_input(run, attempt.configuration_version_id)
                frozen = ProductionEvaluationSearch(self.settings)
                try:
                    async with self.sessions() as session, codex_services(self.settings) as codex:
                        resolver = get_search_configuration_resolver(session, self.settings)
                        adapter = FrozenGenerativeAdapter(
                            frozen,
                            resolver,
                            FrozenEvaluationAccess(session),
                            input_approval=CodexInputApprovalRequest.model_validate(
                                run.input_approval,
                            )
                            if run.input_approval
                            else None,
                        )
                        prepared = await adapter.prepare(run.owner_id, candidate, case)
                        async for pipeline in get_search_service(
                            session, self.settings, resolver, codex
                        ):
                            output = await pipeline.execute(prepared, observer=observer)
                        cited = tuple(
                            dict.fromkeys(
                                id
                                for citation in output.generation.citations
                                for id in citation.evidence_ids
                            )
                        )
                        selected = tuple(item.evidence.id for item in output.grounding_evidence)
                        profile = prepared.configuration.generation_profile
                        requested = (
                            profile.deployment.provider_model_id
                            if profile and profile.deployment
                            else None
                        )
                        exposed = set(output.retrieved_evidence_ids) | set(selected) | set(cited)
                        leaks = exposed - case.permission_scenario.authorized_source_ids
                        observation = GenerativeObservation(
                            execution_id=attempt.execution_id,
                            retrieved_evidence_ids=output.retrieved_evidence_ids,
                            selected_evidence_ids=selected,
                            cited_evidence_ids=cited,
                            generation_status=output.generation.status.value,
                            citation_valid=(
                                bool(cited) and set(cited).issubset(selected)
                                if output.generation.status.value == "answered"
                                else None
                            ),
                            requested_model=requested,
                            observed_model=None,
                            access_exposures=tuple(sorted(leaks)),
                            duration_ms=(perf_counter() - started) * 1000,
                        )
                        result = PrivateGenerativeResult(
                            observation=observation,
                            answer=output.generation.text,
                            citations=tuple(
                                ClaimCitation(
                                    claim_index=c.claim_index, evidence_ids=c.evidence_ids
                                )
                                for c in output.generation.citations
                            ),
                            evidence=tuple(
                                e.model_dump(mode="json")
                                for e in SearchResponse.from_domain(output).grounding_evidence
                            ),
                        )
                finally:
                    await frozen.close()
            except Exception as exc:
                error = exc.code if isinstance(exc, AppError) else "evaluation_execution_failed"
                failed_stage = observer.active or observer.failed_stage or "request"
                exposed = set(observer.retrieved_evidence_ids) | set(observer.selected_evidence_ids)
                await observer.fail(error)
                result = PrivateGenerativeResult(
                    observation=GenerativeObservation(
                        execution_id=attempt.execution_id,
                        error_code=error,
                        failure_stage=failed_stage,
                        retrieved_evidence_ids=observer.retrieved_evidence_ids,
                        selected_evidence_ids=observer.selected_evidence_ids,
                        access_exposures=(
                            tuple(sorted(exposed - case.permission_scenario.authorized_source_ids))
                            if exposed
                            else ()
                        ),
                        duration_ms=(perf_counter() - started) * 1000,
                    )
                )
            await observer.begin("persistence")
            await self.repository.complete_attempt(attempt_id, token, result, error_code=error)
            await observer.end("persistence")
            await observer.finish(
                ExecutionOutcome(
                    state="failed" if error else "completed",
                    error_code=error,
                    answer_status=result.observation.generation_status,
                )
            )
        await self.repository.finish_run(run_id, token)
