"""Public synthetic tables: select relationships, never invent an answer or a cell."""

from dataclasses import replace
from math import sqrt
from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import SourceLocation, TableCellLocation
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget, select_context
from ai_workshop.labs.rag.highlighting.domain import EvidenceAnswer
from tests.unit.labs.rag.highlighting.test_context import EMPTY, ContextEmbedding
from tests.unit.labs.rag.highlighting.test_evidence_selector import _policy, _source

QUERY = "ORCHID-71을 현금화하면 돈은 며칠 뒤 받을 수 있어?"


class LowScores(ContextEmbedding):
    def encode_documents(self, texts):
        return [[0.87, sqrt(1 - 0.87**2)] for _ in texts]


def table_source():
    source = _source(71, "synthetic")
    template = source.chunk.evidence_units[0]
    prefix = ["합성 상품 안내", "환매 신청 및 대금 지급", "영업일 기준 안내",
              "T는 접수일이다.", "마감 후 신청은 다음 영업일 접수다.", "아래 표를 참고한다."]
    rows = [("항목", "ORCHID-71", "CEDAR-82"),
            ("신청 마감", "15시", "14시"),
            ("마감 후 신청", "다음 영업일 접수", "다음 영업일 접수"),
            ("적용 기준가격", "접수일 T+2", "접수일 T+3"),
            ("대금 지급일", "접수일 T+6 영업일", "접수일 T+9 영업일")]
    suffix = ["지급 시점의 예외", "CEDAR-82는 휴장 시 결제가 지연된다.",
              "이 예외는 ORCHID-71에는 적용하지", "않는다.", "계산 안내",
              "접수일을 기준으로 계산한다.", "정보가 없는 경우", "달력 날짜를 추측하지 않는다.",
              "조건 확인이 필요하다.", "합성 자료이며 실제 상품이 아니다.", "안내 끝", "1 / 1"]
    cells = [(text, (10.0, float(i * 15), 450.0, float(i * 15 + 10)))
             for i, text in enumerate(prefix)]
    for r, row in enumerate(rows):
        for col, text in enumerate(row):
            left = (20.0, 180.0, 350.0)[col]
            cells.append((text, (left, 120.0 + r * 20, left + 100, 130.0 + r * 20)))
    cells += [(text, (10.0, 240.0 + i * 15, 450.0, 250.0 + i * 15))
              for i, text in enumerate(suffix)]
    units = tuple(replace(template, id=UUID(int=7100 + i), ordinal=i, text=text,
                         location=SourceLocation(UUID(int=8100 + i), 1, i * 100,
                                                 i * 100 + len(text), bbox))
                  for i, (text, bbox) in enumerate(cells))
    assert len(units) == 33
    return replace(source, media_type="application/pdf", chunk=replace(
        source.chunk, text="\n".join(u.text for u in units), evidence_units=units))


def expected_units(source):
    # The other product column is removed, including its header. All surrounding
    # prose and row labels survive, including the split negative exception.
    excluded = {8, 11, 14, 17, 20}
    return tuple(u for u in source.chunk.evidence_units if u.ordinal not in excluded)


def choose(source=None, *, query=QUERY, budget=None, diagnostics=True, sources=None):
    return select_context(query=query, sources=sources or (source or table_source(),),
                          extractive=EMPTY, policy=_policy(min_semantic_score=0.9),
                          budget=budget or EvidenceBudget(8, 32, 12000),
                          embedding=LowScores(), include_diagnostics=diagnostics)


@pytest.mark.parametrize("diagnostics", [False, True])
def test_payment_timing_uses_exact_target_column_without_changing_scores(diagnostics):
    source = table_source()
    result = choose(source, diagnostics=diagnostics)
    assert len(result.groups) == 1
    assert result.groups[0].units == expected_units(source)
    assert all(u is original for u, original in zip(
        result.groups[0].units, expected_units(source), strict=True))
    observation = result.observations[0]
    assert observation.semantic_score == pytest.approx(0.87)
    assert observation.keyword_coverage < 0.5
    assert observation.reason == "structured_table_selected"
    assert observation.budget_trace.incoming_units == 28


def test_structured_selection_diagnostics_only_mark_transmitted_units():
    source = table_source()
    result = choose(source)
    transmitted = {u.id for u in expected_units(source)}
    selected_ids = {d.evidence_id for d in result.diagnostics if d.evidence_id and d.selected}
    assert selected_ids == transmitted
    assert len([d for d in result.diagnostics if d.evidence_id and not d.selected]) == 5
    texts = [u.text for u in result.groups[0].units]
    assert "접수일 T+6 영업일" in texts
    assert "접수일 T+9 영업일" not in texts
    assert texts[texts.index("이 예외는 ORCHID-71에는 적용하지") + 1] == "않는다."


