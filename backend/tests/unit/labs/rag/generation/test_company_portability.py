"""Synthetic company substitution: transport/selection contracts, not model quality or ACL.

Both companies use the same product and question. No live model, DB, or network
is involved; company names below are document content, never tenant identities.
Only existing untyped fixture helper calls have targeted type-check exemptions.
"""

import json
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.evidence_payload import evidence_payload
from ai_workshop.labs.rag.generation.openai_compatible import _generation_user_content
from ai_workshop.labs.rag.generation.source_reading import build_source_reading
from ai_workshop.labs.rag.highlighting.domain import EvidenceAnswer, EvidenceSource
from ai_workshop.labs.rag.search.pipeline import _grounding_evidence
from tests.unit.labs.rag.generation.test_http_evidence_groups import restore
from tests.unit.labs.rag.generation.test_source_reading import request_for, source_units
from tests.unit.labs.rag.generation.test_source_reading_mock import (
    MockBoundaryRuntime,
    complete_without_io,
)
from tests.unit.labs.rag.highlighting.test_table_context import choose, table_source

QUESTION = "COMMON-17을 현금화하면 돈은 며칠 뒤 받을 수 있어?"


def company_table(company: str, days: int, cutoff: str) -> EvidenceSource:
    source: EvidenceSource = table_source()  # type: ignore[no-untyped-call]
    identity = 90100 if company == "A" else 90200
    chunk = replace(source.chunk, workspace_id=UUID(int=identity),
                    asset_version_id=UUID(int=identity + 1),
                    projection_id=UUID(int=identity + 2), chunk_id=UUID(int=identity + 3),
                    index_build_id=UUID(int=identity + 4))
    units = []
    offset = 0
    for unit in source.chunk.evidence_units:
        text = unit.text.replace("ORCHID-71", "COMMON-17")
        if unit.ordinal == 0:
            text = f"합성 업체 {company} 상품 안내"
        elif unit.ordinal == 4:
            text = f"{cutoff} 이후 신청은 다음 영업일 접수다."
        elif unit.ordinal == 10:
            text = cutoff
        elif unit.ordinal == 19:
            text = f"접수일 T+{days} 영업일"
        units.append(replace(unit, text=text, id=UUID(int=identity + 10 + unit.ordinal),
                             chunk_id=chunk.chunk_id, projection_id=chunk.projection_id,
                             location=replace(unit.location,
                                              element_id=UUID(int=identity + 50 + unit.ordinal),
                                              char_start=offset, char_end=offset + len(text))))
        offset += len(text)
    return replace(source, document_id=UUID(int=901 if company == "A" else 902),
                   chunk=replace(chunk, text="\n".join(u.text for u in units),
                                 evidence_units=tuple(units)))


@pytest.mark.parametrize("reference", ["rag-answer-v3", "rag-answer-v4"])
def test_same_question_and_prompt_transmit_each_company_rule_and_conditions(reference: str) -> None:
    prompts = []
    for company, days, cutoff in [("A", 2, "10시"), ("B", 11, "16시")]:
        source = company_table(company, days, cutoff)
        selected = choose(source, query=QUESTION)  # type: ignore[no-untyped-call]
        assert selected.observations[0].reason == "structured_table_selected"
        expected = tuple(u for u in source.chunk.evidence_units
                         if u.ordinal not in {8, 11, 14, 17, 20})
        assert selected.groups[0].units == expected
        items = _grounding_evidence(tuple(
            EvidenceAnswer(source, unit, "", (), None, None) for unit in expected))
        request = request_for(items, question=QUESTION, reference=reference)
        runtime = MockBoundaryRuntime(request, {
            "schema_version": 2, "status": "insufficient_evidence", "claims": []})
        # This authored empty response cannot establish a model's answer accuracy.
        result = complete_without_io(runtime, request)
        assert result.generation is None
        body = runtime.sent[0]
        prompts.append(body["messages"][0]["content"])
        payload = json.loads(body["messages"][1]["content"])
        assert payload["question"] == payload["resolved_query"] == QUESTION
        assert restore(payload) == evidence_payload(items, contextual=True)  # type: ignore[no-untyped-call]
        assert {e["document_id"] for e in restore(payload)} == {str(source.document_id)}  # type: ignore[no-untyped-call]
        texts = [e["text"] for e in payload["evidence"]]
        assert f"접수일 T+{days} 영업일" in texts
        assert f"{cutoff} 이후 신청은 다음 영업일 접수다." in texts
        assert "이 예외는 COMMON-17에는 적용하지" in texts
        assert texts[texts.index("이 예외는 COMMON-17에는 적용하지") + 1] == "않는다."
        assert "접수일 T+9 영업일" not in texts  # Explicitly omitted other product column.
        assert "접수일 T+4 영업일" not in texts
    assert prompts[0] == prompts[1]


@pytest.mark.parametrize("days", [1, 4, 23, 108])
def test_table_numeric_substitution_uses_source_value_without_answer_constants(days: int) -> None:
    source = company_table("B", days, "17시")
    units = choose(source, query=QUESTION).groups[0].units  # type: ignore[no-untyped-call]
    assert next(u for u in units if u.ordinal == 19).text == f"접수일 T+{days} 영업일"
    assert all(any(u is original for original in source.chunk.evidence_units) for u in units)


