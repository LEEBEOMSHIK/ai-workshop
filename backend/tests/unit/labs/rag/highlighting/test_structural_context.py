"""Offline grid candidates: no inferred header roles, reference resolution or answer quality."""

import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation, TableCellLocation
from ai_workshop.labs.rag.generation.evidence_payload import evidence_payload
from ai_workshop.labs.rag.generation.openai_compatible import _generation_user_content
from ai_workshop.labs.rag.highlighting.context import (
    ContextSelection,
    EvidenceBudget,
    select_context,
)
from ai_workshop.labs.rag.highlighting.domain import AnswerPolicy, EvidenceAnswer, EvidenceSource
from ai_workshop.labs.rag.highlighting.structural_context import inspect_grid_candidate
from ai_workshop.labs.rag.search.pipeline import _grounding_evidence
from tests.unit.labs.rag.generation.test_http_evidence_groups import restore
from tests.unit.labs.rag.generation.test_source_reading import request_for
from tests.unit.labs.rag.highlighting.test_context import EMPTY, ContextEmbedding
from tests.unit.labs.rag.highlighting.test_evidence_selector import _source
from tests.unit.labs.rag.highlighting.test_table_context import table_source

DEFAULT_BUDGET = EvidenceBudget(2, 64, 12000)


class LowEmbedding(ContextEmbedding):
    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0, 1.0] for _ in texts]


def grid(
    *, annotated: bool = False, value: str = "23周期", name: str = "DEVICE-Ω",
    note: str = "同じ条件。別の表を参照。", transpose: bool = False, swap: bool = False,
) -> EvidenceSource:
    source = _source(811, "synthetic")
    rows = [("Specification", name, "OTHER-X"), ("Interval", value, "61 cycles"),
            ("Exception", "See note", "Not defined")]
    if swap:
        rows = [(r[2], r[0], r[1]) for r in rows]
    if transpose:
        rows = list(zip(*rows, strict=True))
    cells: list[tuple[str, tuple[float, float, float, float], TableCellLocation | None]] = [
        ("합성 업체의 운용 안내", (5.0, 1.0, 450.0, 10.0), None)]
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            cells.append((text, (20.0 + c * 150, 30.0 + r * 20,
                                 120.0 + c * 150, 40.0 + r * 20),
                          TableCellLocation(r, c) if annotated else None))
    cells.append((note, (5.0, 100.0, 450.0, 110.0), None))
    units = []
    offset = 0
    for i, (text, bbox, cell) in enumerate(cells):
        units.append(EvidenceUnit(
            UUID(int=81000 + i), source.chunk.chunk_id, i, text,
            SourceLocation(UUID(int=82000 + i), 1, offset, offset + len(text), bbox,
                           table_cell=cell), source.chunk.projection_id))
        offset += len(text)
    return replace(source, media_type="application/pdf", chunk=replace(
        source.chunk, text="\n".join(u.text for u in units), evidence_units=tuple(units)))


def select(source: EvidenceSource, *, query: str = "DEVICE-Ω explain unknown usage?",
           budget: EvidenceBudget = DEFAULT_BUDGET, high: bool = False) -> ContextSelection:
    return select_context(query=query, sources=(source,), extractive=EMPTY,
                          policy=AnswerPolicy(0.9, 1.0), budget=budget,
                          embedding=ContextEmbedding() if high else LowEmbedding(),
                          include_diagnostics=True, table_strategy="structure-v1")


@pytest.mark.parametrize("annotated", [False, True])
@pytest.mark.parametrize(("name", "value"), [("DEVICE-Ω", "23周期"), ("장비-나", "104시간")])
@pytest.mark.parametrize(("transpose", "swap"), [(False, False), (False, True), (True, False)])
def test_company_terms_values_column_order_and_orientation_preserve_full_chunk(
    annotated: bool, name: str, value: str, transpose: bool, swap: bool,
) -> None:
    source = grid(annotated=annotated, name=name, value=value, transpose=transpose, swap=swap)
    result = select(source, query=f"{name} explain unknown usage?")
    assert result.groups[0].units == source.chunk.evidence_units
    assert all(a is b for a, b in zip(result.groups[0].units, source.chunk.evidence_units,
                                     strict=True))
    observation = result.observations[0]
    assert observation.reason == "structural_grid_selected"
    assert observation.structure_reason == (
        "cell_coordinates_match" if annotated else "bbox_grid_match")
    assert observation.semantic_score == 0.0
    assert value in [u.text for u in result.groups[0].units]


