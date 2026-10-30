"""Source-defined business days: public fixture replay plus hostile variations."""

from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.citation_validation import CitationValidator
from ai_workshop.labs.rag.generation.domain import (
    GeneratedClaim,
    GenerationOutcome,
    GenerationStatus,
    GroundingEvidence,
    StructuredGeneration,
)
from tests.unit.labs.rag.generation.test_source_reading import stored_evidence

FIRST_CLAIM = "두 경우 모두 접수일 T의 다음 영업일부터 2영업일을 센 T+2의 기준가격을 적용합니다."
SECOND_CLAIM = "두 경우 모두 접수일 다음 영업일부터 2영업일을 센 T+2의 기준가격을 적용합니다."


def cited_sources() -> tuple[GroundingEvidence, ...]:
    items = stored_evidence()
    return tuple(items[index] for index in (4, 5, 7, 12, 13))


def changed_text(
    items: tuple[GroundingEvidence, ...], index: int, text: str,
) -> tuple[GroundingEvidence, ...]:
    """Preserve source continuity, so semantic mutations do not fail on offsets."""
    delta = len(text) - len(items[index].text)
    result = list(items)
    result[index] = replace(items[index], text=text, char_end=items[index].char_end + delta)
    for later in range(index + 1, len(items)):
        result[later] = replace(
            items[later], char_start=items[later].char_start + delta,
            char_end=items[later].char_end + delta,
        )
    return tuple(result)


def validate(
    text: str = FIRST_CLAIM,
    items: tuple[GroundingEvidence, ...] | None = None,
    *, schema: int = 2, refs: tuple[UUID, ...] | None = None,
) -> GenerationOutcome:
    items = cited_sources() if items is None else items
    return CitationValidator().validate(
        StructuredGeneration(schema, (GeneratedClaim(
            text, tuple(item.evidence_id for item in items) if refs is None else refs,
        ),)),
        allowed_evidence=items,
    )


def assert_rejected(outcome: GenerationOutcome) -> None:
    assert outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
    assert outcome.reason_codes == ("exact_value_not_supported",)
    assert outcome.text is None
    assert outcome.citations == ()


@pytest.mark.parametrize("text", [FIRST_CLAIM, SECOND_CLAIM])
@pytest.mark.parametrize("schema", [1, 2])
def test_cited_definition_and_exact_table_relationship_support_saved_paraphrase(
    text: str, schema: int,
) -> None:
    items = cited_sources()
    outcome = validate(text, items, schema=schema)
    assert outcome.status is GenerationStatus.ANSWERED
    assert outcome.text == text
    assert outcome.citations[0].claim_text == text
    assert outcome.citations[0].evidence_ids == tuple(item.evidence_id for item in items)


@pytest.mark.parametrize("missing", range(5))
def test_each_definition_header_label_and_value_must_be_cited(missing: int) -> None:
    items = cited_sources()
    refs = tuple(item.evidence_id for i, item in enumerate(items) if i != missing)
    assert_rejected(validate(items=items, refs=refs))


@pytest.mark.parametrize("change", [
    {"document_id": UUID(int=910)}, {"asset_version_id": UUID(int=910)},
    {"projection_id": UUID(int=910)}, {"chunk_id": UUID(int=910)},
    {"page": 9}, {"source_kind": "normalized_text"}, {"source_part": "other"},
    {"section_path": ("other",)}, {"ordinal": 50}, {"char_start": 741},
    {"char_start": 743}, {"char_end": 742},
])
def test_definition_cannot_cross_source_boundaries_or_broken_positions(
    change: dict[str, Any],
) -> None:
    items = list(cited_sources())
    items[1] = replace(items[1], **change)
    assert_rejected(validate(items=tuple(items)))


@pytest.mark.parametrize("text", [
    FIRST_CLAIM.replace("2영업일", "3영업일"),
    FIRST_CLAIM.replace("T+2", "T+3"),
    FIRST_CLAIM.replace("T+2", "T-2"),
    FIRST_CLAIM.replace("T+2", "S+2"),
    FIRST_CLAIM.replace("2영업일", "-2영업일"),
    FIRST_CLAIM.replace("접수일", "신청일"),
    FIRST_CLAIM.replace("다음 영업일부터", "당일부터"),
    FIRST_CLAIM.replace("기준가격", "대금 지급일"),
    FIRST_CLAIM.replace("두 경우 모두", "AM-SYN-202는"),
    FIRST_CLAIM.replace("적용합니다", "적용하지 않습니다"),
    FIRST_CLAIM + " 추가 기간은 9영업일입니다.",
])
def test_changed_period_base_start_product_or_attribute_is_not_newly_supported(text: str) -> None:
    assert_rejected(validate(text))


@pytest.mark.parametrize("text", [
    "T는 신청일이며, T+N은 신청일 다음 영업일부터",
    "T는 접수일이며, T+N은 접수일 당일부터",
    "T는 접수일이며, T+N은 접수일 다음 날부터",
    "S는 접수일이며, S+N은 접수일 다음 영업일부터",
    "T는 접수일이며, T-N은 접수일 다음 영업일부터",
    "T는 접수일이 아니며, T+N은 접수일 다음 영업일부터",
])
def test_missing_or_contradictory_unit_definition_does_not_supply_values(text: str) -> None:
    assert_rejected(validate(items=changed_text(cited_sources(), 0, text)))


@pytest.mark.parametrize("text", [
    "N일을 세지 않는다.", "N시간을 센다.", "N일을 센다. T는 신청일이다.",
])
def test_negated_or_ambiguous_definition_tail_is_rejected(text: str) -> None:
    assert_rejected(validate(items=changed_text(cited_sources(), 1, text)))


@pytest.mark.parametrize("index,box", [
    (2, (300.0, 254.0, 350.0, 267.0)),
    (3, (51.0, 330.0, 111.0, 343.0)),
    (4, (300.0, 350.0, 350.0, 363.0)),
    (4, None), (0, (42.0, float("nan"), 541.0, 208.0)),
])
def test_missing_or_wrong_table_geometry_cannot_bind_a_different_column_or_row(
    index: int, box: tuple[float, float, float, float] | None,
) -> None:
    items = list(cited_sources())
    items[index] = replace(items[index], bbox=box)
    assert_rejected(validate(items=tuple(items)))


def test_reversed_definition_citations_are_not_sorted_into_a_proof() -> None:
    items = cited_sources()
    assert_rejected(validate(items=(items[1], items[0], *items[2:])))


def test_duplicate_definition_citation_is_not_a_proof() -> None:
    items = cited_sources()
    refs = (items[0].evidence_id, *(item.evidence_id for item in items))
    assert_rejected(validate(items=items, refs=refs))


def test_other_numerical_values_are_still_checked() -> None:
    assert_rejected(validate(FIRST_CLAIM + " 수수료는 9%입니다."))


def test_schema_three_is_not_enabled_by_relative_day_relation() -> None:
    outcome = validate(schema=3)
    assert outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
    assert outcome.reason_codes == ("structured_output_invalid",)


def test_other_anchor_symbol_and_period_are_not_fixture_specific() -> None:
    items = cited_sources()
    for index, item in enumerate(items):
        text = item.text.replace("접수일", "검수일").replace("T+", "R+").replace("T는", "R는")
        text = text.replace("T+2", "R+6").replace("R+2", "R+6")
        items = changed_text(items, index, text)
    text = "검수일 R의 다음 영업일부터 6영업일을 센 R+6의 기준가격을 적용합니다."
    assert validate(text, items).status is GenerationStatus.ANSWERED
