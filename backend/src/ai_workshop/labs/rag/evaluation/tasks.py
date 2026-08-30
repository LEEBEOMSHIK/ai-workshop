from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from uuid import UUID

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.configurations.repository import (
    SqlAlchemySearchConfigurationResolver,
)
from ai_workshop.labs.rag.evaluation.domain import EvaluationCase
from ai_workshop.labs.rag.evaluation.metrics import (
    AccessExposure,
    BoundingBox,
    CharacterSpan,
    StableObservation,
)
from ai_workshop.labs.rag.evaluation.repository import SqlAlchemyEvaluationRepository
from ai_workshop.labs.rag.evaluation.service import (
    CandidateExecutionInput,
    EvaluationSearchPort,
    EvaluationWorkflow,
    SearchExecutionObservation,
)
from ai_workshop.labs.rag.highlighting.domain import AnswerStatus
from ai_workshop.labs.rag.highlighting.service import EvidenceSelector
from ai_workshop.labs.rag.retrieval.domain import ResolvedSearchScope
from ai_workshop.labs.rag.retrieval.elasticsearch import (
    ElasticsearchDenseRetriever,
    ElasticsearchSparseRetriever,
)
from ai_workshop.labs.rag.retrieval.scope import (
    SearchScopeResolver,
    SqlAlchemySearchScopeRepository,
)
from ai_workshop.labs.rag.retrieval.service import HybridRetrievalService
from ai_workshop.labs.rag.search.repository import SqlAlchemySearchSourceResolver
from ai_workshop.shared.db import create_engine, create_session_factory
from ai_workshop.shared.errors import AppError


@dataclass(frozen=True, slots=True)
class _ResolvedScope:
    value: ResolvedSearchScope

    async def resolve(
        self,
        *,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
    ) -> ResolvedSearchScope:
        del actor_id
        if (
            workspace_ids != self.value.workspace_ids
            or folder_ids != self.value.folder_ids
        ):
            raise RuntimeError("The resolved Evaluation Search scope changed.")
        return self.value


