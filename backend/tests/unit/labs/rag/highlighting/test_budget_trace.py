"""Admission-time counts must explain rejection without changing whole-group selection."""

from dataclasses import replace

import pytest

from ai_workshop.labs.rag.highlighting.context import EvidenceBudget
from ai_workshop.labs.rag.highlighting.domain import EvidenceAnswer
from tests.unit.labs.rag.highlighting.test_context import EMPTY, ContextEmbedding
from tests.unit.labs.rag.highlighting.test_pdf_context_budget import choose, pdf_page


def trace(item):
    value = getattr(item, "budget_trace", None)
    assert value is not None, "Eligible groups need their actual admission-time budget counts"
    return value.model_dump(mode="json")


@pytest.mark.parametrize(
    "budget, violated",
    [
        (EvidenceBudget(8, 32, 12000), ["units"]),
        (EvidenceBudget(8, 128, 711), ["characters"]),
        (EvidenceBudget(8, 32, 711), ["units", "characters"]),
        (EvidenceBudget(8, 33, 712), []),
    ],
)
def test_full_pdf_counts_explain_each_limit_and_exact_boundary(budget, violated):
    result = choose((pdf_page(),), budget)
    assert trace(result.observations[0]) == {
        "incoming_units": 33,
        "incoming_characters": 712,
        "before_groups": 0,
        "before_units": 0,
        "before_characters": 0,
        "group_limit": budget.max_groups,
        "unit_limit": budget.max_units,
        "character_limit": budget.max_characters,
        "violated": violated,
    }
    assert bool(result.groups) == (not violated)
    assert trace(result.diagnostics[0]) == trace(result.observations[0])
    assert all(
        getattr(item, "budget_trace", None) is None
        for item in result.diagnostics
        if item.evidence_id is not None
    )


def test_rejected_group_consumes_nothing_and_records_all_simultaneous_constraints():
    sources = tuple(pdf_page(value) for value in range(1, 4))
    result = choose(sources, EvidenceBudget(1, 33, 712), diagnostics=False)
    assert len(result.groups) == 1
    for item in result.observations[1:]:
        assert trace(item) == {
            "incoming_units": 33,
            "incoming_characters": 712,
            "before_groups": 1,
            "before_units": 33,
            "before_characters": 712,
            "group_limit": 1,
            "unit_limit": 33,
            "character_limit": 712,
            "violated": ["groups", "units", "characters"],
        }


def test_group_limit_alone_excludes_next_group_even_with_units_and_characters_remaining():
    result = choose((pdf_page(1), pdf_page(2)), EvidenceBudget(1, 128, 12000))
    assert len(result.groups) == 1
    second = trace(result.observations[1])
    assert second["violated"] == ["groups"]
    assert second["before_groups"] == 1
    assert second["before_units"] == 33
    assert second["before_characters"] == 712


def test_diagnostic_setting_keeps_admission_counts_and_embedding_work_unchanged():
    class CountingEmbedding(ContextEmbedding):
        def __init__(self):
            self.query_calls = 0
            self.document_calls = 0

        def encode_query(self, text):
            self.query_calls += 1
            return super().encode_query(text)

        def encode_documents(self, texts):
            self.document_calls += 1
            return super().encode_documents(texts)

    off, on = CountingEmbedding(), CountingEmbedding()
    without = choose((pdf_page(),), EvidenceBudget(8, 32, 12000), diagnostics=False, embedding=off)
    with_diagnostics = choose((pdf_page(),), EvidenceBudget(8, 32, 12000), embedding=on)
    assert trace(without.observations[0]) == trace(with_diagnostics.observations[0])
    assert without.groups == with_diagnostics.groups
    assert (off.query_calls, off.document_calls) == (1, 1)
    assert (on.query_calls, on.document_calls) == (1, 2)


def test_below_threshold_group_never_gets_a_budget_pass_or_failure():
    class Unrelated(ContextEmbedding):
        def encode_documents(self, texts):
            return [[0.0, 1.0] for _ in texts]

    result = choose((pdf_page(),), EvidenceBudget(8, 32, 12000), embedding=Unrelated())
    assert result.observations[0].reason == "below_threshold"
    assert getattr(result.observations[0], "budget_trace", None) is None


def test_conflict_cancellation_retains_historical_admission_without_fabricating_failure():
    sources = (pdf_page(1), pdf_page(2))
    answers = tuple(
        EvidenceAnswer(s, s.chunk.evidence_units[1], s.chunk.evidence_units[1].text, (), None, 1.0)
        for s in sources
    )
    result = choose(
        sources,
        EvidenceBudget(8, 65, 12000),
        extractive=replace(EMPTY, answer=answers[0], conflicts=(answers[1],)),
    )
    assert not result.groups
    assert all(
        not item.selected and item.reason == "conflict_context_budget_exceeded"
        for item in result.observations
    )
    assert trace(result.observations[0])["violated"] == []
    assert trace(result.observations[1])["before_units"] == 33
    assert trace(result.observations[1])["violated"] == ["units"]