@pytest.mark.parametrize("note", [
    "같은 조건에서만 적용한다.", "OTHER-X와 동일. 왼쪽 값을 참조한다.",
    "다른 페이지의 주석을 참조한다.", "일반 규칙은 없다. 예시만 제공한다.",
    "DEVICE-Ω의 주기는 99시간이다. 앞의 값과 상충한다.",
])
def test_notes_references_absent_rules_and_conflicts_are_preserved_not_interpreted(
    note: str,
) -> None:
    source = grid(note=note)
    result = select(source)
    assert result.groups[0].units == source.chunk.evidence_units
    items = _grounding_evidence(tuple(
        EvidenceAnswer(source, u, "", (), None, None) for u in result.groups[0].units))
    payload = json.loads(_generation_user_content(request_for(items)))
    assert restore(payload) == evidence_payload(items, contextual=True)  # type: ignore[no-untyped-call]
    assert payload["evidence"][-1]["text"] == note
    assert "answer" not in payload and "claims" not in payload


@pytest.mark.parametrize("query", [
    "DEVICE-Ω0", "PREDEVICE-Ω", "DEVICE-Ω를", "23 unmatched", "device paraphrase",
])
def test_partial_names_numbers_and_paraphrases_do_not_gain_structural_eligibility(
    query: str,
) -> None:
    result = select(grid(), query=query)
    assert result.groups == ()
    assert result.observations[0].structure_reason == "no_cell_match"


def test_numeric_keyword_can_still_qualify_via_ordinary_policy() -> None:
    result = select(grid(), query="23")
    assert len(result.groups) == 1
    assert result.observations[0].reason == "selected"
    assert result.observations[0].structure_reason == "no_cell_match"


@pytest.mark.parametrize("annotated", [False, True])
def test_translated_scaled_and_shuffled_layout_keeps_parser_order(annotated: bool) -> None:
    source = grid(annotated=annotated)
    units = []
    for unit in source.chunk.evidence_units:
        box = unit.location.bbox
        assert box is not None
        transformed = (box[0] * 2.0 + 70.0, box[1] * 2.0 + 19.0,
                       box[2] * 2.0 + 70.0, box[3] * 2.0 + 19.0)
        units.append(replace(unit, location=replace(unit.location, bbox=transformed)))
    expected = tuple(units)
    source = replace(source, chunk=replace(source.chunk, evidence_units=tuple(reversed(units))))
    assert select(source).groups[0].units == expected


def test_missing_requested_rule_does_not_become_an_answer_or_a_semantic_role() -> None:
    source = grid(value="未定", note="No warranty rule is provided.")
    result = select(source, query="DEVICE-Ω warranty duration?")
    assert result.groups[0].units == source.chunk.evidence_units
    # Candidate selection does not assert that the requested rule exists.
    assessment = inspect_grid_candidate("DEVICE-Ω warranty duration?", source,
                                        source.chunk.evidence_units)
    assert assessment.eligible and assessment.reason == "bbox_grid_match"


def test_separated_grids_are_ambiguous_and_notes_are_not_silently_dropped() -> None:
    source = grid()
    units = list(source.chunk.evidence_units)
    # Move the last grid row below the prose note: there are now two grid runs.
    for index in (7, 8, 9):
        box = units[index].location.bbox
        assert box is not None
        units[index] = replace(units[index], location=replace(
            units[index].location, bbox=(box[0], 130.0, box[2], 140.0)))
    source = replace(source, chunk=replace(source.chunk, evidence_units=tuple(units)))
    result = select(source)
    assert result.groups == ()
    assert result.observations[0].structure_reason == "ambiguous_structure"


@pytest.mark.parametrize("mutation", [
    "missing_cell", "duplicate_coordinate", "merged", "coordinate_gap", "misaligned",
    "overlap", "nan", "page", "part", "image", "interleaved_prose", "filtered_unit",
])
def test_ambiguous_or_incomplete_grid_cannot_promote_a_low_score(mutation: str) -> None:
    source = grid(annotated=True)
    units = list(source.chunk.evidence_units)
    location = units[5].location
    if mutation == "missing_cell":
        units.pop(5)
    elif mutation == "filtered_unit":
        units[5] = replace(units[5], projection_id=None)
    elif mutation == "interleaved_prose":
        units[5] = replace(units[5], location=replace(location, table_cell=None))
    else:
        mutations: dict[str, dict[str, Any]] = {
            "duplicate_coordinate": {"table_cell": TableCellLocation(0, 0)},
            "merged": {"table_cell": TableCellLocation(1, 1, 2, 1)},
            "coordinate_gap": {"table_cell": TableCellLocation(8, 1)},
            "misaligned": {"bbox": (175.0, 50.0, 275.0, 60.0)},
            "overlap": {"bbox": (100.0, 50.0, 275.0, 60.0)},
            "nan": {"bbox": (float("nan"), 50.0, 275.0, 60.0)},
            "page": {"page": 2}, "part": {"source_part": "other"},
            "image": {"image_sha256": "a" * 64},
        }
        units[5] = replace(units[5], location=replace(location, **mutations[mutation]))
    source = replace(source, chunk=replace(source.chunk, evidence_units=tuple(units)))
    result = select(source)
    assert result.groups == ()
    assert result.observations[0].structure_reason == (
        "incomplete_source" if mutation == "filtered_unit" else "ambiguous_structure")


