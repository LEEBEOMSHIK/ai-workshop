"""Verbatim public synthetic source frozen in run e0331df7 (no DB/model required)."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget, select_context
from ai_workshop.labs.rag.highlighting.domain import EvidenceSource
from ai_workshop.labs.rag.highlighting.table_context import payment_table_units
from ai_workshop.labs.rag.retrieval.domain import RetrievedChunk
from tests.unit.labs.rag.highlighting.test_context import EMPTY
from tests.unit.labs.rag.highlighting.test_evidence_selector import _policy
from tests.unit.labs.rag.highlighting.test_table_context import LowScores, choose, expected_units

STORED_QUERY = "AM-SYN-101을 현금화하면 돈은 며칠 뒤 받을 수 있어?"
FIXTURE = Path(__file__).parents[4] / "fixtures/rag/stored_payment_table.json"


def test_fixture_matches_frozen_synthetic_source():
    # Canonical source digest captured by a read-only snapshot query; insensitive
    # to checkout line endings, but includes every original ID, text and bbox.
    data = json.loads(FIXTURE.read_text(encoding="utf8"))
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode()).hexdigest() == (
        "573df69f23f6cc7fc29dc2f3c2e453813ec97269de1db9a1a372e71b37903673")


def stored_source():
    data = json.loads(FIXTURE.read_text(encoding="utf8"))
    chunk_id, projection_id = UUID(data["chunk_id"]), UUID(data["projection_id"])
    units = tuple(EvidenceUnit(
        id=UUID(u["id"]), chunk_id=chunk_id, projection_id=projection_id,
        ordinal=u["ordinal"], text=u["text"], location=SourceLocation(
            UUID(u["element_id"]), u["page"], u["char_start"], u["char_end"], tuple(u["bbox"])))
        for u in data["evidence_units"])
    return EvidenceSource(
        document_id=UUID(data["document_id"]), asset_version_number=data["asset_version_number"],
        media_type=data["media_type"], fused_score=1.0, chunk=RetrievedChunk(
            chunk_id=chunk_id, projection_id=projection_id,
            asset_version_id=UUID(data["asset_version_id"]),
            workspace_id=UUID(data["workspace"]["id"]), folder_id=None,
            index_build_id=UUID(data["index_build_id"]), title=data["title"],
            section_path=tuple(data["section_path"]), text=data["chunk_text"],
            evidence_units=units))


def with_units(source, units):
    return replace(source, chunk=replace(source.chunk, evidence_units=tuple(units)))


@pytest.mark.parametrize("diagnostics", [False, True])
def test_stored_source_selects_original_payout_and_preserves_every_condition(diagnostics):
    source = stored_source()
    result = choose(source, query=STORED_QUERY, diagnostics=diagnostics)
    assert len(result.groups) == 1
    selected = result.groups[0].units
    assert selected == expected_units(source)
    assert len(selected) == 28
    assert all(unit is original for unit, original in zip(
        selected, expected_units(source), strict=True))
    # All outside-table text survives, including the split "does not apply",
    # date example, missing-calendar warning, disclaimer, and page number.
    outside = source.chunk.evidence_units[:6] + source.chunk.evidence_units[21:]
    assert tuple(u for u in selected if u.ordinal < 6 or u.ordinal > 20) == outside
    payout = source.chunk.evidence_units[19]
    assert payout.id == UUID("25b7b690-dd81-440e-9bd8-1e1020823e65")
    assert payout.text == "접수일 T+4 영업일"
    assert payout in selected
    assert result.observations[0].reason == "structured_table_selected"


@pytest.mark.parametrize("ordinal,text", [
    (19, "AM-SYN-202의 지급일 참조"),
    (23, "AM-SYN-101의 지급일은 다른 상품과 동일하다."),
    (30, "위 표의 우측 지급일을 참조한다."),
])
def test_stored_other_product_references_prevent_projection(ordinal, text):
    source = stored_source()
    units = list(source.chunk.evidence_units)
    units[ordinal] = replace(units[ordinal], text=text)
    source = with_units(source, units)
    assert payment_table_units(STORED_QUERY, source, tuple(units)) is None
    assert choose(source, query=STORED_QUERY).groups == ()


@pytest.mark.parametrize("ordinal", [6, 7, 8, 10, 19])
def test_stored_incomplete_header_or_table_is_not_repaired(ordinal):
    source = stored_source()
    source = with_units(source, [u for u in source.chunk.evidence_units if u.ordinal != ordinal])
    assert choose(source, query=STORED_QUERY).groups == ()


@pytest.mark.parametrize("limit", [27, 28])
def test_stored_bundle_remains_indivisible_at_budget_boundary(limit):
    source = stored_source()
    result = choose(source, query=STORED_QUERY, budget=EvidenceBudget(1, limit, 12000))
    assert bool(result.groups) is (limit == 28)


def test_stored_other_target_preserves_its_payout_and_all_exceptions():
    source = stored_source()
    selected = choose(source, query=STORED_QUERY.replace("101", "202")).groups[0].units
    assert selected == tuple(u for u in source.chunk.evidence_units
                             if u.ordinal not in {7, 10, 13, 16, 19})
    assert source.chunk.evidence_units[20].text == "접수일 T+7 영업일"


@pytest.mark.parametrize("scale,dx,dy", [(0.5, 30.0, 70.0), (2.0, 100.0, 150.0)])
def test_footer_recognition_does_not_depend_on_absolute_coordinates(scale, dx, dy):
    source = stored_source()
    units = []
    for unit in source.chunk.evidence_units:
        x0, y0, x1, y1 = unit.location.bbox
        units.append(replace(unit, location=replace(unit.location, bbox=(
            x0*scale+dx, y0*scale+dy, x1*scale+dx, y1*scale+dy))))
    source = with_units(source, units)
    assert choose(source, query=STORED_QUERY).groups[0].units == expected_units(source)


def test_ambiguous_footer_keeps_ordinary_whole_chunk_selection():
    source = stored_source()
    units = list(source.chunk.evidence_units)
    units[32] = replace(units[32], text="결제 비율 02 / 03")
    source = with_units(source, units)
    result = select_context(query=STORED_QUERY, sources=(source,), extractive=EMPTY,
        policy=_policy(min_semantic_score=0.8), budget=EvidenceBudget(1, 33, 12000),
        embedding=LowScores(), include_diagnostics=True)
    assert result.groups[0].units == tuple(units)
    assert result.observations[0].reason == "selected"


@pytest.mark.parametrize("mutation", [
    "not_page_number", "wrong_page", "impossible_total", "zero_page", "embedded_number",
    "overlapping_footer", "table_aligned_footer", "number_in_table_column",
    "body_sized_footer", "close_to_body", "nonterminal_footer",
    "resumed_two_cells", "resumed_three_cells", "second_table",
])
def test_stored_ambiguous_trailing_rows_stay_ineligible(mutation):
    source = stored_source()
    units = list(source.chunk.evidence_units)
    text_changes = {"not_page_number": "접수일 T+7 영업일", "wrong_page": "01 / 03",
                    "impossible_total": "02 / 01", "zero_page": "00 / 03",
                    "embedded_number": "결제 비율 02 / 03"}
    if mutation in text_changes:
        units[32] = replace(units[32], text=text_changes[mutation])
    elif mutation == "nonterminal_footer":
        units.append(replace(units[30], id=UUID(int=9090), ordinal=33,
            location=replace(units[30].location, bbox=(42.0, 830.0, 300.0, 844.0))))
    elif mutation in {"resumed_two_cells", "resumed_three_cells", "second_table"}:
        count = 2 if mutation == "resumed_two_cells" else 3
        original = units[6:6 + count] if mutation == "second_table" else units[18:18 + count]
        extra = [replace(u, id=UUID(int=9100+i), ordinal=31+i,
            location=replace(u.location, bbox=(u.location.bbox[0], 720.0,
                                               u.location.bbox[2], 732.0)))
                 for i, u in enumerate(original)]
        units[31:] = extra + [replace(u, ordinal=u.ordinal+count) for u in units[31:]]
    else:
        if mutation == "overlapping_footer":
            units[32] = replace(units[32], location=replace(
                units[32].location, bbox=(200.0, 800.2960205078125, 528.0, 810.927978515625)))
        elif mutation == "table_aligned_footer":
            units[31] = replace(units[31], location=replace(
                units[31].location, bbox=(51.0, 800.2960205078125, 236.8, 810.927978515625)))
        elif mutation == "number_in_table_column":
            units[32] = replace(units[32], location=replace(
                units[32].location, bbox=(362.0, 800.2960205078125, 390.0, 810.927978515625)))
        elif mutation == "body_sized_footer":
            for i in (31, 32):
                b = units[i].location.bbox
                units[i] = replace(units[i], location=replace(
                    units[i].location, bbox=(b[0], b[1], b[2], b[1]+16.0)))
        elif mutation == "close_to_body":
            for i in (31, 32):
                b = units[i].location.bbox
                units[i] = replace(units[i], location=replace(
                    units[i].location, bbox=(b[0], 670.0, b[2], 680.63195703125)))
    source = with_units(source, units)
    assert payment_table_units(STORED_QUERY, source, tuple(units)) is None
    assert choose(source, query=STORED_QUERY).groups == ()
