"""Synthetic span-fragmented PDFs retain whole, source-addressable context."""

from dataclasses import replace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import SourceLocation, TableCellLocation
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget, select_context
from ai_workshop.labs.rag.highlighting.domain import EvidenceAnswer
from tests.unit.labs.rag.highlighting.test_context import EMPTY, ContextEmbedding
from tests.unit.labs.rag.highlighting.test_evidence_selector import _policy, _source


def pdf_page(value=1, *, count=33):
    source = _source(value, "synthetic")
    template = source.chunk.evidence_units[0]
    # 33 spans, 712 characters: headers, two distinct rows, and a distant exception.
    labels = ["Product | Duration", "Orchid | 10 days", "Cedar | 20 days"]
    labels += [f"Disclosure {index}" for index in range(count - 4)]
    labels += ["Exception: closed days excluded"]
    texts = [text.ljust(21, ".") for text in labels]
    texts[0] += "." * max(0, 712 - sum(map(len, texts)))
    units = tuple(replace(
        template, id=UUID(int=value * 1000 + index), ordinal=index, text=text,
        location=SourceLocation(
            element_id=UUID(int=value * 10000 + index), page=value,
            char_start=index * 100, char_end=index * 100 + len(text),
            bbox=(10.0, float(index * 10), 500.0, float(index * 10 + 9)),
            table_cell=TableCellLocation(index, 0) if index < 3 else None,
        ),
    ) for index, text in enumerate(texts))
    return replace(source, media_type="application/pdf", chunk=replace(
        source.chunk, text="\n".join(texts), evidence_units=units,
    ))


def choose(sources, budget, *, diagnostics=True, extractive=EMPTY, embedding=None):
    return select_context(
        query="unrelated question", sources=sources, extractive=extractive,
        policy=_policy(min_semantic_score=0.9), budget=budget,
        embedding=embedding or ContextEmbedding(), include_diagnostics=diagnostics,
    )


def test_fragmented_pdf_budget_failure_and_evaluated_candidate_preserve_full_page():
    source = pdf_page()
    assert len(source.chunk.evidence_units) == 33
    assert sum(len(unit.text) for unit in source.chunk.evidence_units) == 712
    limited = choose((source,), EvidenceBudget(8, 32, 12000))
    assert not limited.groups
    assert limited.diagnostics[0].eligible
    assert limited.diagnostics[0].reason == "budget_exceeded"
    candidate = EvidenceBudget(8, 128, 12000)
    retained = choose((source,), candidate)
    assert retained.groups[0].units == source.chunk.evidence_units
    assert retained.groups == choose((source,), candidate, diagnostics=False).groups
    assert all(unit is original for unit, original in zip(
        retained.groups[0].units, source.chunk.evidence_units, strict=True,
    ))
    assert all(item.selected for item in retained.diagnostics)


@pytest.mark.parametrize("budget", [EvidenceBudget(8, 128, 711), EvidenceBudget(8, 32, 12000)])
def test_pdf_page_never_loses_headers_other_rows_or_exception_to_fit(budget):
    assert not choose((pdf_page(),), budget).groups


def test_candidate_unit_limit_applies_across_pdf_pages():
    sources = tuple(pdf_page(value) for value in range(1, 5))
    result = choose(sources, EvidenceBudget(8, 128, 12000))
    assert len(result.groups) == 3
    assert sum(len(group.units) for group in result.groups) == 99
    assert all(len(group.units) == 33 for group in result.groups)
    assert sum(item.reason == "budget_exceeded" for item in result.diagnostics) == 1


def test_larger_pdf_budget_does_not_qualify_unrelated_context():
    class Unrelated(ContextEmbedding):
        def encode_documents(self, texts):
            return [[0.0, 1.0] for _ in texts]

    result = choose((pdf_page(),), EvidenceBudget(8, 128, 12000), embedding=Unrelated())
    assert not result.groups
    assert result.diagnostics[0].reason == "below_threshold"


def test_pdf_budget_preserves_conflict_pair_or_blocks_every_group():
    sources = (pdf_page(1), pdf_page(2))
    answers = tuple(EvidenceAnswer(
        source, source.chunk.evidence_units[1], source.chunk.evidence_units[1].text,
        (), None, 1.0,
    ) for source in sources)
    selection = replace(EMPTY, answer=answers[0], conflicts=(answers[1],))
    rejected = choose(sources, EvidenceBudget(8, 65, 12000), extractive=selection)
    assert not rejected.groups
    assert rejected.blocked_reason == "conflict_context_budget_exceeded"
    assert not any(item.selected for item in rejected.diagnostics)
    retained = choose(sources, EvidenceBudget(8, 128, 12000), extractive=selection)
    assert len(retained.groups) == 2
    assert retained.blocked_reason is None


def test_larger_pdf_budget_does_not_rescue_missing_provenance():
    source = pdf_page()
    invalid = tuple(replace(unit, location=replace(unit.location, bbox=None))
                    for unit in source.chunk.evidence_units)
    source = replace(source, chunk=replace(source.chunk, evidence_units=invalid))
    result = choose((source,), EvidenceBudget(8, 128, 12000))
    assert not result.groups
    assert not result.diagnostics


def test_larger_pdf_budget_rejects_conflicting_source_identity():
    source = pdf_page()
    changed = replace(source, document_id=UUID(int=909))
    with pytest.raises(ValueError, match="identity"):
        choose((source, changed), EvidenceBudget(8, 128, 12000))
