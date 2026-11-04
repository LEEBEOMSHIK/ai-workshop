"""Pure analysis of explicitly unverified vector-store observations."""

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from ai_workshop.labs.rag.evaluation.metrics import (
    ndcg_at_k,
    percentile,
    recall_at_k,
    reciprocal_rank,
)
from ai_workshop.labs.rag.evaluation.vector_comparison.contracts import (
    Attempt,
    Chunk,
    Identity,
    Observation,
    Observations,
    Plan,
    QueryCase,
    Snapshot,
    digest,
)
from ai_workshop.labs.rag.evaluation.vector_comparison.planning import validate_plan
from ai_workshop.labs.rag.retrieval.domain import RankedHit
from ai_workshop.labs.rag.retrieval.rrf import rrf_fuse

_TIE_TOLERANCE = 1e-6
_METRIC_NAMES = ("recall_at_k", "mrr_at_k", "ndcg_at_k")
type MetricValues = dict[str, float | None]


@dataclass(frozen=True, slots=True)
class _Quality:
    dense: MetricValues
    hybrid: MetricValues
    neighbor_recall: float | None

    def report(self) -> dict[str, object]:
        return {
            "dense": self.dense,
            "bm25_rrf": self.hybrid,
            "exact_neighbor_recall_at_k": self.neighbor_recall,
        }


@dataclass(frozen=True, slots=True)
class _Row:
    attempt: Attempt
    observation: Observation | None
    status: str
    invalid_reasons: tuple[str, ...]
    gold_status: str
    quality: _Quality | None

    def report(self) -> dict[str, object]:
        observation = self.observation
        return {
            **self.attempt.model_dump(mode="json"),
            "status": self.status,
            "reported_status": observation.status if observation else None,
            "invalid_reasons": list(self.invalid_reasons),
            "elapsed_ms": observation.elapsed_ms if observation else None,
            "hit_count": len(observation.hits) if observation else None,
            "gold_status": self.gold_status,
            "quality": self.quality.report() if self.quality else None,
            "resources": (
                observation.resources.model_dump(mode="json")
                if observation and observation.resources else None
            ),
        }


def _gold_status(case: QueryCase) -> str:
    if case.relevant_chunk_ids is None:
        return "unjudged"
    return "judged" if case.relevant_chunk_ids else "no_positive_gold"


def _metrics(ranks: Sequence[UUID], case: QueryCase, k: int) -> MetricValues:
    gold = frozenset(case.relevant_chunk_ids or ())
    return {
        "recall_at_k": recall_at_k(ranks, gold, k=k),
        "mrr_at_k": reciprocal_rank(ranks[:k], gold),
        "ndcg_at_k": ndcg_at_k(ranks, gold, k=k),
    }


def _identity(value: Identity) -> tuple[UUID, ...]:
    return (
        value.chunk_id, value.workspace_id, value.document_id, value.asset_version_id,
        value.projection_id, value.index_build_id,
    )


