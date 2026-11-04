"""Prepare read-only exact queries for a separately materialized, sealed corpus.

No request is executed here. Candidate stores use keyword/UUID identity fields,
an ``embedding`` vector field in Elasticsearch/pgvector, and Qdrant's unnamed
dense vector. A future runner must verify that schema, current authorization,
and the immutable corpus before executing a prepared request.
"""

import json

from ai_workshop.labs.rag.evaluation.vector_comparison.contracts import (
    Chunk,
    QueryCase,
    Settings,
    Snapshot,
    Target,
)

_IDENTITY_FIELDS = (
    "chunk_id", "workspace_id", "document_id", "asset_version_id", "projection_id",
    "index_build_id",
)


def build_request(
    snapshot: Snapshot, case: QueryCase, target: Target, settings: Settings,
) -> dict[str, object]:
    """Return a JSON-serializable template, or an explicit empty-scope skip.

    Revalidate serialized models because ``model_copy``/``model_construct`` can
    bypass Pydantic validation. In particular, never interpolate an unchecked
    candidate name into SQL or an HTTP path.
    """
    snapshot = Snapshot.model_validate(snapshot.model_dump())
    target = Target.model_validate(target.model_dump())
    settings = Settings.model_validate(settings.model_dump())
    if case not in snapshot.cases:
        raise ValueError("case must equal a case sealed in the snapshot")
    case = QueryCase.model_validate(case.model_dump())
    result: dict[str, object] = {
        "engine": target.engine, "target": target.name, "case_id": str(case.case_id),
        "status": "prepared",
    }
    if not case.allowed_chunk_ids:
        result["status"] = "skipped_empty_scope"
        return result

    by_id = {chunk.chunk_id: chunk for chunk in snapshot.chunks}
    scope = tuple(by_id[chunk_id] for chunk_id in case.allowed_chunk_ids)
    if target.engine == "elasticsearch":
        request = _elasticsearch(scope, case, target, settings)
    elif target.engine == "pgvector":
        request = _pgvector(scope, case, target, settings)
    else:
        request = _qdrant(scope, case, target, settings)
    result["request"] = request
    return result


def _identity(chunk: Chunk) -> dict[str, str]:
    return {field: str(getattr(chunk, field)) for field in _IDENTITY_FIELDS}


def _elasticsearch(
    scope: tuple[Chunk, ...], case: QueryCase, target: Target, settings: Settings,
) -> dict[str, object]:
    alternatives = [
        {"bool": {"filter": [
            {"term": {field: value}} for field, value in _identity(chunk).items()
        ]}}
        for chunk in scope
    ]
    return {
        "method": "POST", "path": f"/{target.name}/_search",
        "body": {
            "size": settings.candidate_k,
            "_source": list(_IDENTITY_FIELDS),
            "track_total_hits": False,
            "sort": [{"_score": "desc"}, {"chunk_id": "asc"}],
            "query": {"script_score": {
                "query": {"bool": {"should": alternatives, "minimum_should_match": 1}},
                "script": {
                    "source": "cosineSimilarity(params.query_vector, 'embedding') + 1.0",
                    "params": {"query_vector": list(case.vector)},
                },
            }},
        },
    }


def _pgvector(
    scope: tuple[Chunk, ...], case: QueryCase, target: Target, settings: Settings,
) -> dict[str, object]:
    params: dict[str, object] = {
        "query_vector": json.dumps(case.vector, separators=(",", ":"), allow_nan=False),
        "candidate_k": settings.candidate_k,
    }
    alternatives = []
    for position, chunk in enumerate(scope):
        conditions = []
        for field, value in _identity(chunk).items():
            key = f"scope_{position}_{field}"
            params[key] = value
            conditions.append(f"{field} = %({key})s::uuid")
        alternatives.append("(" + " AND ".join(conditions) + ")")
    fields = ", ".join(_IDENTITY_FIELDS)
    # The outer query scans a materialized relation with no ANN index. Distance
    # ranking cannot move ahead of the exact source/permission subset.
    sql = (
        "WITH allowed AS MATERIALIZED (\n"
        f"    SELECT {fields}, embedding\n"
        f'    FROM "{target.name}"\n'
        f"    WHERE {' OR '.join(alternatives)}\n"
        ")\n"
        f"SELECT {fields}, embedding <=> %(query_vector)s::vector AS distance\n"
        "FROM allowed\n"
        "ORDER BY distance ASC, chunk_id ASC\n"
        "LIMIT %(candidate_k)s"
    )
    return {"sql": sql, "params": params}


def _qdrant(
    scope: tuple[Chunk, ...], case: QueryCase, target: Target, settings: Settings,
) -> dict[str, object]:
    alternatives = [
        {"must": [{"key": field, "match": {"value": value}}
                  for field, value in _identity(chunk).items()]}
        for chunk in scope
    ]
    return {
        "method": "POST", "path": f"/collections/{target.name}/points/query",
        "body": {
            "query": list(case.vector),
            "filter": {"should": alternatives},
            "params": {"exact": True, "quantization": {"ignore": True}},
            "limit": settings.candidate_k,
            "with_payload": list(_IDENTITY_FIELDS),
            "with_vector": False,
        },
    }
