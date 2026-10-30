import unicodedata
from dataclasses import replace
from itertools import count
from typing import Literal
from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import SourceLocation
from ai_workshop.labs.rag.executions import operation_timings
from ai_workshop.labs.rag.executions.domain import (
    ExecutionIdentity,
    ExecutionOutcome,
    StageObservation,
)
from ai_workshop.labs.rag.executions.observer import ExecutionObserver, observed_call
from ai_workshop.labs.rag.highlighting import service
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget, select_context
from ai_workshop.labs.rag.highlighting.domain import (
    AnswerStatus,
    ConflictState,
    EvidenceSelection,
)
from tests.unit.labs.rag.highlighting.test_evidence_selector import (
    RepeatingEmbedding,
    _policy,
    _source,
)

EVIDENCE_ID = UUID(int=10)
LOCATION = SourceLocation(
    element_id=UUID(int=11), char_start=20, char_end=100, page=None, bbox=None,
)
EMPTY = EvidenceSelection(AnswerStatus.INSUFFICIENT_EVIDENCE, None, ConflictState.NONE, ())


@pytest.mark.parametrize(
    ("query", "text", "coverage", "spans"),
    [
        ("CAFÉ", "Cafe\u0301 noir", 1.0, ((20, 25, "Cafe\u0301"),)),
        ("가", "\u1100\u1161 환매", 1.0, ((20, 22, "\u1100\u1161"),)),
        ("ffi", "\ufb03 file", 1.0, ((20, 21, "\ufb03"),)),
        ("STRASSE", "Straße", 1.0, ((20, 26, "Straße"),)),
        ("s", "ß", 1.0, ((20, 21, "ß"), (20, 21, "ß"))),
        ("i", "\u0130", 1.0, ((20, 21, "\u0130"),)),
        ("à", "a\u0315\u0300", 1.0, ((20, 23, "a\u0315\u0300"),)),
        ("foo bar", "\tＦＯＯ\u3000\nbar\r ", 1.0,
         ((21, 24, "ＦＯＯ"), (26, 29, "bar"))),
        ("Straße STRASSE missing", "Straße", 0.5, ((20, 26, "Straße"),)),
        ("art", "partial art", 1.0, ((21, 24, "art"), (28, 31, "art"))),
        ("aa", "aaa", 1.0, ((20, 22, "aa"),)),
        ("% 50", "５０％", 1.0, ((20, 22, "５０"), (22, 23, "％"))),
        ("", "synthetic", 0.0, ()),
        (" .!? \t", "synthetic", 0.0, ()),
        ("text", "", 0.0, ()),
    ],
)
def test_matcher_preserves_normalized_substrings_and_original_spans(
    query: str,
    text: str,
    coverage: float,
    spans: tuple[tuple[int, int, str], ...],
) -> None:
    matcher = service.KeywordMatcher(query)

    assert matcher.coverage(text) == coverage
    result = matcher.highlights(text, LOCATION, EVIDENCE_ID)

    assert result.coverage == coverage
    assert tuple((span.char_start, span.char_end, span.text) for span in result.highlights) == spans


@pytest.mark.parametrize(
    ("text", "normalized"),
    [("\t ＦＯＯ\u3000\nbar\r ", " foo bar "), ("\t\u2003\n", " "), ("", "")],
)
def test_fast_normalization_preserves_leading_and_trailing_whitespace(
    text: str, normalized: str,
) -> None:
    assert service._normalize_text(text) == normalized


def test_coverage_normalizes_each_unique_text_once_without_offsets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_normalize = unicodedata.normalize
    normalized_inputs: list[str] = []

    def record_normalize(form: Literal["NFC", "NFD", "NFKC", "NFKD"], text: str) -> str:
        normalized_inputs.append(text)
        return original_normalize(form, text)

    def forbid_offsets(text: str) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
        pytest.fail("Coverage must not construct original offsets.")

    monkeypatch.setattr(unicodedata, "normalize", record_normalize)
    monkeypatch.setattr(service, "_normalize_with_original_offsets", forbid_offsets)
    matcher = service.KeywordMatcher("CAFÉ")

    assert matcher.coverage("Cafe\u0301 plain") == 1.0
    assert matcher.coverage("Cafe\u0301 plain") == 1.0
    assert matcher.coverage("CAFÉ") == 1.0
    assert normalized_inputs == ["CAFÉ", "Cafe\u0301 plain"]


def test_same_text_reuses_offsets_but_uses_each_calls_location_and_evidence_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_offsets = service._normalize_with_original_offsets
    offset_inputs: list[str] = []

    def record_offsets(text: str) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
        offset_inputs.append(text)
        return original_offsets(text)

    monkeypatch.setattr(service, "_normalize_with_original_offsets", record_offsets)
    matcher = service.KeywordMatcher("STRASSE")
    first = matcher.highlights("Straße", LOCATION, EVIDENCE_ID)
    pdf_location = replace(
        LOCATION, char_start=70, char_end=76, page=3, bbox=(1.0, 2.0, 3.0, 4.0),
    )
    second = matcher.highlights("Straße", pdf_location, UUID(int=12))

    assert offset_inputs == ["Straße"]
    assert [(span.char_start, span.char_end, span.evidence_unit_id, span.bbox)
            for span in first.highlights] == [(20, 26, EVIDENCE_ID, None)]
    assert [(span.char_start, span.char_end, span.evidence_unit_id, span.page, span.bbox)
            for span in second.highlights] == [(70, 76, UUID(int=12), 3, pdf_location.bbox)]


