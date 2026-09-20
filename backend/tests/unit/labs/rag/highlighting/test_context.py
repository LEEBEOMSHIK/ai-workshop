from dataclasses import replace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.embeddings.contracts import EmbeddingRuntimeUnavailableError
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget, select_context
from ai_workshop.labs.rag.highlighting.domain import (
    AnswerStatus,
    ConflictState,
    EvidenceAnswer,
    EvidenceSelection,
)
from tests.unit.labs.rag.highlighting.test_evidence_selector import _policy, _source

EMPTY = EvidenceSelection(AnswerStatus.INSUFFICIENT_EVIDENCE, None, ConflictState.NONE, ())
BUDGET = EvidenceBudget(8, 32, 12000)


class ContextEmbedding:
    dimension = 2

    def count_tokens(self, text):
        return len(text.split())

    count_query_tokens = count_tokens

    def encode_query(self, text):
        return [1.0, 0.0]

    def encode_documents(self, texts):
        return [[1.0, 0.0] if "\n" in text else [0.0, 1.0] for text in texts]


def paragraph():
    source = _source(1, "실험 장치의 이름은 달빛입니다.")
    first = source.chunk.evidence_units[0]
    second = replace(first, id=UUID(int=99), ordinal=1, text="보증 기간은 구매 후 18개월입니다.",
                     location=replace(first.location, element_id=UUID(int=100),
                                      char_start=0, char_end=25))
    return replace(source, chunk=replace(source.chunk, evidence_units=(first, second)))


def select(sources, *, budget=BUDGET, diagnostics=True, embedding=None):
    return select_context(query="달빛 보증은 얼마나 유지되나요?", sources=sources,
                          extractive=EMPTY, policy=_policy(min_semantic_score=0.9),
                          budget=budget, embedding=embedding or ContextEmbedding(),
                          include_diagnostics=diagnostics)


def test_context_only_match_retains_exact_units_and_diagnostics_do_not_change_selection():
    source = paragraph()
    result = select((source,))
    assert result.groups[0].units == source.chunk.evidence_units
    assert result.groups == select((source,), diagnostics=False).groups
    assert all(d.semantic_score == 0 for d in result.diagnostics if d.evidence_id)
    assert next(d for d in result.diagnostics if d.evidence_id is None).semantic_score == 1


def test_budget_excludes_whole_group_instead_of_cutting_sentences():
    result = select((paragraph(),), budget=EvidenceBudget(1, 1, 12000))
    assert not result.groups
    assert any(d.reason == "budget_exceeded" for d in result.diagnostics)


def test_budget_cannot_keep_only_one_side_of_a_known_conflict():
    sources = (_source(1, "Synthetic rule A"), _source(2, "Synthetic rule B"))
    answers = tuple(EvidenceAnswer(s, s.chunk.evidence_units[0], s.chunk.text, (), None, 1.0)
                    for s in sources)
    result = select_context(query="rule", sources=sources,
        extractive=replace(EMPTY, answer=answers[0], conflicts=(answers[1],)),
        policy=_policy(), budget=EvidenceBudget(1, 1, 12000),
        embedding=ContextEmbedding(), include_diagnostics=True)
    assert result.groups == ()
    assert result.blocked_reason == "conflict_context_budget_exceeded"
    assert not any(item.selected for item in result.diagnostics)


def test_conflicting_identity_is_rejected():
    source = paragraph()
    changed = replace(source, document_id=UUID(int=101))
    with pytest.raises(ValueError, match="identity"):
        select((source, changed))


def test_invalid_provenance_is_not_rescued_by_context():
    source = paragraph()
    invalid = replace(source.chunk.evidence_units[0], projection_id=UUID(int=111))
    source = replace(source, chunk=replace(source.chunk, evidence_units=(invalid,)))
    assert not select((source,)).groups


def test_all_qualified_sentences_survive_even_when_whole_context_scores_low():
    sources = (_source(1, "first relevant statement"), _source(2, "another relevant statement"))
    answers = tuple(EvidenceAnswer(s, s.chunk.evidence_units[0], s.chunk.text, (), None, 1.0)
                    for s in sources)

    class LowContext(ContextEmbedding):
        def encode_documents(self, texts):
            return [[0.0, 1.0] for _ in texts]

    result = select_context(query="paraphrase", sources=sources,
        extractive=replace(EMPTY, answer=answers[0], candidates=answers), policy=_policy(),
        budget=BUDGET, embedding=LowContext(), include_diagnostics=False)
    assert len(result.groups) == 2


def test_diagnostic_embedding_failure_is_visible_without_changing_selected_context():
    class DiagnosticFailure(ContextEmbedding):
        calls = 0

        def encode_documents(self, texts):
            self.calls += 1
            if self.calls > 1:
                raise EmbeddingRuntimeUnavailableError("synthetic failure")
            return super().encode_documents(texts)

    result = select((paragraph(),), embedding=DiagnosticFailure())
    assert len(result.groups) == 1
    assert result.diagnostic_warning == "diagnostic_embedding_unavailable"
    assert all(d.semantic_score is None for d in result.diagnostics if d.evidence_id)


@pytest.mark.parametrize("values", [(0, 1, 1), (2, 1, 10), (True, 2, 10)])
def test_budget_rejects_invalid_limits(values):
    with pytest.raises(ValueError):
        EvidenceBudget(*values)
