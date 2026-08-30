from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.evaluation.domain import (
    EvaluationCase,
    EvaluationDataset,
    ExpectedHighlight,
    PermissionScenario,
)
from ai_workshop.labs.rag.evaluation.metrics import (
    CharacterSpan,
    StableObservation,
)
from ai_workshop.labs.rag.evaluation.service import (
    CandidateExecutionInput,
    CandidateIndexBuildSnapshot,
    CaseEvaluationResult,
    EvaluationRunClaim,
    EvaluationWorkflow,
    SearchExecutionObservation,
)
from ai_workshop.labs.rag.highlighting.domain import AnswerStatus, HighlightKind

E1 = UUID("00000000-0000-0000-0000-000000000001")
E2 = UUID("00000000-0000-0000-0000-000000000002")


def dataset() -> EvaluationDataset:
    scenario = PermissionScenario(
        name="caller-company",
        actor="caller",
        workspace_ids=(uuid4(),),
        folder_ids=(),
        authorized_source_ids=frozenset({E1, E2}),
        forbidden_source_ids=frozenset(),
        as_of="2026-08-31T00:00:00Z",
    )
    supported = EvaluationCase(
        id=uuid4(),
        kind="exact_code",
        query="A-17은 무엇인가?",
        query_sha256="1" * 64,
        permission_scenario=scenario,
        expected_answer_status=AnswerStatus.SUPPORTED,
        expected_evidence_ids=frozenset({E1}),
        expected_highlight=ExpectedHighlight(
            HighlightKind.KEYWORD,
            (CharacterSpan(0, 4),),
            (),
        ),
    )
    insufficient = EvaluationCase(
        id=uuid4(),
        kind="insufficient_evidence",
        query="없는 답은?",
        query_sha256="2" * 64,
        permission_scenario=scenario,
        expected_answer_status=AnswerStatus.INSUFFICIENT_EVIDENCE,
        expected_evidence_ids=frozenset(),
        expected_highlight=None,
    )
    return EvaluationDataset(
        id=uuid4(),
        name="small",
        version=1,
        fixture_bytes=b"{}",
        fixture_sha256="3" * 64,
        document_snapshot=({"asset_version_id": str(uuid4())},),
        document_snapshot_sha256="4" * 64,
        query_set_sha256="5" * 64,
        cases=(supported, insufficient),
    )


def stable(case: EvaluationCase) -> StableObservation:
    if case.expected_answer_status is AnswerStatus.SUPPORTED:
        return StableObservation(
            retrieved_evidence_ids=(E1, E2),
            answer_status=AnswerStatus.SUPPORTED,
            answer_evidence_ids=(E1,),
            conflict_evidence_ids=(),
            related_evidence_ids=(E2,),
            highlight_kind=HighlightKind.KEYWORD,
            highlight_spans=(CharacterSpan(0, 4),),
            highlight_bboxes=(),
        )
    return StableObservation(
        retrieved_evidence_ids=(E2,),
        answer_status=AnswerStatus.INSUFFICIENT_EVIDENCE,
        answer_evidence_ids=(),
        conflict_evidence_ids=(),
        related_evidence_ids=(E2,),
        highlight_kind=None,
        highlight_spans=(),
        highlight_bboxes=(),
    )


@dataclass
class MemoryRepository:
    claim: EvaluationRunClaim

    def __post_init__(self) -> None:
        self.running: list[UUID] = []
        self.case_results: list[tuple[UUID, CaseEvaluationResult]] = []
        self.completed: list[tuple[UUID, object]] = []
        self.failed: list[tuple[UUID, str]] = []
        self.run_completed: UUID | None = None

    async def claim_run(
        self, run_id: UUID, worker_runtime_environment: object
    ) -> EvaluationRunClaim | None:
        assert worker_runtime_environment
        return self.claim if run_id == self.claim.run_id else None

    async def heartbeat(self, run_id: UUID, claim_token: UUID) -> None:
        assert run_id == self.claim.run_id
        assert claim_token == self.claim.claim_token

    async def mark_candidate_running(self, candidate_id: UUID, claim_token: UUID) -> None:
        assert claim_token == self.claim.claim_token
        self.running.append(candidate_id)

    async def find_case_result(
        self, candidate_id: UUID, evaluation_case_id: UUID
    ) -> CaseEvaluationResult | None:
        return next(
            (
                item
                for stored_candidate, item in self.case_results
                if stored_candidate == candidate_id
                and item.evaluation_case_id == evaluation_case_id
            ),
            None,
        )

    async def add_case_result(
        self,
        candidate_id: UUID,
        claim_token: UUID,
        result: CaseEvaluationResult,
    ) -> None:
        assert claim_token == self.claim.claim_token
        self.case_results.append((candidate_id, result))

    async def complete_candidate(
        self, candidate_id: UUID, claim_token: UUID, metrics: object
    ) -> None:
        assert claim_token == self.claim.claim_token
        self.completed.append((candidate_id, metrics))

    async def fail_candidate(
        self, candidate_id: UUID, claim_token: UUID, failure: str
    ) -> None:
        assert claim_token == self.claim.claim_token
        self.failed.append((candidate_id, failure))

    async def complete_run(self, run_id: UUID, claim_token: UUID) -> None:
        assert claim_token == self.claim.claim_token
        self.run_completed = run_id

    async def fail_run(self, run_id: UUID, claim_token: UUID, failure: str) -> None:
        raise AssertionError(f"unexpected run failure: {run_id} {claim_token} {failure}")


