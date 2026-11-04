"""Offline, hand-calculated ranking and untrusted-observation boundary tests."""

import math
from datetime import UTC, datetime
from uuid import UUID

import pytest

from ai_workshop.labs.rag.evaluation.vector_comparison.analysis import analyze
from ai_workshop.labs.rag.evaluation.vector_comparison.contracts import (
    Chunk,
    EmbeddingProfile,
    Engine,
    Hit,
    Observation,
    Observations,
    Plan,
    QueryCase,
    ResourceObservation,
    Settings,
    Snapshot,
    Target,
    digest,
)
from ai_workshop.labs.rag.evaluation.vector_comparison.planning import build_plan


def _snapshot(*, gold: tuple[int, ...] | None = (1,)) -> Snapshot:
    chunks = tuple(
        Chunk(
            chunk_id=UUID(int=number),
            workspace_id=UUID(int=10),
            document_id=UUID(int=20),
            asset_version_id=UUID(int=30),
            projection_id=UUID(int=40),
            index_build_id=UUID(int=50),
            vector=vector,
        )
        for number, vector in enumerate(
            ((1.0, 0.0), (0.8, 0.6), (0.8, -0.6), (0.0, 1.0), (-1.0, 0.0)),
            start=1,
        )
    )
    return Snapshot(
        snapshot_id=UUID(int=100),
        captured_at=datetime(2026, 11, 1, tzinfo=UTC),
        permission_revision="a" * 64,
        profile=EmbeddingProfile(model_id="synthetic", model_revision="b" * 40, dimension=2),
        chunks=chunks,
        cases=(
            QueryCase(
                case_id=UUID(int=101),
                vector=(1.0, 0.0),
                allowed_chunk_ids=tuple(chunk.chunk_id for chunk in chunks[:4]),
                forbidden_chunk_ids=(chunks[4].chunk_id,),
                relevant_chunk_ids=None if gold is None else tuple(UUID(int=i) for i in gold),
                bm25_chunk_ids=(UUID(int=4), UUID(int=1), UUID(int=2)),
            ),
        ),
    )


def _plan(snapshot: Snapshot, *, warmups: int = 0, k: int = 2) -> Plan:
    engines: tuple[Engine, ...] = ("elasticsearch", "pgvector", "qdrant")
    return build_plan(
        snapshot,
        Settings(k=k, candidate_k=3, repeats=2, warmups=warmups),
        tuple(
            Target(
                engine=engine,
                name="synthetic_corpus",
                version="synthetic",
                platform="offline",
                index_configuration="exact",
            )
            for engine in engines
        ),
    )


def _hit(snapshot: Snapshot, number: int) -> Hit:
    chunk = snapshot.chunks[number - 1]
    return Hit(**chunk.model_dump(exclude={"vector"}), score=float(6 - number))


def _observations(
    snapshot: Snapshot, plan: Plan, ranks: tuple[int, ...],
) -> Observations:
    return Observations(
        plan_digest=digest(plan),
        evidence_kind="synthetic",
        records=tuple(
            Observation(
                attempt_id=attempt.attempt_id,
                status="ok",
                elapsed_ms=10.0,
                hits=tuple(_hit(snapshot, number) for number in ranks),
            )
            for attempt in plan.attempts
        ),
    )


