"""Public synthetic request contracts; no server, credentials, or model execution."""

import json
import re
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from ai_workshop.labs.rag.evaluation.vector_comparison.contracts import (
    Chunk,
    EmbeddingProfile,
    Engine,
    QueryCase,
    Settings,
    Snapshot,
    Target,
)

IDENTITY = (
    "chunk_id", "workspace_id", "document_id", "asset_version_id", "projection_id",
    "index_build_id",
)


def _snapshot() -> Snapshot:
    chunks = (
        Chunk(chunk_id=UUID(int=1), workspace_id=UUID(int=10), document_id=UUID(int=20),
              asset_version_id=UUID(int=30), projection_id=UUID(int=40),
              index_build_id=UUID(int=50), vector=(1.0, 0.0)),
        Chunk(chunk_id=UUID(int=2), workspace_id=UUID(int=11), document_id=UUID(int=21),
              asset_version_id=UUID(int=31), projection_id=UUID(int=41),
              index_build_id=UUID(int=51), vector=(0.0, 1.0)),
        Chunk(chunk_id=UUID(int=3), workspace_id=UUID(int=10), document_id=UUID(int=20),
              asset_version_id=UUID(int=30), projection_id=UUID(int=40),
              index_build_id=UUID(int=50), vector=(-1.0, 0.0)),
    )
    case = QueryCase(case_id=UUID(int=100), vector=(1.0, 0.0),
                     allowed_chunk_ids=(UUID(int=1), UUID(int=2)),
                     relevant_chunk_ids=(UUID(int=1),), forbidden_chunk_ids=(UUID(int=3),),
                     bm25_chunk_ids=(UUID(int=2), UUID(int=1)))
    empty = QueryCase(case_id=UUID(int=101), vector=(0.0, 1.0), allowed_chunk_ids=())
    return Snapshot(snapshot_id=UUID(int=200), captured_at=datetime(2026, 11, 1, tzinfo=UTC),
                    permission_revision="a" * 64,
                    profile=EmbeddingProfile(model_id="synthetic", model_revision="b" * 40,
                                             dimension=2), chunks=chunks, cases=(case, empty))


def _target(engine: Engine) -> Target:
    return Target(engine=engine, name="sealed_corpus_01", version="synthetic",
                  platform="test", index_configuration="exact cosine")


def _build(snapshot: Snapshot, target: Target, case: QueryCase | None = None) -> dict[str, object]:
    from ai_workshop.labs.rag.evaluation.vector_comparison.requests import build_request

    return build_request(snapshot, case or snapshot.cases[0], target,
                         Settings(k=1, candidate_k=2))


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _objects(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [_object(item) for item in value]


def _identity(chunk: Chunk) -> dict[str, str]:
    return {field: str(getattr(chunk, field)) for field in IDENTITY}


@pytest.mark.parametrize("engine", ["elasticsearch", "pgvector", "qdrant"])
def test_empty_authorized_scope_produces_no_executable_request(engine: Engine) -> None:
    snapshot = _snapshot()
    result = _build(snapshot, _target(engine), snapshot.cases[1])
    assert result["status"] == "skipped_empty_scope"
    assert result["case_id"] == str(UUID(int=101))
    assert "request" not in result
    assert json.loads(json.dumps(result)) == result


def test_elasticsearch_scores_only_exact_tuples_and_returns_identity_only() -> None:
    snapshot = _snapshot()
    result = _build(snapshot, _target("elasticsearch"))
    request = _object(result["request"])
    body = _object(request["body"])
    assert result["status"] == "prepared"
    assert request["method"] == "POST"
    assert request["path"] == "/sealed_corpus_01/_search"
    assert body["size"] == 2
    assert body["_source"] == list(IDENTITY)
    assert body["sort"] == [{"_score": "desc"}, {"chunk_id": "asc"}]
    assert "knn" not in body and "post_filter" not in body
    score = _object(_object(body["query"])["script_score"])
    script = _object(score["script"])
    assert script["source"] == "cosineSimilarity(params.query_vector, 'embedding') + 1.0"
    assert script["params"] == {"query_vector": [1.0, 0.0]}
    clause = _object(_object(score["query"])["bool"])
    assert clause["minimum_should_match"] == 1
    rows = []
    for alternative in _objects(clause["should"]):
        filters = _objects(_object(alternative["bool"])["filter"])
        row: dict[str, object] = {}
        for item in filters:
            row.update(_object(item["term"]))
        rows.append(row)
    assert rows == [_identity(snapshot.chunks[0]), _identity(snapshot.chunks[1])]
    crossed = _identity(snapshot.chunks[0]) | {"document_id": str(UUID(int=21))}
    assert not any(all(crossed[field] == row[field] for field in IDENTITY) for row in rows)
    assert _identity(snapshot.chunks[2]) not in rows


def test_pgvector_materializes_exact_subset_before_cosine_sort_and_parameterizes_values() -> None:
    snapshot = _snapshot()
    request = _object(_build(snapshot, _target("pgvector"))["request"])
    sql = request["sql"]
    assert isinstance(sql, str)
    params = _object(request["params"])
    assert sql.startswith("WITH allowed AS MATERIALIZED (")
    subset, output = sql.split(")\nSELECT ", maxsplit=1)
    assert 'FROM "sealed_corpus_01"' in subset
    assert "<=>" not in subset and "LIMIT" not in subset
    assert "embedding <=> %(query_vector)s::vector AS distance" in output
    assert "FROM allowed" in output
    assert "ORDER BY distance ASC, chunk_id ASC" in output
    assert output.endswith("LIMIT %(candidate_k)s")
    assert params["query_vector"] == "[1.0,0.0]"
    assert params["candidate_k"] == 2
    where = subset.split("WHERE ", maxsplit=1)[1].strip()
    alternatives = where.split(" OR ")
    assert len(alternatives) == 2
    for position, chunk in enumerate(snapshot.chunks[:2]):
        conditions = alternatives[position].strip("()").split(" AND ")
        assert conditions == [f"{field} = %(scope_{position}_{field})s::uuid"
                              for field in IDENTITY]
        for field in IDENTITY:
            value = str(getattr(chunk, field))
            assert params[f"scope_{position}_{field}"] == value
            assert value not in sql
    assert str(UUID(int=3)) not in params.values()
    selected = output.split(", embedding", maxsplit=1)[0]
    assert selected.split(", ") == list(IDENTITY)
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|COPY|SET)\b", sql)


