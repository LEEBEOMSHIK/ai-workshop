from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.evaluation.vector_comparison.contracts import (
    Chunk,
    EmbeddingProfile,
    Observation,
    QueryCase,
    ResourceObservation,
    Settings,
    Snapshot,
    Target,
    digest,
)
from ai_workshop.labs.rag.evaluation.vector_comparison.planning import build_plan, validate_plan


def sample_snapshot() -> Snapshot:
    chunk = Chunk(
        chunk_id=UUID(int=1),
        workspace_id=UUID(int=10),
        document_id=UUID(int=11),
        asset_version_id=UUID(int=12),
        projection_id=UUID(int=13),
        index_build_id=UUID(int=14),
        vector=(1.0, 0.0),
    )
    return Snapshot(
        snapshot_id=UUID(int=20),
        captured_at=datetime(2026, 11, 1, tzinfo=UTC),
        permission_revision="a" * 64,
        profile=EmbeddingProfile(model_id="synthetic", model_revision="a" * 40, dimension=2),
        chunks=(chunk,),
        cases=(
            QueryCase(
                case_id=UUID(int=30),
                vector=(1.0, 0.0),
                allowed_chunk_ids=(chunk.chunk_id,),
                relevant_chunk_ids=(chunk.chunk_id,),
                bm25_chunk_ids=(chunk.chunk_id,),
            ),
        ),
    )


def test_digest_round_trip_and_vector_normalization() -> None:
    snapshot = sample_snapshot()
    assert digest(Snapshot.model_validate_json(snapshot.model_dump_json())) == digest(snapshot)
    data = snapshot.model_dump(mode="json")
    data["cases"][0]["vector"] = [0.0, 0.0]
    with pytest.raises(ValidationError, match="normalized"):
        Snapshot.model_validate(data)


def test_rejects_out_of_scope_gold_and_unknown_fields() -> None:
    data = sample_snapshot().model_dump(mode="json")
    data["cases"][0]["allowed_chunk_ids"] = []
    with pytest.raises(ValidationError, match="allowed"):
        Snapshot.model_validate(data)
    data = sample_snapshot().model_dump(mode="json")
    data["api_key"] = "never-accepted"
    with pytest.raises(ValidationError, match="Extra inputs"):
        Snapshot.model_validate(data)


@pytest.mark.parametrize(
    "vector",
    [
        [1, 0, 0],
        [True, 0],
        ["1", 0],
        [float("nan"), 0],
        [float("inf"), 0],
        [1e80, 0],
        [2.0, 0.0],
        [],
    ],
)
def test_rejects_malformed_vectors(vector: object) -> None:
    data = sample_snapshot().model_dump(mode="json")
    data["chunks"][0]["vector"] = vector
    with pytest.raises(ValidationError):
        Snapshot.model_validate(data)


def test_float32_is_canonical_before_hashing() -> None:
    data = sample_snapshot().model_dump(mode="json")
    data["chunks"][0]["vector"] = [0.8, 0.6]
    snapshot = Snapshot.model_validate(data)
    assert snapshot.chunks[0].vector[0] == 0.800000011920929
    assert snapshot.chunks[0].vector[1] == 0.6000000238418579
    assert digest(snapshot) == digest(Snapshot.model_validate_json(snapshot.model_dump_json()))


@pytest.mark.parametrize("field", ["classification", "captured_at", "permission_revision"])
def test_rejects_unapproved_or_unbound_snapshot(field: str) -> None:
    data = sample_snapshot().model_dump(mode="json")
    data[field] = {
        "classification": "private",
        "captured_at": "2026-11-01T00:00:00",
        "permission_revision": "missing",
    }[field]
    with pytest.raises(ValidationError):
        Snapshot.model_validate(data)


def test_conflicting_build_and_unknown_case_id_rejected() -> None:
    data = sample_snapshot().model_dump(mode="json")
    other = dict(data["chunks"][0], chunk_id=str(UUID(int=2)), document_id=str(UUID(int=99)))
    data["chunks"].append(other)
    with pytest.raises(ValidationError, match="provenance"):
        Snapshot.model_validate(data)
    data = sample_snapshot().model_dump(mode="json")
    data["cases"][0]["forbidden_chunk_ids"] = [str(UUID(int=999))]
    with pytest.raises(ValidationError, match="unknown"):
        Snapshot.model_validate(data)


def test_plan_balance_first_phase_order_and_tampering() -> None:
    snapshot = sample_snapshot()
    targets = tuple(
        Target(
            engine=engine,
            name="synthetic",
            version="test",
            platform="test",
            index_configuration="exact",
        )
        for engine in ("elasticsearch", "pgvector", "qdrant")
    )
    plan = build_plan(snapshot, Settings(k=1, candidate_k=2, repeats=2), targets)
    assert len(plan.attempts) == 12
    assert [attempt.engine for attempt in plan.attempts[:3]] != [
        attempt.engine for attempt in plan.attempts[3:6]
    ]
    for engine in ("elasticsearch", "pgvector", "qdrant"):
        assert [attempt.phase for attempt in plan.attempts if attempt.engine == engine] == [
            "first_observed",
            "warmup",
            "repeated",
            "repeated",
        ]
    validate_plan(snapshot, plan)
    assert digest(plan) == digest(build_plan(snapshot, plan.settings, tuple(reversed(targets))))
    with pytest.raises(ValueError, match="canonical"):
        validate_plan(snapshot, plan.model_copy(update={"attempts": plan.attempts[:-1]}))


@pytest.mark.parametrize("name", ["../live", "live; DROP TABLE x", "Live", "live*", "a,b"])
def test_target_cannot_escape_candidate_identifier(name: str) -> None:
    with pytest.raises(ValidationError):
        Target(
            engine="pgvector",
            name=name,
            version="test",
            platform="test",
            index_configuration="exact",
        )


def test_success_requires_measured_time() -> None:
    with pytest.raises(ValidationError, match="elapsed_ms"):
        Observation(attempt_id="one", status="ok")


@pytest.mark.parametrize("field", ["workspace_id", "document_id", "asset_version_id"])
def test_identity_parent_remains_consistent_across_builds(field: str) -> None:
    data = sample_snapshot().model_dump(mode="json")
    other = dict(data["chunks"][0], chunk_id=str(UUID(int=2)), index_build_id=str(UUID(int=99)))
    other[field] = str(UUID(int=88))
    data["chunks"].append(other)
    with pytest.raises(ValidationError, match="provenance"):
        Snapshot.model_validate(data)


@pytest.mark.parametrize("value", [True, False, "0.01"])
def test_measurements_do_not_coerce_boolean_or_text(value: object) -> None:
    with pytest.raises(ValidationError):
        Observation.model_validate({"attempt_id": "one", "status": "ok", "elapsed_ms": value})
    with pytest.raises(ValidationError):
        ResourceObservation.model_validate(
            {"method": "test", "scope": "process", "cpu_process_ms": value}
        )


def test_dimension_must_work_for_all_three_engines() -> None:
    with pytest.raises(ValidationError):
        EmbeddingProfile(model_id="synthetic", model_revision="a" * 40, dimension=4097)