class RecordingSearch:
    def __init__(self, failed_version_id: UUID) -> None:
        self.failed_version_id = failed_version_id
        self.calls: list[tuple[UUID, UUID]] = []
        self.durations = iter((10.0, 20.0, 30.0, 40.0))

    async def execute(
        self,
        *,
        actor_id: UUID,
        candidate: CandidateExecutionInput,
        case: EvaluationCase,
    ) -> SearchExecutionObservation:
        del actor_id
        self.calls.append((candidate.configuration_version_id, case.id))
        if candidate.configuration_version_id == self.failed_version_id:
            raise RuntimeError("dense branch unavailable")
        return SearchExecutionObservation(
            stable=stable(case),
            exposures=(),
            duration_ms=next(self.durations),
        )


class WorkerLossSearch:
    def __init__(self, interrupted_case_id: UUID) -> None:
        self.interrupted_case_id = interrupted_case_id
        self.interrupted = False
        self.calls: list[UUID] = []

    async def execute(
        self,
        *,
        actor_id: UUID,
        candidate: CandidateExecutionInput,
        case: EvaluationCase,
    ) -> SearchExecutionObservation:
        del actor_id, candidate
        self.calls.append(case.id)
        if case.id == self.interrupted_case_id and not self.interrupted:
            self.interrupted = True
            raise KeyboardInterrupt
        return SearchExecutionObservation(
            stable=stable(case),
            exposures=(),
            duration_ms=10.0,
        )


@pytest.mark.parametrize("duration_ms", [float("nan"), float("inf"), float("-inf")])
def test_search_observation_rejects_non_finite_duration(duration_ms: float) -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        SearchExecutionObservation(
            stable=stable(dataset().cases[0]),
            exposures=(),
            duration_ms=duration_ms,
        )


@pytest.mark.asyncio
async def test_stale_worker_resume_skips_durable_cases_without_duplicates() -> None:
    frozen_dataset = dataset()
    build = CandidateIndexBuildSnapshot(
        asset_version_id=uuid4(),
        projection_id=uuid4(),
        index_build_id=uuid4(),
        index_name="frozen-index",
        indexing_profile_id=uuid4(),
        vector_dimension=1024,
        active_at_snapshot=True,
    )
    candidate = CandidateExecutionInput(uuid4(), uuid4(), uuid4(), 0, (build,))
    claim = EvaluationRunClaim(
        run_id=uuid4(),
        claim_token=uuid4(),
        owner_id=uuid4(),
        dataset=frozen_dataset,
        metric_definition_version=1,
        retrieval_k=1,
        repetition_count=2,
        candidates=(candidate,),
    )
    repository = MemoryRepository(claim)
    search = WorkerLossSearch(frozen_dataset.cases[1].id)
    workflow = EvaluationWorkflow(repository, search)

    with pytest.raises(KeyboardInterrupt):
        await workflow.run(claim.run_id)
    assert [result.evaluation_case_id for _, result in repository.case_results] == [
        frozen_dataset.cases[0].id
    ]

    await workflow.run(claim.run_id)

    stored_ids = [result.evaluation_case_id for _, result in repository.case_results]
    assert stored_ids == [case.id for case in frozen_dataset.cases]
    assert len(stored_ids) == len(set(stored_ids))
    assert search.calls.count(frozen_dataset.cases[0].id) == 2
    assert search.calls.count(frozen_dataset.cases[1].id) == 3


@pytest.mark.asyncio
async def test_workflow_keeps_failed_candidate_and_completes_stable_comparison() -> None:
    run_id = uuid4()
    owner_id = uuid4()
    profile_id = uuid4()
    build = CandidateIndexBuildSnapshot(
        asset_version_id=uuid4(),
        projection_id=uuid4(),
        index_build_id=uuid4(),
        index_name="frozen-index",
        indexing_profile_id=profile_id,
        vector_dimension=1024,
        active_at_snapshot=True,
    )
    first = CandidateExecutionInput(uuid4(), uuid4(), uuid4(), 0, (build,))
    second = CandidateExecutionInput(uuid4(), uuid4(), uuid4(), 1, (build,))
    claim = EvaluationRunClaim(
        run_id=run_id,
        claim_token=uuid4(),
        owner_id=owner_id,
        dataset=dataset(),
        metric_definition_version=1,
        retrieval_k=1,
        repetition_count=2,
        candidates=(first, second),
    )
    repository = MemoryRepository(claim)
    search = RecordingSearch(second.configuration_version_id)

    await EvaluationWorkflow(repository, search).run(run_id)

    assert repository.running == [first.id, second.id]
    assert len(repository.case_results) == 2
    assert all(len(result.raw_observations) == 2 for _, result in repository.case_results)
    assert [item[0] for item in repository.completed] == [first.id]
    metrics = repository.completed[0][1]
    assert metrics.recall_at_k == 1.0
    assert metrics.mrr == 1.0
    assert metrics.ndcg == 1.0
    assert metrics.supported_precision == 1.0
    assert metrics.false_grounding_rate == 0.0
    assert metrics.highlight_iou == 1.0
    assert metrics.p50_latency_ms == 25.0
    assert metrics.p95_latency_ms == pytest.approx(38.5)
    assert metrics.access_leaks == 0
    assert metrics.reproducibility == 1.0
    assert repository.failed == [(second.id, "unexpected_error:RuntimeError")]
    assert repository.run_completed == run_id
    assert [call[0] for call in search.calls] == [
        first.configuration_version_id,
        first.configuration_version_id,
        first.configuration_version_id,
        first.configuration_version_id,
        second.configuration_version_id,
    ]