def test_perfect_and_reversed_ranks_have_hand_calculated_chunk_metrics() -> None:
    snapshot = _snapshot()
    plan = _plan(snapshot)
    perfect = analyze(snapshot, plan, _observations(snapshot, plan, (1, 2, 4)))
    reversed_result = analyze(snapshot, plan, _observations(snapshot, plan, (4, 1, 2)))

    assert perfect["status"] == "complete"
    assert perfect["evidence_kind"] == "synthetic"
    assert perfect["execution_verified"] is False
    perfect_quality = perfect["engines"]["elasticsearch"]["quality"]
    reverse_quality = reversed_result["engines"]["elasticsearch"]["quality"]
    assert perfect_quality["dense"]["recall_at_k"] == 1.0
    assert perfect_quality["dense"]["mrr_at_k"] == 1.0
    assert perfect_quality["dense"]["ndcg_at_k"] == 1.0
    assert reverse_quality["dense"]["recall_at_k"] == 1.0
    assert reverse_quality["dense"]["mrr_at_k"] == 0.5
    assert reverse_quality["dense"]["ndcg_at_k"] == pytest.approx(1 / math.log2(3))
    assert reverse_quality["exact_neighbor_recall_at_k"] == 0.5
    baseline = perfect["bm25_baseline"]["mean"]
    assert baseline["mrr_at_k"] == 0.5
    # BM25=[4,1,2], dense=[1,2,4]: RRF=[1,4,2], including the existing tie rule.
    assert perfect_quality["bm25_rrf"]["mrr_at_k"] == 1.0
    assert perfect_quality["sample_count"] == 3


@pytest.mark.parametrize(
    ("ranks", "expected"),
    [((1, 2), 1.0), ((1, 3), 1.0), ((2, 3), 0.5), ((1, 4), 0.5), ((), 0.0)],
)
def test_exact_neighbors_credit_boundary_ties_but_require_stronger_neighbors(
    ranks: tuple[int, ...], expected: float,
) -> None:
    snapshot = _snapshot()
    plan = _plan(snapshot)
    report = analyze(snapshot, plan, _observations(snapshot, plan, ranks))
    quality = report["engines"]["qdrant"]["quality"]
    assert quality["exact_neighbor_recall_at_k"] == expected


def test_relevance_mrr_does_not_credit_a_hit_outside_output_k() -> None:
    snapshot = _snapshot()
    plan = _plan(snapshot)
    report = analyze(snapshot, plan, _observations(snapshot, plan, (4, 2, 1)))
    quality = report["engines"]["qdrant"]["quality"]["dense"]
    assert quality == {"recall_at_k": 0.0, "mrr_at_k": 0.0, "ndcg_at_k": 0.0}


@pytest.mark.parametrize(
    ("invalid", "reason"),
    [
        ("forbidden", "outside_allowed_scope"),
        ("unknown", "unknown_chunk"),
        ("workspace", "identity_mismatch"),
        ("document", "identity_mismatch"),
        ("version", "identity_mismatch"),
        ("projection", "identity_mismatch"),
        ("build", "identity_mismatch"),
        ("duplicate", "duplicate_chunk"),
        ("too_many", "too_many_hits"),
    ],
)
def test_invalid_hits_fail_whole_observation_without_scoring_filtered_subset(
    invalid: str, reason: str,
) -> None:
    snapshot = _snapshot()
    plan = _plan(snapshot)
    first = plan.attempts[0]
    valid = _hit(snapshot, 1)
    fields = {
        "workspace": "workspace_id", "document": "document_id",
        "version": "asset_version_id", "projection": "projection_id", "build": "index_build_id",
    }
    if invalid in fields:
        bad = valid.model_copy(update={fields[invalid]: UUID(int=999)})
        hits = (bad, _hit(snapshot, 2))
    elif invalid == "forbidden":
        hits = (valid, _hit(snapshot, 5))
    elif invalid == "unknown":
        hits = (valid.model_copy(update={"chunk_id": UUID(int=999)}),)
    elif invalid == "duplicate":
        hits = (valid, valid)
    else:
        hits = tuple(_hit(snapshot, number) for number in (1, 2, 3, 4))
    observations = Observations(
        plan_digest=digest(plan), evidence_kind="imported_unverified",
        records=(Observation(attempt_id=first.attempt_id, status="ok", elapsed_ms=1, hits=hits),),
    )
    report = analyze(snapshot, plan, observations)
    row = report["attempts"][0]
    engine = report["engines"][first.engine]
    assert row["status"] == "invalid_result"
    assert reason in row["invalid_reasons"]
    assert row["quality"] is None
    assert engine["quality"]["sample_count"] == 0
    assert engine["quality"]["dense"]["recall_at_k"] is None
    assert engine["phases"]["first_observed"]["latency_ms"]["sample_count"] == 0
    assert engine["counts"]["invalid_result"] == 1
    assert report["evidence_kind"] == "imported_unverified"