class ProductionEvaluationSearch(EvaluationSearchPort):
    """Executes exact configuration versions with DB-free model/ES boundaries."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = create_engine(settings)
        self.sessions = create_session_factory(self.engine)
        self.elasticsearch = create_elasticsearch(settings)

    async def close(self) -> None:
        await self.elasticsearch.close()
        await self.engine.dispose()

    async def execute(
        self,
        *,
        actor_id: UUID,
        candidate: CandidateExecutionInput,
        case: EvaluationCase,
    ) -> SearchExecutionObservation:
        evaluation_case = case
        started = perf_counter()
        async with self.sessions() as session:
            configuration = await SqlAlchemySearchConfigurationResolver(
                session, self.settings
            ).resolve_version(candidate.configuration_version_id, actor_id)
        scenario = evaluation_case.permission_scenario
        allowed_workspaces = (
            configuration.workspace_ids if candidate.is_system else candidate.workspace_ids
        )
        if not set(scenario.workspace_ids).issubset(allowed_workspaces):
            if (
                evaluation_case.expected_answer_status
                is AnswerStatus.INSUFFICIENT_EVIDENCE
                and not evaluation_case.expected_evidence_ids
            ):
                return _denied_observation(started)
            raise AppError("not_found", "The requested resource was not found.", 404)
        as_of = datetime.fromisoformat(scenario.as_of.replace("Z", "+00:00"))
        try:
            async with self.sessions() as session:
                scope = await SearchScopeResolver(
                    SqlAlchemySearchScopeRepository(session), now=lambda: as_of
                ).resolve(
                    actor_id=actor_id,
                    workspace_ids=scenario.workspace_ids,
                    folder_ids=scenario.folder_ids,
                )
        except AppError as exc:
            if (
                exc.code == "not_found"
                and evaluation_case.expected_answer_status
                is AnswerStatus.INSUFFICIENT_EVIDENCE
                and not evaluation_case.expected_evidence_ids
            ):
                return _denied_observation(started)
            raise
        hits = await HybridRetrievalService(
            scope_resolver=_ResolvedScope(scope),
            embedding=configuration.embedding,
            sparse_retriever=ElasticsearchSparseRetriever(self.elasticsearch),
            dense_retriever=ElasticsearchDenseRetriever(self.elasticsearch),
        ).search(
            actor_id=actor_id,
            query=evaluation_case.query,
            workspace_ids=scope.workspace_ids,
            folder_ids=scope.folder_ids,
            indexing_profile_id=configuration.indexing_profile_id,
            retrieval_profile=configuration.retrieval_profile,
            index_alias=configuration.active_index_alias,
            result_limit=10,
        )
        async with self.sessions() as session:
            sources = await SqlAlchemySearchSourceResolver(session).resolve(
                actor_id=actor_id,
                indexing_profile_id=configuration.indexing_profile_id,
                hits=hits,
            )
        policy = configuration.answer_policy
        if policy is None or configuration.answer_policy_version_id is None:
            raise AppError(
                "answer_policy_missing",
                "The selected search configuration has no answer policy version.",
                409,
            )
        selection = EvidenceSelector(configuration.embedding).select(
            query=evaluation_case.query.strip(),
            sources=sources,
            policy=policy,
        )
        answer = selection.answer
        conflicts = selection.conflicts
        selected = tuple(item for item in ((answer,) if answer else ()) + conflicts)
        selected_ids = {item.evidence.id for item in selected}
        related_ids = tuple(
            evidence.id
            for source in sources
            for evidence in source.chunk.evidence_units
            if evidence.id not in selected_ids
        )
        retrieved_ids = tuple(
            evidence.id for source in sources for evidence in source.chunk.evidence_units
        )
        highlights = tuple(item for selected_item in selected for item in selected_item.highlights)
        exposures: list[AccessExposure] = []
        for source in sources:
            for evidence in source.chunk.evidence_units:
                exposures.append(
                    AccessExposure(
                        "case_output",
                        evidence.id,
                    )
                )
        for selected_item in selected:
            surface = "answer" if selected_item is answer else "conflict"
            exposures.append(
                AccessExposure(
                    surface,
                    selected_item.evidence.id,
                )
            )
        exposures.extend(
            AccessExposure("related_source", evidence_id)
            for evidence_id in related_ids
        )
        exposures.extend(
            AccessExposure("highlight", item.evidence_unit_id)
            for item in highlights
        )
        return SearchExecutionObservation(
            stable=StableObservation(
                retrieved_evidence_ids=retrieved_ids,
                answer_status=selection.status,
                answer_evidence_ids=(answer.evidence.id,) if answer else (),
                conflict_evidence_ids=tuple(item.evidence.id for item in conflicts),
                related_evidence_ids=related_ids,
                highlight_kind=highlights[0].kind if highlights else None,
                highlight_spans=tuple(
                    CharacterSpan(item.char_start, item.char_end) for item in highlights
                ),
                highlight_bboxes=tuple(
                    BoundingBox(*item.bbox) for item in highlights if item.bbox is not None
                ),
            ),
            exposures=tuple(exposures),
            duration_ms=(perf_counter() - started) * 1000.0,
        )


def _denied_observation(started: float) -> SearchExecutionObservation:
    return SearchExecutionObservation(
        stable=StableObservation(
            retrieved_evidence_ids=(),
            answer_status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            answer_evidence_ids=(),
            conflict_evidence_ids=(),
            related_evidence_ids=(),
            highlight_kind=None,
            highlight_spans=(),
            highlight_bboxes=(),
        ),
        exposures=(),
        duration_ms=(perf_counter() - started) * 1000.0,
    )


class ClosingEvaluationWorkflow(EvaluationWorkflow):
    def __init__(
        self,
        repository: SqlAlchemyEvaluationRepository,
        search: ProductionEvaluationSearch,
        close_repository: Callable[[], Awaitable[None]],
    ) -> None:
        super().__init__(repository, search)
        self.production_search = search
        self.close_repository = close_repository

    async def run(self, run_id: UUID) -> None:
        try:
            await super().run(run_id)
        finally:
            await self.production_search.close()
            await self.close_repository()


def create_evaluation_workflow(settings: Settings) -> EvaluationWorkflow:
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    search = ProductionEvaluationSearch(settings)
    workflow = ClosingEvaluationWorkflow(
        SqlAlchemyEvaluationRepository(sessions),
        search,
        engine.dispose,
    )
    return workflow