def _invalid_reasons(
    observation: Observation, case: QueryCase, chunks: dict[UUID, Chunk], candidate_k: int,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if len(observation.hits) > candidate_k:
        reasons.append("too_many_hits")
    seen: set[UUID] = set()
    allowed = set(case.allowed_chunk_ids)
    forbidden = set(case.forbidden_chunk_ids)
    for hit in observation.hits:
        if hit.chunk_id in seen:
            reasons.append("duplicate_chunk")
        seen.add(hit.chunk_id)
        if hit.chunk_id not in allowed or hit.chunk_id in forbidden:
            reasons.append("outside_allowed_scope")
        chunk = chunks.get(hit.chunk_id)
        if chunk is None:
            reasons.append("unknown_chunk")
        elif _identity(chunk) != _identity(hit):
            reasons.append("identity_mismatch")
    return tuple(dict.fromkeys(reasons))


def _cosine(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    # Normalize again in float64: accepted float32 unit vectors have rounding error.
    dot = math.fsum(a * b for a, b in zip(first, second, strict=True))
    return dot / (math.hypot(*first) * math.hypot(*second))


def _neighbor_recall(
    retrieved: Sequence[UUID], case: QueryCase, chunks: dict[UUID, Chunk], k: int,
) -> float | None:
    count = min(k, len(case.allowed_chunk_ids))
    if count == 0:
        return None
    scores = {
        chunk_id: _cosine(case.vector, chunks[chunk_id].vector)
        for chunk_id in case.allowed_chunk_ids
    }
    cutoff = sorted(scores.values(), reverse=True)[count - 1]
    stronger = {chunk_id for chunk_id, score in scores.items() if score > cutoff + _TIE_TOLERANCE}
    tied = {
        chunk_id for chunk_id, score in scores.items()
        if abs(score - cutoff) <= _TIE_TOLERANCE
    }
    returned = set(retrieved[:k])
    credit = len(returned & stronger) + min(len(returned & tied), count - len(stronger))
    return credit / count


def _score(
    observation: Observation, case: QueryCase, chunks: dict[UUID, Chunk], plan: Plan,
) -> _Quality:
    dense = tuple(hit.chunk_id for hit in observation.hits)
    sparse = case.bm25_chunk_ids[:plan.settings.candidate_k]
    fused = rrf_fuse(
        tuple(RankedHit(chunk_id, rank) for rank, chunk_id in enumerate(sparse, 1)),
        tuple(RankedHit(chunk_id, rank) for rank, chunk_id in enumerate(dense, 1)),
        k=plan.settings.rrf_k,
    )
    # Inputs are UUIDs; RRF's general domain also accepts strings.
    hybrid = tuple(UUID(str(hit.chunk_id)) for hit in fused)
    return _Quality(
        dense=_metrics(dense, case, plan.settings.k),
        hybrid=_metrics(hybrid, case, plan.settings.k),
        neighbor_recall=_neighbor_recall(dense, case, chunks, plan.settings.k),
    )


def _mean(values: Iterable[float | None]) -> float | None:
    known = tuple(value for value in values if value is not None)
    return math.fsum(known) / len(known) if known else None


def _metric_means(values: Sequence[MetricValues]) -> MetricValues:
    return {name: _mean(value[name] for value in values) for name in _METRIC_NAMES}


def _counts(rows: Sequence[_Row]) -> dict[str, int]:
    statuses = Counter(row.status for row in rows)
    return {
        "planned": len(rows),
        "observed": len(rows) - statuses["missing"],
        **{status: statuses[status] for status in (
            "ok", "error", "timeout", "unavailable", "invalid_result", "missing",
        )},
    }


def _latency(rows: Sequence[_Row]) -> dict[str, object]:
    samples = tuple(
        row.observation.elapsed_ms for row in rows
        if row.status == "ok" and row.observation and row.observation.elapsed_ms is not None
    )
    return {
        "sample_count": len(samples),
        "p50": percentile(samples, 0.5) if samples else None,
        "p95": percentile(samples, 0.95) if samples else None,
    }


def _summarize(rows: Sequence[_Row]) -> dict[str, object]:
    measured = tuple(row.quality for row in rows if row.quality is not None)
    counts = _counts(rows)
    phases = {}
    for phase in ("first_observed", "warmup", "repeated"):
        phase_rows = tuple(row for row in rows if row.attempt.phase == phase)
        phases[phase] = {
            "counts": _counts(phase_rows),
            "latency_ms": _latency(phase_rows) if phase != "warmup" else None,
        }
    resource_rows = [
        {
            "attempt_id": row.attempt.attempt_id, "phase": row.attempt.phase,
            "status": row.status, "observation": row.observation.resources.model_dump(mode="json"),
        }
        for row in rows if row.observation and row.observation.resources
    ]
    return {
        "counts": counts,
        "failure_rate_observed": (
            (counts["observed"] - counts["ok"]) / counts["observed"]
            if counts["observed"] else None
        ),
        "phases": phases,
        "quality": {
            "aggregation": "mean_of_valid_non_warmup_attempts",
            "sample_count": len(measured),
            "judged_sample_count": sum(
                value.dense["recall_at_k"] is not None for value in measured
            ),
            "dense": _metric_means(tuple(value.dense for value in measured)),
            "bm25_rrf": _metric_means(tuple(value.hybrid for value in measured)),
            "exact_neighbor_recall_at_k": _mean(value.neighbor_recall for value in measured),
            "exact_neighbor_sample_count": sum(
                value.neighbor_recall is not None for value in measured
            ),
        },
        "resources": resource_rows or None,
    }


def analyze(snapshot: Snapshot, plan: Plan, observations: Observations) -> dict[str, object]:
    """Validate sealed inputs and report chunk metrics without executing a request.

    Invalid results remain failures in the report; they are never filtered into
    successful rankings. Warmups and failed observations do not enter quality or
    latency summaries. Imported resource observations are preserved, not verified.
    """
    validate_plan(snapshot, plan)
    if observations.plan_digest != digest(plan):
        raise ValueError("observation plan digest does not match plan")
    known_attempts = {attempt.attempt_id for attempt in plan.attempts}
    supplied: dict[str, Observation] = {}
    for record in observations.records:
        if record.attempt_id in supplied:
            raise ValueError("duplicate observation attempt ID")
        if record.attempt_id not in known_attempts:
            raise ValueError("unknown observation attempt ID")
        supplied[record.attempt_id] = record
    chunks = {chunk.chunk_id: chunk for chunk in snapshot.chunks}
    cases = {case.case_id: case for case in snapshot.cases}
    rows: list[_Row] = []
    for attempt in plan.attempts:
        case = cases[attempt.case_id]
        observation = supplied.get(attempt.attempt_id)
        reasons = (
            _invalid_reasons(observation, case, chunks, plan.settings.candidate_k)
            if observation else ()
        )
        result_status: str = "missing" if observation is None else observation.status
        if reasons:
            result_status = "invalid_result"
        quality = (
            _score(observation, case, chunks, plan)
            if observation and result_status == "ok" and attempt.phase != "warmup" else None
        )
        rows.append(_Row(attempt, observation, result_status, reasons, _gold_status(case), quality))
    counts = _counts(rows)
    report_status = "complete" if rows else "no_attempts"
    if counts["observed"] != counts["ok"]:
        report_status = "complete_with_failures"
    if counts["missing"]:
        report_status = "partial"
    baseline_values = tuple(
        _metrics(case.bm25_chunk_ids[:plan.settings.candidate_k], case, plan.settings.k)
        for case in snapshot.cases
    )
    return {
        "schema_version": 1,
        "snapshot_digest": plan.snapshot_digest,
        "plan_digest": observations.plan_digest,
        "evidence_kind": observations.evidence_kind,
        "execution_verified": False,
        "status": report_status,
        "counts": counts,
        "k": plan.settings.k,
        "candidate_k": plan.settings.candidate_k,
        "rrf_k": plan.settings.rrf_k,
        "metric_unit": "chunk",
        "tie_tolerance": _TIE_TOLERANCE,
        "skipped_empty_scope_cases": sum(not case.allowed_chunk_ids for case in snapshot.cases),
        "bm25_baseline": {
            "aggregation": "mean_of_cases_with_positive_gold",
            "mean": _metric_means(baseline_values),
            "judged_case_count": sum(value["recall_at_k"] is not None for value in baseline_values),
            "cases": [
                {
                    "case_id": str(case.case_id), "gold_status": _gold_status(case),
                    "metrics": metrics,
                }
                for case, metrics in zip(snapshot.cases, baseline_values, strict=True)
            ],
        },
        "engines": {
            target.engine: _summarize(tuple(
                row for row in rows if row.attempt.engine == target.engine
            ))
            for target in plan.targets
        },
        "attempts": [row.report() for row in rows],
        "limitations": [
            "Offline preparation; supplied observations are not proof of engine execution.",
            "First observed latency is not a cold-start measurement; warmups are excluded.",
            "Latency is supplied client wall time including network round trips; "
            "no timing is collected here.",
            "Percentiles summarize observed valid samples only; "
            "small samples do not establish tail latency.",
            "Resource values are externally supplied; "
            "methods, scopes and intervals are not verified or pooled.",
            "Chunk relevance and exact-neighbor recall do not measure answer or citation quality.",
            "Synthetic corpus results cannot establish production-scale performance "
            "or promote a target.",
        ],
    }