def test_missing_failed_and_warmup_observations_cannot_bias_success_latency() -> None:
    snapshot = _snapshot()
    plan = _plan(snapshot, warmups=1)
    records = []
    for attempt in plan.attempts:
        if attempt.engine == "qdrant":
            continue
        status = "ok"
        elapsed = 9999.0 if attempt.phase == "warmup" else 10.0
        if attempt.phase == "repeated":
            elapsed = 20.0 if attempt.repeat == 0 else 40.0
        if attempt.engine == "pgvector":
            status = {"first_observed": "unavailable", "warmup": "error", "repeated": "timeout"}[
                attempt.phase
            ]
            elapsed = 9000.0
        records.append(Observation(
            attempt_id=attempt.attempt_id, status=status, elapsed_ms=elapsed,
            hits=(_hit(snapshot, 1),) if status == "ok" else (),
        ))
    report = analyze(snapshot, plan, Observations(
        plan_digest=digest(plan), evidence_kind="synthetic", records=tuple(records),
    ))
    engines = report["engines"]
    assert report["status"] == "partial"
    assert engines["elasticsearch"]["quality"]["sample_count"] == 3
    assert engines["elasticsearch"]["phases"]["first_observed"]["latency_ms"] == {
        "sample_count": 1, "p50": 10.0, "p95": 10.0,
    }
    assert engines["elasticsearch"]["phases"]["repeated"]["latency_ms"] == {
        "sample_count": 2, "p50": 30.0, "p95": 39.0,
    }
    assert engines["elasticsearch"]["phases"]["warmup"]["latency_ms"] is None
    assert engines["pgvector"]["counts"]["error"] == 1
    assert engines["pgvector"]["counts"]["timeout"] == 2
    assert engines["pgvector"]["counts"]["unavailable"] == 1
    assert engines["pgvector"]["phases"]["repeated"]["latency_ms"]["p95"] is None
    assert engines["qdrant"]["counts"]["missing"] == 4
    assert engines["qdrant"]["counts"]["observed"] == 0
    assert engines["qdrant"]["failure_rate_observed"] is None


@pytest.mark.parametrize(("gold", "gold_status"), [(None, "unjudged"), ((), "no_positive_gold")])
def test_unjudged_and_no_positive_gold_preserve_null_quality(
    gold: tuple[int, ...] | None, gold_status: str,
) -> None:
    snapshot = _snapshot(gold=gold)
    plan = _plan(snapshot)
    report = analyze(snapshot, plan, _observations(snapshot, plan, (1, 2)))
    quality = report["engines"]["elasticsearch"]["quality"]
    assert quality["dense"]["recall_at_k"] is None
    assert quality["dense"]["mrr_at_k"] is None
    assert quality["bm25_rrf"]["ndcg_at_k"] is None
    assert quality["judged_sample_count"] == 0
    assert quality["exact_neighbor_recall_at_k"] == 1.0
    assert report["bm25_baseline"]["cases"][0]["gold_status"] == gold_status


def test_unmeasured_resources_are_null_and_supplied_values_keep_method_and_scope() -> None:
    snapshot = _snapshot()
    plan = _plan(snapshot)
    observations = _observations(snapshot, plan, (1, 2))
    resources = ResourceObservation(
        method="external_sampler", scope="single process", rss_peak_bytes=50,
    )
    first = observations.records[0].model_copy(update={"resources": resources})
    observations = observations.model_copy(update={"records": (first, *observations.records[1:])})
    report = analyze(snapshot, plan, observations)
    assert report["attempts"][1]["resources"] is None
    recorded = report["attempts"][0]["resources"]
    assert recorded == {
        "method": "external_sampler", "scope": "single process", "rss_peak_bytes": 50,
        "cpu_process_ms": None, "container_memory_peak_bytes": None, "storage_bytes": None,
    }
    assert report["engines"][plan.attempts[1].engine]["resources"] is None