@pytest.mark.parametrize("query", [
    "CEDAR-82를 환매하면 대금을 언제 받을 수 있나요?",
    "When will I receive payment after redeeming CEDAR-82?",
])
def test_another_target_and_language_do_not_borrow_first_product_values(query):
    result = choose(query=query)
    assert len(result.groups) == 1
    texts = [u.text for u in result.groups[0].units]
    assert "접수일 T+9 영업일" in texts and "접수일 T+6 영업일" not in texts


@pytest.mark.parametrize("query", [
    "ORCHID-710을 현금화하면 돈을 언제 받을 수 있나요?",
    "UNKNOWN-19를 현금화하면 돈은 며칠 뒤 받을 수 있어?",
    "ORCHID-71의 다음 달 확정 수익률은 얼마야?",
    "ORCHID-71을 현금화하면 수수료는 얼마야?",
    "ORCHID-71의 가격을 알려 줘",
    "ORCHID-71과 CEDAR-82를 환매하면 돈은 언제 받을 수 있나요?",
    "ORCHID-71을 환매하지 않으면 돈을 언제 받을 수 있나요?",
    "ORCHID-71과 다른 상품을 비교해서 환매 대금 지급일을 알려 줘",
    "돈을 언제 받을 수 있나요?",
])
def test_unsupported_ambiguous_or_unrelated_questions_do_not_gain_eligibility(query):
    assert choose(query=query).groups == ()


@pytest.mark.parametrize("removed", [6, 7, 10, 18, 19])
def test_missing_header_label_or_cell_is_not_reconstructed(removed):
    source = table_source()
    source = replace(source, chunk=replace(source.chunk, evidence_units=tuple(
        u for u in source.chunk.evidence_units if u.ordinal != removed)))
    assert choose(source).groups == ()


@pytest.mark.parametrize("mutation", [
    "duplicate_header", "duplicate_cell", "overlap", "nan", "zero",
    "missing_bbox", "page_split", "misaligned",
])
def test_ambiguous_table_geometry_does_not_gain_eligibility(mutation):
    source = table_source()
    units = list(source.chunk.evidence_units)
    if mutation == "duplicate_header":
        units[8] = replace(units[8], text=units[7].text)
    elif mutation == "duplicate_cell":
        units.append(replace(units[10], id=UUID(int=99999)))
    else:
        bbox = {"overlap": (180.0, 140.0, 400.0, 150.0),
                "nan": (float("nan"), 140.0, 280.0, 150.0),
                "zero": (180.0, 140.0, 180.0, 150.0),
                "missing_bbox": None, "misaligned": (190.0, 140.0, 290.0, 150.0)}
        location = replace(units[10].location, page=2) if mutation == "page_split" else replace(
            units[10].location, bbox=bbox[mutation])
        units[10] = replace(units[10], location=location)
    source = replace(source, chunk=replace(source.chunk, evidence_units=tuple(units)))
    assert choose(source).groups == ()


def test_budget_is_applied_to_complete_structured_bundle_without_further_trimming():
    source = table_source()
    size = sum(len(u.text) for u in expected_units(source))
    selected = choose(source, budget=EvidenceBudget(1, 28, size)).groups[0].units
    assert selected == expected_units(source)
    assert choose(source, budget=EvidenceBudget(1, 27, size)).groups == ()
    assert choose(source, budget=EvidenceBudget(1, 28, size - 1)).groups == ()


def test_duplicate_inputs_and_shuffled_units_preserve_exact_original_order():
    source = table_source()
    shuffled = replace(source, chunk=replace(source.chunk, evidence_units=(
        *reversed(source.chunk.evidence_units), source.chunk.evidence_units[0])))
    result = choose(sources=(shuffled, shuffled))
    assert len(result.groups) == 1
    assert result.groups[0].units == expected_units(source)


@pytest.mark.parametrize("as_conflict", [False, True])
def test_qualified_other_column_evidence_is_never_projected_away(as_conflict):
    source = table_source()
    answer = EvidenceAnswer(source, source.chunk.evidence_units[19], "", (), None, 1.0)
    other = EvidenceAnswer(source, source.chunk.evidence_units[20], "", (), None, 1.0)
    extractive = replace(EMPTY, answer=answer, conflicts=(other,) if as_conflict else (),
                         candidates=() if as_conflict else (other,))
    for limit in (32, 33):
        result = select_context(query=QUERY, sources=(source,), extractive=extractive,
                                policy=_policy(min_semantic_score=0.9),
                                budget=EvidenceBudget(1, limit, 12000),
                                embedding=LowScores(), include_diagnostics=True)
        if limit == 33:
            assert result.groups[0].units == source.chunk.evidence_units
            assert result.observations[0].reason == "selected"
        else:
            assert result.groups == ()
            assert not any(d.selected for d in result.diagnostics)
            if as_conflict:
                assert result.blocked_reason == "conflict_context_budget_exceeded"


