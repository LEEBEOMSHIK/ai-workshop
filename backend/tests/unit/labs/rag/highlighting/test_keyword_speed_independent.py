"""Independent public-contract checks for request-owned keyword reuse."""

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import SourceLocation
from ai_workshop.labs.rag.highlighting import service
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget, select_context
from ai_workshop.labs.rag.highlighting.domain import ConflictState
from ai_workshop.labs.rag.highlighting.service import EvidenceSelector, KeywordMatcher
from tests.unit.labs.rag.highlighting.test_evidence_selector import _policy, _source


def _location(text: str, start: int = 37) -> SourceLocation:
    return SourceLocation(
        element_id=UUID(int=11), page=3, char_start=start,
        char_end=start + len(text), bbox=(1.0, 2.0, 3.0, 4.0),
    )


@pytest.mark.parametrize(
    ("query", "text", "coverage", "ranges"),
    [
        ("café", "x Cafe\u0301 y", 1.0, [(2, 7)]),
        ("가", "x \u1100\u1161 y", 1.0, [(2, 4)]),
        ("각", "\u1100\u1161\u11a8", 1.0, [(0, 3)]),
        ("ffi", "\ufb03", 1.0, [(0, 1)]),
        ("strasse", "Straße", 1.0, [(0, 6)]),
        ("ss", "aßßz", 1.0, [(1, 2), (2, 3)]),
        ("i", "İ", 1.0, [(0, 1)]),
        ("iv", "Ⅳ", 1.0, [(0, 1)]),
        ("cat cat", "concatenate cat", 1.0, [(3, 6), (12, 15)]),
        ("ＦＯＯ foo FOO absent", "\tfoo\u3000", 0.5, [(1, 4)]),
        ("a b", " a\t\r\n\u00a0b ", 1.0, [(1, 2), (6, 7)]),
        ("%", "50％", 1.0, [(2, 3)]),
        ("", "synthetic", 0.0, []),
        ("?! \t", "synthetic", 0.0, []),
        ("alpha", "", 0.0, []),
    ],
)
def test_unicode_coverage_and_original_spans_have_explicit_expectations(
    query: str, text: str, coverage: float, ranges: list[tuple[int, int]],
) -> None:
    matcher = KeywordMatcher(query)
    location = _location(text)
    result = matcher.highlights(text, location, UUID(int=12))

    assert matcher.coverage(text) == result.coverage == coverage
    assert [(span.char_start, span.char_end, span.text) for span in result.highlights] == [
        (location.char_start + start, location.char_start + end, text[start:end])
        for start, end in ranges
    ]
    for span, (start, end) in zip(result.highlights, ranges, strict=True):
        whole_unit = start == 0 and end == len(text)
        assert span.evidence_unit_id == UUID(int=12)
        assert span.page == 3
        assert span.bbox == (location.bbox if whole_unit else None)
        assert span.warnings == (() if whole_unit else ("pdf_keyword_bbox_unavailable",))


def test_coverage_does_not_build_original_offsets(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(_text: str) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
        raise AssertionError("Coverage must not calculate original offsets")

    monkeypatch.setattr(service, "_normalize_with_original_offsets", forbidden)
    matcher = KeywordMatcher("STRASSE ffi 가")
    assert matcher.coverage(" Straße \ufb03 \u1100\u1161 ") == 1.0
    assert matcher.coverage("no match") == 0.0
    assert KeywordMatcher("?!").coverage("synthetic") == 0.0


def test_cached_text_never_reuses_another_sources_coordinates_or_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = service._normalize_with_original_offsets
    calls: list[str] = []

    def counted(text: str) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
        calls.append(text)
        return original(text)

    monkeypatch.setattr(service, "_normalize_with_original_offsets", counted)
    text = "synthetic Straße"
    first = KeywordMatcher("strasse")
    a = first.highlights(text, _location(text, 40), UUID(int=20))
    b = first.highlights(text, _location(text, 400), UUID(int=21))
    assert calls.count(text) == 1
    assert a.highlights[0].char_start == 50
    assert b.highlights[0].char_start == 410
    assert a.highlights[0].evidence_unit_id == UUID(int=20)
    assert b.highlights[0].evidence_unit_id == UUID(int=21)

    second = KeywordMatcher("strasse")
    assert second.highlights(text, _location(text, 40), UUID(int=20)) == a
    assert calls.count(text) == 2, "A new request must calculate its own source offsets"


class OrthogonalEmbedding:
    """A deterministic local port; no model or network can be invoked."""

    dimension = 2

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def count_query_tokens(self, text: str) -> int:
        return len(text.split())

    def encode_query(self, text: str) -> list[float]:
        return [1.0, 0.0]

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0, 1.0] for _ in texts]