def test_new_matcher_recomputes_query_and_body_instead_of_sharing_request_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_normalize = unicodedata.normalize
    normalized_inputs: list[str] = []

    def record_normalize(form: Literal["NFC", "NFD", "NFKC", "NFKD"], text: str) -> str:
        normalized_inputs.append(text)
        return original_normalize(form, text)

    monkeypatch.setattr(unicodedata, "normalize", record_normalize)

    for _ in range(2):
        assert service.KeywordMatcher("plain").coverage("plain body") == 1.0

    assert normalized_inputs == ["plain", "plain body", "plain", "plain body"]


def test_context_coverage_does_not_compute_offsets_even_for_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_offsets(text: str) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
        pytest.fail("Context coverage must not construct original offsets.")

    monkeypatch.setattr(service, "_normalize_with_original_offsets", forbid_offsets)
    source = _source(1, "plain synthetic body")

    result = select_context(
        query="plain", sources=(source,), extractive=EMPTY, policy=_policy(),
        budget=EvidenceBudget(1, 1, 100), embedding=RepeatingEmbedding(),
        include_diagnostics=True,
    )

    assert result.groups[0].units == source.chunk.evidence_units
    assert [item.keyword_coverage for item in result.diagnostics] == [1.0, 1.0]


def test_shared_matcher_keeps_conflicts_and_context_budget_without_repeating_offsets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = "최소 가입 금액"
    sources = (_source(1, "최소 가입 금액은 100만원입니다."),
               _source(2, "최소 가입 금액은 200만원입니다."))
    original_offsets = service._normalize_with_original_offsets
    offset_inputs: list[str] = []

    def record_offsets(text: str) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
        offset_inputs.append(text)
        return original_offsets(text)

    monkeypatch.setattr(service, "_normalize_with_original_offsets", record_offsets)
    matcher = service.KeywordMatcher(query)
    extractive = service.EvidenceSelector(RepeatingEmbedding()).select(
        query=query, sources=sources, policy=_policy(), keywords=matcher,
    )
    result = select_context(
        query=query, sources=sources, extractive=extractive, policy=_policy(),
        budget=EvidenceBudget(1, 1, 100), embedding=RepeatingEmbedding(),
        include_diagnostics=True, keywords=matcher,
    )

    assert extractive.answer is not None
    assert extractive.answer.source == sources[0]
    assert [answer.source for answer in extractive.conflicts] == [sources[1]]
    assert result.groups == ()
    assert result.blocked_reason == "conflict_context_budget_exceeded"
    assert not any(item.selected for item in result.diagnostics)
    assert offset_inputs == ["최소 가입 금액은 100만원입니다.", "최소 가입 금액은 200만원입니다."]


@pytest.mark.parametrize("query", ["different", "PLAIN", "plain "])
def test_extract_and_context_reject_matcher_from_different_query(query: str) -> None:
    matcher = service.KeywordMatcher("plain")

    with pytest.raises(ValueError, match="query"):
        service.EvidenceSelector(RepeatingEmbedding()).select(
            query=query, sources=(), policy=_policy(), keywords=matcher,
        )
    with pytest.raises(ValueError, match="query"):
        select_context(
            query=query, sources=(), extractive=EMPTY, policy=_policy(),
            budget=EvidenceBudget(1, 1, 100), embedding=RepeatingEmbedding(),
            include_diagnostics=False, keywords=matcher,
        )


class _StageRecorder:
    def __init__(self) -> None:
        self.rows: list[StageObservation] = []

    async def start(self, identity: ExecutionIdentity) -> None:
        pass

    async def record(self, execution_id: UUID, observation: StageObservation) -> None:
        self.rows.append(observation)

    async def finish(self, execution_id: UUID, outcome: ExecutionOutcome) -> None:
        pass


@pytest.mark.asyncio
async def test_keyword_timings_count_actual_and_reused_work_without_changing_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = count(0.0, 0.1)
    monkeypatch.setattr(operation_timings, "perf_counter", lambda: next(ticks))
    recorder = _StageRecorder()
    observer = ExecutionObserver(
        ExecutionIdentity(actor_id=UUID(int=20), turn_id=UUID(int=21)), recorder,
    )

    async def run() -> None:
        await observer.begin("selection")
        matcher = service.KeywordMatcher("STRASSE")
        assert matcher.coverage("Straße") == matcher.coverage("Straße") == 1.0
        first = matcher.highlights("Straße", LOCATION, EVIDENCE_ID)
        repeated = matcher.highlights("Straße", LOCATION, EVIDENCE_ID)
        assert first == repeated
        assert [(span.char_start, span.char_end) for span in first.highlights] == [(20, 26)]
        await observer.end("selection")

    await observed_call(run(), observer)
    assert recorder.rows[-1].operations is not None
    operations = {item.name: item for item in recorder.rows[-1].operations}
    assert set(operations) == {"keyword.normalize", "keyword.offsets"}
    normalization = operations["keyword.normalize"]
    assert (normalization.calls, normalization.items, normalization.reused_items) == (5, 5, 3)
    assert normalization.duration_ms == pytest.approx(500)
    offsets = operations["keyword.offsets"]
    assert (offsets.calls, offsets.items, offsets.reused_items) == (2, 2, 1)
    assert offsets.duration_ms == pytest.approx(200)
