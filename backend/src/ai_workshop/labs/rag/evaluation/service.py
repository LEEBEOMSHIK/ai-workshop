import json
import math
import os
import platform
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Protocol
from uuid import UUID

from ai_workshop.labs.rag.configurations.domain import (
    BM25_BASELINE_CONFIGURATION_VERSION_ID,
)
from ai_workshop.labs.rag.evaluation.domain import (
    CandidateStatus,
    EvaluationCase,
    EvaluationDataset,
    EvaluationMetrics,
    EvaluationPolicy,
    EvaluationRunStatus,
    load_evaluation_dataset,
)
from ai_workshop.labs.rag.evaluation.metrics import (
    AccessExposure,
    AnswerObservation,
    StableObservation,
    bbox_set_iou,
    count_access_leaks,
    false_grounding_rate,
    ndcg_at_k,
    percentile,
    recall_at_k,
    reciprocal_rank,
    reproducibility_rate,
    span_iou,
    structured_highlight_iou,
    supported_precision,
)


@dataclass(frozen=True, slots=True)
class CandidateIndexBuildSnapshot:
    asset_version_id: UUID
    projection_id: UUID
    index_build_id: UUID
    index_name: str
    indexing_profile_id: UUID
    vector_dimension: int
    active_at_snapshot: bool

    def __post_init__(self) -> None:
        if not self.index_name.strip():
            raise ValueError("An Evaluation candidate requires a concrete index name.")
        if self.vector_dimension < 1:
            raise ValueError("An Evaluation candidate requires a positive dimension.")


@dataclass(frozen=True, slots=True)
class CandidateExecutionInput:
    id: UUID
    configuration_id: UUID
    configuration_version_id: UUID
    ordinal: int
    index_builds: tuple[CandidateIndexBuildSnapshot, ...]
    retrieval_k: int = 10
    workspace_ids: tuple[UUID, ...] = ()
    is_system: bool = False
    component_snapshot: Mapping[str, object] | None = None
    execution_snapshot: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.index_builds:
            raise ValueError("An Evaluation candidate requires an immutable index manifest.")
        profile_ids = {item.indexing_profile_id for item in self.index_builds}
        dimensions = {item.vector_dimension for item in self.index_builds}
        if len(profile_ids) != 1 or len(dimensions) != 1:
            raise ValueError("An Evaluation candidate index manifest must be compatible.")
        if not 1 <= self.retrieval_k <= 50:
            raise ValueError("An Evaluation candidate requires a supported retrieval K.")


@dataclass(frozen=True, slots=True)
class EvaluationRunClaim:
    run_id: UUID
    claim_token: UUID
    owner_id: UUID
    dataset: EvaluationDataset
    metric_definition_version: int
    retrieval_k: int
    repetition_count: int
    candidates: tuple[CandidateExecutionInput, ...]


@dataclass(frozen=True, slots=True)
class SearchExecutionObservation:
    stable: StableObservation
    exposures: tuple[AccessExposure, ...]
    duration_ms: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.duration_ms) or self.duration_ms < 0:
            raise ValueError("Search duration must be finite and non-negative.")


@dataclass(frozen=True, slots=True)
class CaseEvaluationResult:
    evaluation_case_id: UUID
    ordinal: int
    query_sha256: str
    permission_scenario: object
    expected_evidence_ids: frozenset[UUID]
    raw_observations: tuple[SearchExecutionObservation, ...]
    duration_ms: float
    recall_at_k: float | None
    reciprocal_rank: float | None
    ndcg: float | None
    correct_supported: bool | None
    false_grounding: bool | None
    highlight_iou: float | None
    access_leaks: int
    reproducible: bool


@dataclass(frozen=True, slots=True)
class EvaluationCandidateView:
    id: UUID
    configuration_version_id: UUID
    ordinal: int
    status: CandidateStatus
    failure: str | None
    metrics: EvaluationMetrics | None
    case_results: tuple[CaseEvaluationResult, ...]


@dataclass(frozen=True, slots=True)
class EvaluationRunView:
    id: UUID
    owner_id: UUID
    dataset_snapshot_id: UUID
    evaluation_policy_version_id: UUID | None
    status: EvaluationRunStatus
    fixture_sha256: str
    document_snapshot_sha256: str
    query_set_sha256: str
    execution_snapshot_sha256: str
    runtime_environment: Mapping[str, object]
    worker_runtime_environment: Mapping[str, object] | None
    metric_definition_version: int
    retrieval_k: int
    repetition_count: int
    failure: str | None
    candidates: tuple[EvaluationCandidateView, ...]