def test_qdrant_uses_exact_original_vectors_with_tuple_prefilter_and_identity_payload() -> None:
    snapshot = _snapshot()
    request = _object(_build(snapshot, _target("qdrant"))["request"])
    assert request["method"] == "POST"
    assert request["path"] == "/collections/sealed_corpus_01/points/query"
    body = _object(request["body"])
    assert body["query"] == [1.0, 0.0]
    assert body["params"] == {"exact": True, "quantization": {"ignore": True}}
    assert body["limit"] == 2
    assert body["with_payload"] == list(IDENTITY)
    assert body["with_vector"] is False
    rows = []
    for alternative in _objects(_object(body["filter"])["should"]):
        rows.append({item["key"]: _object(item["match"])["value"]
                     for item in _objects(alternative["must"])})
    assert rows == [_identity(snapshot.chunks[0]), _identity(snapshot.chunks[1])]
    crossed = _identity(snapshot.chunks[0]) | {"projection_id": str(UUID(int=41))}
    assert not any(all(crossed[field] == row[field] for field in IDENTITY) for row in rows)
    assert _identity(snapshot.chunks[2]) not in rows


@pytest.mark.parametrize("engine", ["elasticsearch", "pgvector", "qdrant"])
def test_request_is_json_serializable_and_does_not_mutate_inputs(engine: Engine) -> None:
    snapshot, target = _snapshot(), _target(engine)
    original = snapshot.model_dump(mode="json")
    result = _build(snapshot, target)
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert snapshot.model_dump(mode="json") == original
    assert target == _target(engine)
    assert result["engine"] == engine
    assert result["target"] == "sealed_corpus_01"


@pytest.mark.parametrize("name", ["prod-*", "a,b", "x/../../_all", 'x"; DROP TABLE x; --',
                                 "public.corpus", "x\n"])
def test_bypassed_target_validation_cannot_inject_sql_or_broaden_a_path(name: str) -> None:
    target = _target("pgvector").model_copy(update={"name": name})
    with pytest.raises(ValueError):
        _build(_snapshot(), target)


@pytest.mark.parametrize("change", ["scope", "vector", "unknown_case"])
def test_case_must_equal_the_case_sealed_in_the_snapshot(change: str) -> None:
    snapshot = _snapshot()
    changes: dict[str, object] = {
        "scope": {"allowed_chunk_ids": (UUID(int=1),)},
        "vector": {"vector": (0.0, 1.0)},
        "unknown_case": {"case_id": UUID(int=999)},
    }
    case = snapshot.cases[0].model_copy(update=cast(dict[str, object], changes[change]))
    with pytest.raises(ValueError, match="case.*snapshot"):
        _build(snapshot, _target("elasticsearch"), case)


def test_bypassed_snapshot_validation_cannot_emit_unknown_chunk_or_bad_vector() -> None:
    snapshot = _snapshot()
    invalid = snapshot.model_copy(update={"chunks": snapshot.chunks[:1]})
    with pytest.raises(ValueError):
        _build(invalid, _target("qdrant"))
    bad_case = snapshot.cases[0].model_copy(update={"vector": (float("nan"), 0.0)})
    invalid = snapshot.model_copy(update={"cases": (bad_case,)})
    with pytest.raises(ValueError):
        _build(invalid, _target("pgvector"), bad_case)


def test_equal_boolean_case_vector_is_rejected_instead_of_emitted_as_numeric() -> None:
    snapshot = _snapshot()
    # Python treats True == 1.0: case equality alone is not vector validation.
    invalid = snapshot.cases[0].model_copy(update={"vector": (True, 0.0)})
    with pytest.raises(ValueError):
        _build(snapshot, _target("elasticsearch"), invalid)