@pytest.mark.parametrize("max_groups", [1, 2])
def test_reused_matcher_preserves_conflicts_anchors_and_budget(max_groups: int) -> None:
    query = "late fee"
    sources = (_source(1, "late fee 3%"), _source(2, "late fee 5%"))
    policy = _policy()
    embedding = OrthogonalEmbedding()
    selector = EvidenceSelector(embedding)
    ordinary = selector.select(query=query, sources=sources, policy=policy)
    keywords = KeywordMatcher(query)
    shared = selector.select(query=query, sources=sources, policy=policy, keywords=keywords)
    assert shared == ordinary
    assert shared.answer is not None and shared.answer.source == sources[0]
    assert shared.conflict_state is ConflictState.SEPARATE_SOURCES
    assert [answer.source for answer in shared.conflicts] == [sources[1]]

    context = select_context(
        query=query, sources=sources, extractive=shared, policy=policy,
        budget=EvidenceBudget(max_groups, 2, 100), embedding=embedding,
        include_diagnostics=True, keywords=keywords,
    )
    assert context == select_context(
        query=query, sources=sources, extractive=shared, policy=policy,
        budget=EvidenceBudget(max_groups, 2, 100), embedding=embedding,
        include_diagnostics=True,
    )
    if max_groups == 1:
        assert context.groups == ()
        assert context.blocked_reason == "conflict_context_budget_exceeded"
    else:
        assert [group.source for group in context.groups] == list(sources)
        assert [unit for group in context.groups for unit in group.units] == [
            source.chunk.evidence_units[0] for source in sources
        ]
        assert context.blocked_reason is None


def test_matcher_query_binding_is_exact_even_for_equivalent_normalization() -> None:
    source = _source(1, "synthetic alpha")
    embedding = OrthogonalEmbedding()
    selector = EvidenceSelector(embedding)
    ordinary = selector.select(query="alpha", sources=(source,), policy=_policy())
    with pytest.raises(ValueError, match="query"):
        selector.select(
            query="alpha", sources=(source,), policy=_policy(), keywords=KeywordMatcher("ALPHA"),
        )
    with pytest.raises(ValueError, match="query"):
        select_context(
            query="alpha", sources=(source,), extractive=ordinary, policy=_policy(),
            budget=EvidenceBudget(1, 1, 100), embedding=embedding, include_diagnostics=False,
            keywords=KeywordMatcher("ALPHA"),
        )


def test_reuse_does_not_rescue_invalid_provenance() -> None:
    valid = _source(1, "synthetic alpha")
    invalid_unit = replace(valid.chunk.evidence_units[0], projection_id=UUID(int=900))
    invalid = replace(valid, chunk=replace(valid.chunk, evidence_units=(invalid_unit,)))
    keywords = KeywordMatcher("alpha")
    assert keywords.coverage(invalid_unit.text) == 1.0
    embedding = OrthogonalEmbedding()
    selected = EvidenceSelector(embedding).select(
        query="alpha", sources=(invalid,), policy=_policy(), keywords=keywords,
    )
    assert selected.answer is None
    context = select_context(
        query="alpha", sources=(invalid,), extractive=selected, policy=_policy(),
        budget=EvidenceBudget(1, 1, 100), embedding=embedding, include_diagnostics=True,
        keywords=keywords,
    )
    assert context.groups == context.diagnostics == ()