@pytest.mark.parametrize("mismatch", ["snapshot", "plan"])
def test_digest_mismatches_are_rejected_before_scoring(mismatch: str) -> None:
    snapshot = _snapshot()
    plan = _plan(snapshot)
    observations = _observations(snapshot, plan, (1, 2))
    if mismatch == "snapshot":
        snapshot = snapshot.model_copy(update={"permission_revision": "f" * 64})
    else:
        observations = observations.model_copy(update={"plan_digest": "f" * 64})
    with pytest.raises(ValueError, match="digest|snapshot"):
        analyze(snapshot, plan, observations)


@pytest.mark.parametrize("invalid", ["duplicate", "unknown"])
def test_unknown_and_duplicate_attempt_observations_are_rejected(invalid: str) -> None:
    snapshot = _snapshot()
    plan = _plan(snapshot)
    observations = _observations(snapshot, plan, (1, 2))
    record = observations.records[0]
    if invalid == "unknown":
        record = record.model_copy(update={"attempt_id": "unknown-attempt"})
    observations = observations.model_copy(update={"records": (*observations.records, record)})
    with pytest.raises(ValueError, match="duplicate|unknown"):
        analyze(snapshot, plan, observations)


def test_modified_attempt_schedule_is_rejected_even_with_matching_plan_digest() -> None:
    snapshot = _snapshot()
    plan = _plan(snapshot)
    plan = plan.model_copy(update={"attempts": plan.attempts[:-1]})
    observations = _observations(snapshot, plan, (1, 2))
    with pytest.raises(ValueError, match="plan|attempt|schedule"):
        analyze(snapshot, plan, observations)


@pytest.mark.parametrize(("gap", "expected"), [(0.0000004, 1.0), (0.000003, 0.0)])
def test_neighbor_boundary_uses_absolute_cosine_tolerance(gap: float, expected: float) -> None:
    snapshot = _snapshot()
    top = 0.8 + gap
    chunk = snapshot.chunks[0].model_copy(update={"vector": (top, math.sqrt(1 - top * top))})
    snapshot = Snapshot.model_validate({
        **snapshot.model_dump(), "chunks": (chunk, *snapshot.chunks[1:]),
    })
    plan = _plan(snapshot, k=1)
    report = analyze(snapshot, plan, _observations(snapshot, plan, (2,)))
    assert report["engines"]["qdrant"]["quality"]["exact_neighbor_recall_at_k"] == expected


def test_empty_allowed_scope_has_no_attempts_or_invented_measurements() -> None:
    snapshot = _snapshot()
    case = snapshot.cases[0].model_copy(update={
        "allowed_chunk_ids": (), "relevant_chunk_ids": (), "bm25_chunk_ids": (),
    })
    snapshot = Snapshot.model_validate({**snapshot.model_dump(), "cases": (case,)})
    plan = _plan(snapshot)
    report = analyze(snapshot, plan, _observations(snapshot, plan, ()))
    assert report["status"] == "no_attempts"
    assert report["skipped_empty_scope_cases"] == 1
    assert report["counts"]["planned"] == 0
    assert report["attempts"] == []
    assert report["engines"]["qdrant"]["quality"]["exact_neighbor_recall_at_k"] is None
    assert report["engines"]["qdrant"]["phases"]["repeated"]["latency_ms"]["p50"] is None


def test_all_observed_failures_are_not_marked_complete_success() -> None:
    snapshot = _snapshot()
    plan = _plan(snapshot)
    observations = Observations(
        plan_digest=digest(plan), evidence_kind="imported_unverified",
        records=tuple(
            Observation(attempt_id=attempt.attempt_id, status="error")
            for attempt in plan.attempts
        ),
    )
    report = analyze(snapshot, plan, observations)
    assert report["status"] == "complete_with_failures"
    assert report["counts"]["missing"] == 0
    assert report["counts"]["error"] == len(plan.attempts)
    assert report["engines"]["pgvector"]["failure_rate_observed"] == 1.0
    assert report["engines"]["pgvector"]["quality"]["sample_count"] == 0
