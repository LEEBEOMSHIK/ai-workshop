from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_workshop.labs.rag.evaluation.domain import (
    CandidateStatus,
    EvaluationMetrics,
    EvaluationPolicy,
    EvaluationRunStatus,
)
from ai_workshop.labs.rag.evaluation.service import (
    CaseEvaluationResult,
    EvaluationCandidateView,
    EvaluationRunView,
)


def _rounded(value: float) -> float:
    return round(value, 6)


class EvaluationPolicyCreate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    dataset_snapshot_id: UUID
    metric_definition_version: Literal[1]
    retrieval_k: int = Field(ge=1, le=50)
    min_recall_at_k: float = Field(ge=0.0, le=1.0)
    min_mrr: float = Field(ge=0.0, le=1.0)
    min_ndcg: float = Field(ge=0.0, le=1.0)
    min_supported_precision: float = Field(ge=0.0, le=1.0)
    max_false_grounding_rate: float = Field(ge=0.0, le=1.0)
    min_highlight_iou: float = Field(ge=0.0, le=1.0)
    max_p50_latency_ms: float = Field(ge=0.0)
    max_p95_latency_ms: float = Field(ge=0.0)
    max_access_leaks: Literal[0]
    required_reproducibility: Annotated[float, Field(ge=1.0, le=1.0)]