@pytest.mark.parametrize(("additional", "use_projection"), [
    ("COMMON-17은 접수일 T+12 영업일 지급이다.", True),
    ("OTHER-88의 사례: 2031-02-03 신청, 2031-02-06 지급.", True),
    ("COMMON-17은 같은 조건에서 접수일 T+12 영업일 지급이다.", False),
])
def test_table_selection_preserves_prose_or_declines_reference_wording(
    additional: str, use_projection: bool,
) -> None:
    source = company_table("A", 2, "10시")
    changed = []
    offset = 0
    for unit in source.chunk.evidence_units:
        text = additional if unit.ordinal == 21 else unit.text
        changed.append(replace(unit, text=text, location=replace(
            unit.location, char_start=offset, char_end=offset + len(text))))
        offset += len(text)
    units = tuple(changed)
    source = replace(source, chunk=replace(source.chunk, evidence_units=units,
                                          text="\n".join(u.text for u in units)))
    selected = choose(source, query=QUESTION)  # type: ignore[no-untyped-call]
    if not use_projection:
        # The lexical reference guard treats "같은" as potentially cross-column.
        # The low-score fixture cannot qualify for ordinary whole-chunk selection.
        assert selected.groups == ()
        return
    expected = tuple(u for u in units if u.ordinal not in {8, 11, 14, 17, 20})
    assert selected.groups[0].units == expected
    items = _grounding_evidence(tuple(
        EvidenceAnswer(source, u, "", (), None, None) for u in expected))
    payload = json.loads(_generation_user_content(request_for(items, question=QUESTION)))
    assert restore(payload) == evidence_payload(items, contextual=True)  # type: ignore[no-untyped-call]
    assert additional in [e["text"] for e in payload["evidence"]]
    assert "접수일 T+2 영업일" in [e["text"] for e in payload["evidence"]]
    # Preserving both statements is not semantic conflict detection or resolution.


@pytest.mark.parametrize("texts", [
    ["합성 업체 A: COMMON-17 안내", "지급 시점은 이 문서에서 정하지 않는다."],
    ["합성 업체 B: COMMON-17은 접수일 T+3 영업일 지급이다.",
     "COMMON-17은 같은 조건에서 접수일 T+12 영업일 지급이다."],
    ["합성 업체 A: COMMON-17은 접수일 T+23 영업일 지급이다.",
     "다른 상품 OTHER-88의 예시: 2031-02-03 신청 후 2031-02-06 지급."],
    ["합성 업체 B: OTHER-88의 예시만 있다.", "COMMON-17의 일반 지급 규칙은 없다."],
])
@pytest.mark.parametrize("reference", ["rag-answer-v3", "rag-answer-v4"])
def test_absent_conflicting_and_unrelated_rules_are_neither_rewritten_nor_resolved(
    texts: list[str], reference: str,
) -> None:
    items = source_units(texts)
    payload = json.loads(_generation_user_content(
        request_for(items, question=QUESTION, reference=reference)))
    assert restore(payload) == evidence_payload(items, contextual=True)  # type: ignore[no-untyped-call]
    assert [e["text"] for e in payload["evidence"]] == texts
    assert "claims" not in payload and "answer" not in payload
    if reference == "rag-answer-v4":
        assert payload["source_reading"]["semantic_roles"] == "not_assigned"
    # Deliberately no assertion that the model can resolve conflict or abstain.


def test_document_boundaries_do_not_filter_companies_out_of_generation_input() -> None:
    a = source_units(["업체 A 일반 규칙", "접수일 T+2 영업일"])
    b = tuple(replace(item, document_id=UUID(int=902), evidence_id=UUID(int=500 + i))
              for i, item in enumerate(source_units(["업체 B 일반 규칙", "접수일 T+11 영업일"])))
    mixed = (*a, *b)
    guide = build_source_reading(mixed)
    assert guide["contiguous_spans"] == [
        [str(e.evidence_id) for e in a], [str(e.evidence_id) for e in b]]
    payload = json.loads(_generation_user_content(request_for(mixed, question=QUESTION)))
    assert restore(payload) == evidence_payload(mixed, contextual=True)  # type: ignore[no-untyped-call]
    assert len(payload["evidence"]) == 4
    # Reading hints are not ACL enforcement: both supplied documents remain visible.


@pytest.mark.parametrize("change", ["missing_rule", "unrecognized_label"])
def test_payment_specific_route_is_not_general_table_understanding(change: str) -> None:
    source = company_table("A", 2, "10시")
    if change == "missing_rule":
        units = tuple(u for u in source.chunk.evidence_units if u.ordinal not in {18, 19, 20})
    else:
        units = tuple(replace(u, text="지급 일정") if u.ordinal == 18 else u
                      for u in source.chunk.evidence_units)
    source = replace(source, chunk=replace(source.chunk, evidence_units=units))
    selected: Any = choose(source, query=QUESTION)  # type: ignore[no-untyped-call]
    # Under the fixture's low semantic score, unknown vocabulary is not promoted.
    # A whole chunk could still qualify under the ordinary scoring route.
    assert selected.groups == ()