def test_missing_structure_and_ordinary_fallback_have_separate_diagnostics() -> None:
    source = grid()
    units = tuple(replace(u, location=replace(u.location, bbox=(5.0, i * 15.0,
                                                                450.0, i * 15.0 + 10)))
                  for i, u in enumerate(source.chunk.evidence_units))
    source = replace(source, chunk=replace(source.chunk, evidence_units=units))
    assert select(source).groups == ()
    high = select(source, high=True)
    assert high.groups[0].units == units
    assert high.observations[0].reason == "selected"
    assert high.observations[0].structure_reason == "missing_structure"


def test_existing_payment_behavior_is_default_and_opt_in_keeps_all_columns() -> None:
    source: EvidenceSource = table_source()  # type: ignore[no-untyped-call]
    query = "ORCHID-71 현금화하면 돈은 며칠 뒤 받을 수 있어?"
    kwargs: dict[str, Any] = dict(query=query, sources=(source,), extractive=EMPTY,
                  policy=AnswerPolicy(0.9, 1.0), budget=EvidenceBudget(2, 64, 12000),
                  embedding=LowEmbedding(), include_diagnostics=False)
    legacy = select_context(**kwargs)
    assert len(legacy.groups[0].units) == 28
    # No Korean particle inference: exact whole-cell token with a separator.
    modern = select(source, query=query)
    assert modern.groups[0].units == source.chunk.evidence_units
    assert legacy == select_context(**kwargs, table_strategy="payment-v1")
    with pytest.raises(ValueError, match="strategy"):
        select_context(**(kwargs | {"table_strategy": "unknown"}))


@pytest.mark.parametrize("limit", ["units", "characters"])
def test_budget_excludes_entire_candidate_without_dropping_notes(limit: str) -> None:
    source = grid()
    size = sum(len(u.text) for u in source.chunk.evidence_units)
    budget = EvidenceBudget(1, 10 if limit == "units" else 11,
                            size - 1 if limit == "characters" else size)
    result = select(source, budget=budget)
    assert result.groups == ()
    assert result.observations[0].reason == "budget_exceeded"
    assert result.observations[0].structure_reason == "bbox_grid_match"


def test_known_conflict_cannot_be_lost_when_whole_grid_exceeds_budget() -> None:
    source = grid()
    answers = tuple(EvidenceAnswer(source, unit, "", (), None, 1.0)
                    for unit in (source.chunk.evidence_units[2], source.chunk.evidence_units[-1]))
    result = select_context(query="DEVICE-Ω", sources=(source,),
        extractive=replace(EMPTY, answer=answers[0], conflicts=(answers[1],)),
        policy=AnswerPolicy(0.9, 1.0), budget=EvidenceBudget(1, 10, 12000),
        embedding=LowEmbedding(), include_diagnostics=True, table_strategy="structure-v1")
    assert result.groups == ()
    assert result.blocked_reason == "conflict_context_budget_exceeded"


def test_non_pdf_and_stripped_source_are_explicitly_unsupported() -> None:
    source = grid()
    assert inspect_grid_candidate("DEVICE-Ω", replace(source, media_type="text/plain"),
                                  source.chunk.evidence_units).reason == "unsupported_source"
    assert inspect_grid_candidate("DEVICE-Ω", source,
                                  source.chunk.evidence_units[:-1]).reason == "incomplete_source"


def test_all_missing_pdf_boxes_emit_safe_opt_in_diagnostic_without_unit_ids() -> None:
    source = grid()
    source = replace(source, chunk=replace(source.chunk, evidence_units=tuple(
        replace(u, location=replace(u.location, bbox=None)) for u in source.chunk.evidence_units)))
    result = select(source)
    assert result.groups == () and result.observations == () and result.diagnostics == ()
    assert result.diagnostic_warning == "structural_context_incomplete_source"
    default = select_context(query="DEVICE-Ω", sources=(source,), extractive=EMPTY,
        policy=AnswerPolicy(0.9, 1.0), budget=DEFAULT_BUDGET, embedding=LowEmbedding(),
        include_diagnostics=True)
    assert default.diagnostic_warning is None


def test_fully_filtered_source_warning_survives_other_valid_context() -> None:
    source = grid()
    source = replace(source, chunk=replace(source.chunk, evidence_units=tuple(
        replace(u, location=replace(u.location, bbox=None)) for u in source.chunk.evidence_units)))
    other = _source(812, "ordinary context")
    answer = EvidenceAnswer(other, other.chunk.evidence_units[0], "", (), None, 1.0)
    result = select_context(query="unmatched", sources=(source, other),
        extractive=replace(EMPTY, answer=answer), policy=AnswerPolicy(0.9, 1.0),
        budget=DEFAULT_BUDGET, embedding=LowEmbedding(), include_diagnostics=False,
        table_strategy="structure-v1")
    assert result.groups[0].source == other
    assert result.diagnostic_warning == "structural_context_incomplete_source"
    assert source.chunk.chunk_id not in [o.chunk_id for o in result.observations]