def test_projection_respects_cumulative_budget_with_other_sources():
    table = table_source()
    first = _source(1, QUERY)
    result = choose(sources=(first, table), budget=EvidenceBudget(2, 28, 12000))
    assert [g.source for g in result.groups] == [first]
    observation = next(o for o in result.observations if o.chunk_id == table.chunk.chunk_id)
    assert observation.reason == "budget_exceeded"
    assert observation.budget_trace.before_units == 1
    assert observation.budget_trace.incoming_units == 28
    assert observation.budget_trace.violated == ("units",)


def test_structural_path_does_not_add_embedding_calls_or_replace_embedding_input():
    class RecordingEmbedding(LowScores):
        queries = []
        batches = []

        def encode_query(self, text):
            self.queries.append(text)
            return super().encode_query(text)

        def encode_documents(self, texts):
            self.batches.append(texts)
            return super().encode_documents(texts)

    source = table_source()
    embedding = RecordingEmbedding()
    result = select_context(query=QUERY, sources=(source,), extractive=EMPTY,
                            policy=_policy(min_semantic_score=0.9),
                            budget=EvidenceBudget(1, 32, 12000), embedding=embedding,
                            include_diagnostics=False)
    assert len(result.groups) == 1
    assert embedding.queries == [QUERY]
    assert len(embedding.batches) == 1
    assert len(embedding.batches[0]) == 1
    assert all(u.text in embedding.batches[0][0] for u in source.chunk.evidence_units)


@pytest.mark.parametrize("mutation", ["annotated", "non_pdf", "invalid_prose", "second_table"])
def test_unsupported_source_layout_keeps_existing_threshold_behavior(mutation):
    source = table_source()
    units = list(source.chunk.evidence_units)
    if mutation == "annotated":
        units[10] = replace(units[10], location=replace(
            units[10].location, table_cell=TableCellLocation(1, 1, column_span=2)))
    elif mutation == "non_pdf":
        source = replace(source, media_type="text/plain")
    elif mutation == "invalid_prose":
        units[-1] = replace(units[-1], location=replace(units[-1].location, bbox=None))
    else:
        units += [replace(u, id=UUID(int=9000 + i), ordinal=33 + i,
                          location=replace(u.location, bbox=(20.0 + i * 160, 500.0,
                                                             120.0 + i * 160, 510.0)))
                  for i, u in enumerate(units[6:9])]
    source = replace(source, chunk=replace(source.chunk, evidence_units=tuple(units)))
    assert choose(source).groups == ()


@pytest.mark.parametrize("query", [
    "ORCHID-71의 환매가 아닌 경우에도 현금화하면 돈은 며칠 뒤 받을 수 있어?",
    "ORCHID-71을 현금화해서 돈은 언제 받을 수 없는지 알려줘",
    "ORCHID-71을 현금화하면 돈은 언제 못 받을까?",
    "ORCHID-71을 현금화하면 돈은 언제 안받게 되나?",
])
def test_negative_payment_questions_do_not_use_positive_timing_route(query):
    assert choose(query=query).groups == ()


@pytest.mark.parametrize("reference", [
    "CEDAR-82와 동일", "오른쪽과 동일", "ditto", "same as above", "〃", "CEDAR-82 참조",
])
@pytest.mark.parametrize("position", [19, 21])
def test_references_to_omitted_values_keep_whole_chunk_or_reject(reference, position):
    source = table_source()
    units = list(source.chunk.evidence_units)
    units[position] = replace(units[position], text=reference)
    source = replace(source, chunk=replace(source.chunk, evidence_units=tuple(units)))
    assert choose(source).groups == ()
    # A qualifying whole chunk remains available; the new route must not trim it.
    result = select_context(query=QUERY, sources=(source,), extractive=EMPTY,
                            policy=_policy(min_semantic_score=0.8),
                            budget=EvidenceBudget(1, 33, 12000), embedding=LowScores(),
                            include_diagnostics=False)
    assert result.groups[0].units == source.chunk.evidence_units
    assert result.observations[0].reason == "selected"
