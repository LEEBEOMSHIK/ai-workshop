from dataclasses import replace
from uuid import UUID

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.executions.domain import CandidateObservation, StageObservation
from ai_workshop.labs.rag.executions.selection import selection_observation
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget
from ai_workshop.labs.rag.models.budget_trace import BudgetTrace
from ai_workshop.labs.rag.retrieval.domain import FusedHit
from ai_workshop.labs.rag.search.diagnostics import SearchDiagnostics
from ai_workshop.labs.rag.search.pipeline import SearchResult
from ai_workshop.labs.rag.search.schemas import SearchResponse
from tests.unit.labs.rag.highlighting.test_context import EMPTY
from tests.unit.labs.rag.highlighting.test_pdf_context_budget import choose, pdf_page
from tests.unit.labs.rag.search.test_generation_policy_gate import _configuration

TRACE = {
    "incoming_units": 33,
    "incoming_characters": 712,
    "before_groups": 0,
    "before_units": 0,
    "before_characters": 0,
    "group_limit": 8,
    "unit_limit": 32,
    "character_limit": 12000,
    "violated": ["units"],
}


@pytest.mark.parametrize(
    "field, value",
    [
        ("incoming_units", True),
        ("before_characters", 0.0),
        ("before_units", -1),
        ("group_limit", 0),
        ("unit_limit", "32"),
        ("text", "synthetic body"),
        ("violated", ["tokens"]),
        ("violated", ["units", "units"]),
        ("violated", ["groups", "units", "characters", "groups"]),
    ],
)
def test_metadata_rejects_coerced_counts_unbounded_fields_and_invalid_constraints(field, value):
    with pytest.raises(ValidationError):
        BudgetTrace.model_validate({**TRACE, field: value})


def test_legacy_execution_metadata_omits_trace_without_altering_existing_nullable_fields():
    old = CandidateObservation(
        document_id=UUID(int=1),
        asset_version_id=UUID(int=2),
        projection_id=UUID(int=3),
        evidence_unit_id=UUID(int=4),
        reason="budget_exceeded",
    ).model_dump(mode="json")
    assert "budget_trace" not in old
    assert old["semantic_score"] is None
    assert CandidateObservation.model_validate(old).model_dump(mode="json") == old


@pytest.mark.parametrize("diagnostics", [False, True])
def test_actual_trace_survives_execution_storage_without_request_diagnostics(diagnostics):
    source = pdf_page()
    context = choose((source,), EvidenceBudget(8, 32, 12000), diagnostics=diagnostics)
    configuration = _configuration(approval=None)
    hit = FusedHit(source.chunk.chunk_id, 0.5, 1, 1, None, sparse_score=2.0)
    observation = selection_observation((source,), (hit,), context, configuration, 0, (), 1)
    stage = StageObservation(stage="selection", state="completed", selection=observation)
    persisted = stage.model_dump(mode="json")
    assert persisted["selection"]["candidates"][0]["budget_trace"] == TRACE
    restored = StageObservation.model_validate(persisted)
    assert restored.model_dump(mode="json") == persisted
    assert len(observation.candidates) == 1


def test_search_response_contains_group_trace_only_and_legacy_response_is_unchanged():
    source = pdf_page()
    context = choose((source,), EvidenceBudget(8, 32, 12000))
    hit = FusedHit(source.chunk.chunk_id, 0.5, 1, 1, None, sparse_score=2.0)
    result = SearchResult(
        EMPTY,
        _configuration(approval=None),
        (),
        diagnostics=SearchDiagnostics(context.diagnostics, (hit,), (source,), {}, 1.0, 0.9),
    )
    payload = SearchResponse.from_domain(result).model_dump(mode="json")
    candidates = payload["diagnostics"]["candidates"]
    assert candidates[0]["budget_trace"] == TRACE
    assert "budget_trace" not in candidates[1]
    assert candidates[0]["semantic_score"] == 1.0
    legacy_candidates = tuple(replace(item, budget_trace=None) for item in context.diagnostics)
    legacy = replace(result, diagnostics=replace(result.diagnostics, candidates=legacy_candidates))
    legacy_payload = SearchResponse.from_domain(legacy).model_dump(mode="json")
    assert all("budget_trace" not in item for item in legacy_payload["diagnostics"]["candidates"])


@pytest.mark.parametrize("top_k, recorded", [(1, 1), (250, 200)])
def test_trace_addition_preserves_top_k_and_hard_candidate_cap(top_k, recorded):
    source = pdf_page()
    context = choose((source,), EvidenceBudget(8, 32, 12000), diagnostics=False)
    context = replace(context, observations=context.observations * 201)
    hit = FusedHit(source.chunk.chunk_id, 0.5, 1, 1, None)
    observation = selection_observation(
        (source,),
        (hit,),
        context,
        _configuration(approval=None),
        0,
        (),
        top_k,
    )
    assert observation.candidate_count == 201
    assert len(observation.candidates) == recorded
    assert observation.truncated
    assert observation.candidates[-1].budget_trace.model_dump(mode="json") == TRACE