class EvaluationPolicyResponse(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    id: UUID
    owner_id: UUID
    dataset_snapshot_id: UUID
    version: int
    metric_definition_version: Literal[1]
    retrieval_k: int
    min_recall_at_k: float
    min_mrr: float
    min_ndcg: float
    min_supported_precision: float
    max_false_grounding_rate: float
    min_highlight_iou: float
    max_p50_latency_ms: float
    max_p95_latency_ms: float
    max_access_leaks: Literal[0]
    required_reproducibility: float

    @classmethod
    def from_domain(cls, policy: EvaluationPolicy) -> Self:
        return cls(
            id=policy.id,
            owner_id=policy.owner_id,
            dataset_snapshot_id=policy.dataset_snapshot_id,
            version=policy.version,
            metric_definition_version=1,
            retrieval_k=policy.retrieval_k,
            min_recall_at_k=_rounded(policy.recall_at_k),
            min_mrr=_rounded(policy.mrr),
            min_ndcg=_rounded(policy.ndcg),
            min_supported_precision=_rounded(policy.supported_precision),
            max_false_grounding_rate=_rounded(policy.max_false_grounding_rate),
            min_highlight_iou=_rounded(policy.min_highlight_iou),
            max_p50_latency_ms=_rounded(policy.max_p50_latency_ms),
            max_p95_latency_ms=_rounded(policy.max_p95_latency_ms),
            max_access_leaks=0,
            required_reproducibility=1.0,
        )


class EvaluationRunCreate(BaseModel):
    dataset_fixture: dict[str, object] | None = None
    dataset_snapshot_id: UUID | None = None
    evaluation_policy_version_id: UUID | None = None
    configuration_version_ids: list[UUID] = Field(
        default_factory=list,
        description=(
            "Additional exact Saved Configuration Versions; the automatic system BM25 "
            "baseline is always included first."
        ),
    )
    metric_definition_version: Literal[1]
    retrieval_k: int = Field(ge=1, le=50)
    repetition_count: int = Field(default=2, ge=2, le=5)

    @model_validator(mode="after")
    def one_dataset_source(self) -> Self:
        if (self.dataset_fixture is None) == (self.dataset_snapshot_id is None):
            raise ValueError("Exactly one immutable dataset source is required.")
        if len(self.configuration_version_ids) != len(set(self.configuration_version_ids)):
            raise ValueError("Evaluation candidates must be unique.")
        return self


class EvaluationMetricsResponse(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    recall_at_k: float
    mrr: float
    ndcg: float
    supported_precision: float
    false_grounding_rate: float
    highlight_iou: float
    p50_latency_ms: float
    p95_latency_ms: float
    access_leaks: int
    reproducibility: float

    @classmethod
    def from_domain(cls, metrics: EvaluationMetrics) -> Self:
        return cls(
            recall_at_k=_rounded(metrics.recall_at_k),
            mrr=_rounded(metrics.mrr),
            ndcg=_rounded(metrics.ndcg),
            supported_precision=_rounded(metrics.supported_precision),
            false_grounding_rate=_rounded(metrics.false_grounding_rate),
            highlight_iou=_rounded(metrics.highlight_iou),
            p50_latency_ms=_rounded(metrics.p50_latency_ms),
            p95_latency_ms=_rounded(metrics.p95_latency_ms),
            access_leaks=metrics.access_leaks,
            reproducibility=_rounded(metrics.reproducibility),
        )


class EvaluationCaseResponse(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    evaluation_case_id: UUID
    ordinal: int
    query_sha256: str
    expected_evidence_ids: list[UUID]
    duration_ms: float
    recall_at_k: float | None
    reciprocal_rank: float | None
    ndcg: float | None
    correct_supported: bool | None
    false_grounding: bool | None
    highlight_iou: float | None
    access_leaks: int
    reproducible: bool
    raw_observations: list[dict[str, object]]

    @classmethod
    def from_domain(cls, result: CaseEvaluationResult) -> Self:
        raw: list[dict[str, object]] = []
        for observation in result.raw_observations:
            stable = observation.stable
            raw.append(
                {
                    "retrieved_evidence_ids": [
                        str(item) for item in stable.retrieved_evidence_ids
                    ],
                    "answer_status": stable.answer_status.value,
                    "answer_evidence_ids": [str(item) for item in stable.answer_evidence_ids],
                    "conflict_evidence_ids": [
                        str(item) for item in stable.conflict_evidence_ids
                    ],
                    "related_evidence_ids": [
                        str(item) for item in stable.related_evidence_ids
                    ],
                    "highlight_kind": (
                        stable.highlight_kind.value if stable.highlight_kind else None
                    ),
                    "highlight_spans": [
                        [item.start, item.end] for item in stable.highlight_spans
                    ],
                    "highlight_bboxes": [
                        [item.x0, item.y0, item.x1, item.y1]
                        for item in stable.highlight_bboxes
                    ],
                    "highlights": [
                        {
                            "surface": item.surface,
                            "document_id": str(item.document_id),
                            "asset_version_id": str(item.asset_version_id),
                            "evidence_unit_id": str(item.evidence_unit_id),
                            "page": item.page,
                            "kind": item.kind.value,
                            "spans": [[span.start, span.end] for span in item.spans],
                            "bboxes": [
                                [box.x0, box.y0, box.x1, box.y1]
                                for box in item.bboxes
                            ],
                        }
                        for item in stable.highlights
                    ],
                    "exposures": [
                        {
                            "surface": item.surface,
                            "source_id": str(item.source_id),
                        }
                        for item in observation.exposures
                    ],
                    "duration_ms": _rounded(observation.duration_ms),
                }
            )
        return cls(
            evaluation_case_id=result.evaluation_case_id,
            ordinal=result.ordinal,
            query_sha256=result.query_sha256,
            expected_evidence_ids=sorted(result.expected_evidence_ids),
            duration_ms=_rounded(result.duration_ms),
            recall_at_k=(
                _rounded(result.recall_at_k) if result.recall_at_k is not None else None
            ),
            reciprocal_rank=(
                _rounded(result.reciprocal_rank)
                if result.reciprocal_rank is not None
                else None
            ),
            ndcg=_rounded(result.ndcg) if result.ndcg is not None else None,
            correct_supported=result.correct_supported,
            false_grounding=result.false_grounding,
            highlight_iou=(
                _rounded(result.highlight_iou)
                if result.highlight_iou is not None
                else None
            ),
            access_leaks=result.access_leaks,
            reproducible=result.reproducible,
            raw_observations=raw,
        )


class EvaluationCandidateResponse(BaseModel):
    id: UUID
    configuration_version_id: UUID
    ordinal: int
    status: CandidateStatus
    failure: str | None
    metrics: EvaluationMetricsResponse | None
    case_results: list[EvaluationCaseResponse]

    @classmethod
    def from_domain(cls, candidate: EvaluationCandidateView) -> Self:
        return cls(
            id=candidate.id,
            configuration_version_id=candidate.configuration_version_id,
            ordinal=candidate.ordinal,
            status=candidate.status,
            failure=candidate.failure,
            metrics=(
                EvaluationMetricsResponse.from_domain(candidate.metrics)
                if candidate.metrics is not None
                else None
            ),
            case_results=[
                EvaluationCaseResponse.from_domain(item)
                for item in candidate.case_results
            ],
        )


class EvaluationRunResponse(BaseModel):
    id: UUID
    owner_id: UUID
    dataset_snapshot_id: UUID
    evaluation_policy_version_id: UUID | None
    status: EvaluationRunStatus
    fixture_sha256: str
    document_snapshot_sha256: str
    query_set_sha256: str
    execution_snapshot_sha256: str
    runtime_environment: dict[str, object]
    worker_runtime_environment: dict[str, object] | None
    metric_definition_version: Literal[1]
    retrieval_k: int
    repetition_count: int
    failure: str | None
    candidates: list[EvaluationCandidateResponse]

    @classmethod
    def from_domain(cls, run: EvaluationRunView) -> Self:
        return cls(
            id=run.id,
            owner_id=run.owner_id,
            dataset_snapshot_id=run.dataset_snapshot_id,
            evaluation_policy_version_id=run.evaluation_policy_version_id,
            status=run.status,
            fixture_sha256=run.fixture_sha256,
            document_snapshot_sha256=run.document_snapshot_sha256,
            query_set_sha256=run.query_set_sha256,
            execution_snapshot_sha256=run.execution_snapshot_sha256,
            runtime_environment=dict(run.runtime_environment),
            worker_runtime_environment=(
                dict(run.worker_runtime_environment)
                if run.worker_runtime_environment is not None
                else None
            ),
            metric_definition_version=1,
            retrieval_k=run.retrieval_k,
            repetition_count=run.repetition_count,
            failure=run.failure,
            candidates=[
                EvaluationCandidateResponse.from_domain(item) for item in run.candidates
            ],
        )