class EvaluationApplicationRepositoryPort(Protocol):
    async def add_or_get_dataset(
        self, actor_id: UUID, dataset: EvaluationDataset
    ) -> EvaluationDataset: ...

    async def find_dataset_visible(
        self, dataset_snapshot_id: UUID, actor_id: UUID
    ) -> EvaluationDataset | None: ...

    async def add_policy(
        self, actor_id: UUID, policy: EvaluationPolicy
    ) -> EvaluationPolicy: ...

    async def next_policy_version(
        self, actor_id: UUID, dataset_snapshot_id: UUID
    ) -> int: ...

    async def create_run(
        self,
        *,
        actor_id: UUID,
        dataset: EvaluationDataset,
        evaluation_policy_version_id: UUID | None,
        configuration_version_ids: tuple[UUID, ...],
        metric_definition_version: int,
        retrieval_k: int,
        repetition_count: int,
        runtime_environment: Mapping[str, object],
    ) -> EvaluationRunView: ...

    async def detail_visible(
        self, run_id: UUID, actor_id: UUID
    ) -> EvaluationRunView | None: ...

    async def list_visible(
        self, actor_id: UUID, limit: int
    ) -> tuple[EvaluationRunView, ...]: ...


async def _no_op_commit() -> None:
    return None


def _application_source_sha256() -> str:
    package_root = Path(__file__).resolve().parents[3]
    digest = sha256()
    for source in sorted(package_root.rglob("*.py")):
        digest.update(source.relative_to(package_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(source.read_bytes())
    return digest.hexdigest()


def _capture_model_runtime() -> dict[str, object]:
    captured: dict[str, object] = {
        "configured_device": os.environ.get("AI_WORKSHOP_MODEL_DEVICE", "cpu"),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "cuda_runtime": None,
        "cudnn_runtime": None,
        "cuda_available": False,
        "cuda_device_count": 0,
    }
    try:
        torch = import_module("torch")
        cuda = torch.cuda
        captured["torch_runtime"] = str(torch.__version__)
        captured["cuda_runtime"] = getattr(torch.version, "cuda", None)
        captured["cudnn_runtime"] = torch.backends.cudnn.version()
        captured["cuda_available"] = bool(cuda.is_available())
        captured["cuda_device_count"] = int(cuda.device_count())
        if captured["cuda_available"]:
            device_index = int(cuda.current_device())
            captured["active_cuda_device"] = device_index
            captured["active_cuda_device_name"] = str(
                cuda.get_device_name(device_index)
            )
            captured["active_cuda_device_capability"] = [
                int(value) for value in cuda.get_device_capability(device_index)
            ]
    except (ImportError, OSError, RuntimeError, AttributeError) as exc:
        captured["torch_runtime_error"] = type(exc).__name__
    return captured


def capture_worker_runtime(*, environment: str) -> dict[str, object]:
    packages: dict[str, str] = {}
    for package in (
        "celery",
        "elasticsearch",
        "fastapi",
        "numpy",
        "sentence-transformers",
        "sqlalchemy",
        "tokenizers",
        "torch",
        "transformers",
    ):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = "unavailable"
    revision = os.environ.get("AI_WORKSHOP_BUILD_REVISION")
    if not revision and environment not in {"local", "test"}:
        raise RuntimeError("A non-development evaluation worker requires a build revision.")
    source_sha256 = _application_source_sha256()
    if not revision:
        revision = f"source-sha256:{source_sha256}"
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": sys.platform,
        "application": "ai-workshop",
        "application_revision": revision,
        "application_source_sha256": source_sha256,
        "execution_role": "celery-worker",
        "device": os.environ.get("AI_WORKSHOP_MODEL_DEVICE", "cpu"),
        "model_cache_root": os.environ.get("AI_WORKSHOP_MODEL_CACHE_ROOT"),
        "packages": packages,
        "model_runtime": _capture_model_runtime(),
    }


def normalize_evaluation_candidates(
    configuration_version_ids: tuple[UUID, ...],
) -> tuple[UUID, ...]:
    if len(configuration_version_ids) != len(set(configuration_version_ids)):
        raise ValueError("Evaluation candidates must be unique.")
    return (
        BM25_BASELINE_CONFIGURATION_VERSION_ID,
        *(
            item
            for item in configuration_version_ids
            if item != BM25_BASELINE_CONFIGURATION_VERSION_ID
        ),
    )


class EvaluationApplicationService:
    def __init__(
        self,
        repository: EvaluationApplicationRepositoryPort,
        *,
        commit: Callable[[], Awaitable[None]] = _no_op_commit,
    ) -> None:
        self.application_repository = repository
        self.commit = commit

    async def create_policy(
        self,
        *,
        actor_id: UUID,
        dataset_snapshot_id: UUID,
        metric_definition_version: int,
        retrieval_k: int,
        min_recall_at_k: float,
        min_mrr: float,
        min_ndcg: float,
        min_supported_precision: float,
        max_false_grounding_rate: float,
        min_highlight_iou: float,
        max_p50_latency_ms: float,
        max_p95_latency_ms: float,
        max_access_leaks: int,
        required_reproducibility: float,
    ) -> EvaluationPolicy:
        dataset = await self.application_repository.find_dataset_visible(
            dataset_snapshot_id, actor_id
        )
        if dataset is None:
            from ai_workshop.shared.errors import AppError

            raise AppError("not_found", "The requested resource was not found.", 404)
        policy = EvaluationPolicy.create(
            owner_id=actor_id,
            dataset_snapshot_id=dataset.id,
            version=await self.application_repository.next_policy_version(
                actor_id, dataset.id
            ),
            metric_definition_version=metric_definition_version,
            retrieval_k=retrieval_k,
            recall_at_k=min_recall_at_k,
            mrr=min_mrr,
            ndcg=min_ndcg,
            supported_precision=min_supported_precision,
            max_false_grounding_rate=max_false_grounding_rate,
            min_highlight_iou=min_highlight_iou,
            max_p50_latency_ms=max_p50_latency_ms,
            max_p95_latency_ms=max_p95_latency_ms,
            max_access_leaks=max_access_leaks,
            required_reproducibility=required_reproducibility,
        )
        saved = await self.application_repository.add_policy(actor_id, policy)
        await self.commit()
        return saved

    async def start_run(
        self,
        *,
        actor_id: UUID,
        dataset_fixture: Mapping[str, object] | None,
        dataset_snapshot_id: UUID | None,
        evaluation_policy_version_id: UUID | None,
        configuration_version_ids: tuple[UUID, ...],
        metric_definition_version: int,
        retrieval_k: int,
        repetition_count: int,
    ) -> EvaluationRunView:
        dataset: EvaluationDataset
        if dataset_fixture is not None:
            canonical = json.dumps(
                dataset_fixture,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            dataset = await self.application_repository.add_or_get_dataset(
                actor_id, load_evaluation_dataset(canonical)
            )
        elif dataset_snapshot_id is not None:
            visible_dataset = await self.application_repository.find_dataset_visible(
                dataset_snapshot_id, actor_id
            )
            if visible_dataset is None:
                from ai_workshop.shared.errors import AppError

                raise AppError("not_found", "The requested resource was not found.", 404)
            dataset = visible_dataset
        else:
            raise ValueError("An Evaluation Run requires one immutable dataset snapshot.")
        normalized_candidates = normalize_evaluation_candidates(
            configuration_version_ids
        )
        runtime: dict[str, object] = {"capture": "celery-worker-start"}
        run = await self.application_repository.create_run(
            actor_id=actor_id,
            dataset=dataset,
            evaluation_policy_version_id=evaluation_policy_version_id,
            configuration_version_ids=normalized_candidates,
            metric_definition_version=metric_definition_version,
            retrieval_k=retrieval_k,
            repetition_count=repetition_count,
            runtime_environment=runtime,
        )
        await self.commit()
        return run

    async def detail(self, run_id: UUID, actor_id: UUID) -> EvaluationRunView:
        run = await self.application_repository.detail_visible(run_id, actor_id)
        if run is None:
            from ai_workshop.shared.errors import AppError

            raise AppError("not_found", "The requested resource was not found.", 404)
        return run

    async def list(self, actor_id: UUID, limit: int) -> tuple[EvaluationRunView, ...]:
        return await self.application_repository.list_visible(actor_id, limit)


class EvaluationRepositoryPort(Protocol):
    async def claim_run(
        self, run_id: UUID, worker_runtime_environment: Mapping[str, object]
    ) -> EvaluationRunClaim | None: ...

    async def heartbeat(self, run_id: UUID, claim_token: UUID) -> None: ...

    async def mark_candidate_running(
        self, candidate_id: UUID, claim_token: UUID
    ) -> None: ...

    async def find_case_result(
        self, candidate_id: UUID, evaluation_case_id: UUID
    ) -> CaseEvaluationResult | None: ...

    async def add_case_result(
        self,
        candidate_id: UUID,
        claim_token: UUID,
        result: CaseEvaluationResult,
    ) -> None: ...

    async def complete_candidate(
        self,
        candidate_id: UUID,
        claim_token: UUID,
        metrics: EvaluationMetrics,
    ) -> None: ...

    async def fail_candidate(
        self,
        candidate_id: UUID,
        claim_token: UUID,
        failure: str,
    ) -> None: ...

    async def complete_run(self, run_id: UUID, claim_token: UUID) -> None: ...

    async def fail_run(
        self,
        run_id: UUID,
        claim_token: UUID,
        failure: str,
    ) -> None: ...


class EvaluationSearchPort(Protocol):
    async def execute(
        self,
        *,
        actor_id: UUID,
        candidate: CandidateExecutionInput,
        case: EvaluationCase,
    ) -> SearchExecutionObservation: ...


class EvaluationMetricMissingError(ValueError):
    pass


def _safe_failure(exc: Exception) -> str:
    from ai_workshop.shared.errors import AppError

    if isinstance(exc, AppError):
        return f"application_error:{exc.code}"
    return f"unexpected_error:{type(exc).__name__}"


def _mean(values: Sequence[float | None], name: str) -> float:
    measured = tuple(value for value in values if value is not None)
    if not measured:
        raise EvaluationMetricMissingError(f"Required evaluation metric is missing: {name}")
    return sum(measured) / len(measured)


def _answer_observation(
    case: EvaluationCase,
    observation: StableObservation,
) -> AnswerObservation:
    return AnswerObservation(
        expected_status=case.expected_answer_status,
        actual_status=observation.answer_status,
        expected_evidence_ids=case.expected_evidence_ids,
        answer_evidence_ids=observation.answer_evidence_ids,
    )


def _highlight_iou(
    case: EvaluationCase,
    observation: StableObservation,
) -> float | None:
    expected = case.expected_highlight
    if expected is None:
        return None
    structured_expected = expected.as_observation()
    if structured_expected is not None:
        return structured_highlight_iou(structured_expected, observation.highlights)
    if expected.spans:
        return span_iou(expected=expected.spans, actual=observation.highlight_spans)
    if not expected.bboxes:
        return None
    return bbox_set_iou(
        expected=expected.bboxes,
        actual=observation.highlight_bboxes,
    )


def evaluate_case(
    case: EvaluationCase,
    ordinal: int,
    observations: Sequence[SearchExecutionObservation],
    *,
    retrieval_k: int = 10,
) -> CaseEvaluationResult:
    if not observations:
        raise EvaluationMetricMissingError("A case requires raw search observations.")
    first = observations[0].stable
    answer = _answer_observation(case, first)
    precision = supported_precision((answer,))
    grounding = false_grounding_rate((answer,))
    return CaseEvaluationResult(
        evaluation_case_id=case.id,
        ordinal=ordinal,
        query_sha256=case.query_sha256,
        permission_scenario=case.permission_scenario,
        expected_evidence_ids=case.expected_evidence_ids,
        raw_observations=tuple(observations),
        duration_ms=sum(item.duration_ms for item in observations),
        recall_at_k=recall_at_k(
            first.retrieved_evidence_ids,
            case.expected_evidence_ids,
            k=retrieval_k,
        ),
        reciprocal_rank=reciprocal_rank(
            first.retrieved_evidence_ids,
            case.expected_evidence_ids,
        ),
        ndcg=ndcg_at_k(
            first.retrieved_evidence_ids,
            case.expected_evidence_ids,
            k=retrieval_k,
        ),
        correct_supported=(precision == 1.0 if precision is not None else None),
        false_grounding=(grounding == 1.0 if grounding is not None else None),
        highlight_iou=_highlight_iou(case, first),
        access_leaks=sum(
            count_access_leaks(
                item.exposures,
                authorized_source_ids=(
                    case.permission_scenario.authorized_source_ids
                ),
                forbidden_source_ids=case.permission_scenario.forbidden_source_ids,
            )
            for item in observations
        ),
        reproducible=(
            reproducibility_rate((tuple(item.stable for item in observations),)) == 1.0
        ),
    )


def aggregate_metrics(
    dataset: EvaluationDataset,
    results: Sequence[CaseEvaluationResult],
) -> EvaluationMetrics:
    by_case = {result.evaluation_case_id: result for result in results}
    if len(by_case) != len(dataset.cases) or any(
        case.id not in by_case for case in dataset.cases
    ):
        raise EvaluationMetricMissingError("Every frozen evaluation case must be present.")
    ordered = tuple(by_case[case.id] for case in dataset.cases)
    answers = tuple(
        _answer_observation(case, by_case[case.id].raw_observations[0].stable)
        for case in dataset.cases
    )
    precision = supported_precision(answers)
    grounding = false_grounding_rate(answers)
    reproducibility = reproducibility_rate(
        tuple(
            tuple(item.stable for item in result.raw_observations)
            for result in ordered
        )
    )
    if precision is None or grounding is None or reproducibility is None:
        raise EvaluationMetricMissingError("A required answer metric is missing.")
    latencies = tuple(
        observation.duration_ms
        for result in ordered
        for observation in result.raw_observations
    )
    return EvaluationMetrics(
        recall_at_k=_mean(tuple(item.recall_at_k for item in ordered), "recall_at_k"),
        mrr=_mean(tuple(item.reciprocal_rank for item in ordered), "mrr"),
        ndcg=_mean(tuple(item.ndcg for item in ordered), "ndcg"),
        supported_precision=precision,
        false_grounding_rate=grounding,
        highlight_iou=_mean(
            tuple(item.highlight_iou for item in ordered), "highlight_iou"
        ),
        p50_latency_ms=percentile(latencies, 0.50),
        p95_latency_ms=percentile(latencies, 0.95),
        access_leaks=sum(item.access_leaks for item in ordered),
        reproducibility=reproducibility,
    )


class EvaluationWorkflow:
    def __init__(
        self,
        repository: EvaluationRepositoryPort,
        search: EvaluationSearchPort,
        *,
        runtime_provider: Callable[[], Mapping[str, object]] | None = None,
    ) -> None:
        self.repository = repository
        self.search = search
        self.runtime_provider = runtime_provider or (
            lambda: capture_worker_runtime(environment="test")
        )

    async def run(self, run_id: UUID) -> None:
        claim = await self.repository.claim_run(run_id, self.runtime_provider())
        if claim is None:
            return
        try:
            if claim.repetition_count < 2:
                raise ValueError("Evaluation reproducibility requires at least two executions.")
            if any(case.permission_scenario.actor != "caller" for case in claim.dataset.cases):
                raise ValueError("Evaluation scenarios cannot impersonate another actor.")
            for candidate in claim.candidates:
                await self.repository.mark_candidate_running(
                    candidate.id, claim.claim_token
                )
                try:
                    results: list[CaseEvaluationResult] = []
                    for ordinal, case in enumerate(claim.dataset.cases):
                        existing = await self.repository.find_case_result(
                            candidate.id, case.id
                        )
                        if existing is not None:
                            results.append(existing)
                            continue
                        observations = tuple(
                            [
                                await self.search.execute(
                                    actor_id=claim.owner_id,
                                    candidate=candidate,
                                    case=case,
                                )
                                for _ in range(claim.repetition_count)
                            ]
                        )
                        await self.repository.heartbeat(run_id, claim.claim_token)
                        result = evaluate_case(
                            case,
                            ordinal,
                            observations,
                            retrieval_k=claim.retrieval_k,
                        )
                        await self.repository.add_case_result(
                            candidate.id,
                            claim.claim_token,
                            result,
                        )
                        results.append(result)
                    metrics = aggregate_metrics(claim.dataset, results)
                    await self.repository.complete_candidate(
                        candidate.id,
                        claim.claim_token,
                        metrics,
                    )
                except Exception as exc:
                    await self.repository.fail_candidate(
                        candidate.id,
                        claim.claim_token,
                        _safe_failure(exc),
                    )
            await self.repository.complete_run(run_id, claim.claim_token)
        except Exception as exc:
            await self.repository.fail_run(
                run_id,
                claim.claim_token,
                _safe_failure(exc),
            )
