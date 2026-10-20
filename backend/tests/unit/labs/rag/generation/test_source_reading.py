"""Source-coordinate contracts, not semantic role or model-quality tests."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import TableCellLocation
from ai_workshop.labs.rag.generation.domain import GenerationRequest, GroundingEvidence
from ai_workshop.labs.rag.generation.evidence_payload import evidence_payload
from ai_workshop.labs.rag.generation.openai_compatible import _generation_user_content
from ai_workshop.labs.rag.generation.prompts import load_prompt, prompt_reference_version
from ai_workshop.labs.rag.generation.source_reading import build_source_reading
from ai_workshop.labs.rag.models.context_evidence import EvidenceBudget, resolve_evidence_budget
from tests.unit.labs.rag.generation.test_http_evidence_groups import restore
from tests.unit.labs.rag.generation.test_openai_compatible import evidence, profile

FIXTURE = Path(__file__).parents[4] / "fixtures/rag/source_reading_cases.json"
REF = "rag-answer-v4"


def fixture() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data


def stored_evidence() -> tuple[GroundingEvidence, ...]:
    items = []
    for row in fixture()["stored_evidence"]:
        values = dict(row)
        for key in (
            "evidence_id",
            "document_id",
            "asset_version_id",
            "projection_id",
            "chunk_id",
            "element_id",
        ):
            values[key] = UUID(values[key])
        values["section_path"] = tuple(values["section_path"])
        if values["bbox"] is not None:
            values["bbox"] = tuple(values["bbox"])
        if values["table_cell"] is not None:
            values["table_cell"] = TableCellLocation(**values["table_cell"])
        items.append(GroundingEvidence(**values))
    return tuple(items)


def source_units(texts: list[str]) -> tuple[GroundingEvidence, ...]:
    items = []
    offset = 0
    for index, text in enumerate(texts):
        items.append(
            replace(
                evidence(),
                evidence_id=UUID(int=100 + index),
                element_id=UUID(int=200 + index),
                text=text,
                page=1,
                ordinal=index,
                char_start=offset,
                char_end=offset + len(text),
            )
        )
        offset += len(text)
    return tuple(items)


def request_for(
    items: tuple[GroundingEvidence, ...],
    *,
    reference: str = REF,
    schema: int = 2,
    question: str = "근거의 일반 기준은?",
) -> GenerationRequest:
    selected = replace(
        profile(),
        prompt_ref=reference,
        response_schema_version=schema,
        evidence_budget=EvidenceBudget(8, 32, 12000),
    )
    return GenerationRequest(question, question, (), items, selected, "synthetic")


def test_saved_split_sources_are_linked_without_creating_roles_or_rewriting_text() -> None:
    items = stored_evidence()
    before = evidence_payload(items, contextual=True)
    guide = build_source_reading(items)
    assert guide["basis"] == "parser_source_order_only"
    assert guide["semantic_roles"] == "not_assigned"
    spans = guide["contiguous_spans"]
    by_order = {item.ordinal: str(item.evidence_id) for item in items}
    assert any(by_order[26] in span and by_order[27] in span for span in spans)
    assert any(by_order[18] in span and by_order[19] in span for span in spans)
    assert evidence_payload(items, contextual=True) == before


@pytest.mark.parametrize(
    "change",
    [
        {"document_id": UUID(int=1)},
        {"asset_version_id": UUID(int=1)},
        {"projection_id": UUID(int=1)},
        {"chunk_id": UUID(int=1)},
        {"page": 2},
        {"source_part": "other"},
        {"source_kind": "ocr"},
        {"section_path": ("other",)},
        {"table_cell": TableCellLocation(1, 2)},
        {"ordinal": 4},
        {"char_start": 50, "char_end": 55},
        {"char_start": 0, "char_end": 1},
        {"projection_id": None},
        {"chunk_id": None},
    ],
)
def test_source_boundaries_and_gaps_are_not_bridged(change: dict[str, Any]) -> None:
    first, second = source_units(["abc", "def"])
    assert build_source_reading((first, replace(second, **change)))["contiguous_spans"] == []


def test_empty_single_duplicate_and_reversed_units_do_not_create_spans() -> None:
    first, second = source_units(["abc", "def"])
    for items in [(), (first,), (second, first), (first, second, first)]:
        assert build_source_reading(items)["contiguous_spans"] == []


def test_interleaved_sources_are_not_reordered_to_manufacture_continuity() -> None:
    first, second = source_units(["abc", "def"])
    other = replace(first, evidence_id=UUID(int=999), chunk_id=UUID(int=888))
    assert build_source_reading((first, other, second))["contiguous_spans"] == []


@pytest.mark.parametrize("scenario", fixture()["scenarios"], ids=lambda c: c["name"])
def test_other_domains_and_missing_rules_use_only_coordinates(scenario: dict[str, Any]) -> None:
    items = source_units(scenario["texts"])
    guide = build_source_reading(items)
    assert guide["semantic_roles"] == "not_assigned"
    assert guide["contiguous_spans"] == [[str(item.evidence_id) for item in items]]
    # Keep coordinates/IDs constant while changing every word, date, and number.
    changed = tuple(replace(item, text="x" * len(item.text)) for item in items)
    assert build_source_reading(changed) == guide
    payload = json.loads(
        _generation_user_content(request_for(items, question=scenario["question"]))
    )
    assert restore(payload) == evidence_payload(items, contextual=True)
    assert payload["source_reading"] == guide


@pytest.mark.parametrize("schema", [1, 2])
def test_v4_adds_only_source_reading_and_keeps_response_contract(schema: int) -> None:
    items = stored_evidence()
    old = json.loads(
        _generation_user_content(request_for(items, reference="rag-answer-v3", schema=schema))
    )
    current = json.loads(_generation_user_content(request_for(items, schema=schema)))
    assert current.pop("source_reading") == build_source_reading(items)
    assert current == old
    assert current["schema_version"] == schema


def test_v4_is_explicit_contextual_prompt_with_no_case_answer_constants() -> None:
    text = load_prompt(REF)
    assert prompt_reference_version(REF) == 4
    assert text != load_prompt("rag-answer-v3")
    for fragment in ("일반 규칙", "적용 조건", "예시", "추정하지", "같은 주장", "인접", "비신뢰"):
        assert fragment in text
    for prohibited in ("AM-SYN", "T+4", "09-14", "200시간", "37일"):
        assert prohibited not in text
    config = {
        "prompt_ref": REF,
        "context_evidence": {
            "version": 1,
            "max_groups": 8,
            "max_units": 32,
            "max_characters": 12000,
        },
    }
    assert resolve_evidence_budget(config) == EvidenceBudget(8, 32, 12000)
    with pytest.raises(ValueError, match="explicit evidence budget"):
        resolve_evidence_budget({"prompt_ref": REF})


def test_v1_v2_v3_match_payload_bytes_captured_before_v4_implementation() -> None:
    for baseline in fixture()["legacy_payload_sha256"]:
        request = request_for(
            stored_evidence(), reference=baseline["prompt_ref"], schema=baseline["schema"]
        )
        if baseline["prompt_ref"] == "rag-answer-v1":
            request = replace(request, profile=replace(request.profile, evidence_budget=None))
        actual = hashlib.sha256(_generation_user_content(request).encode()).hexdigest()
        assert actual == baseline["sha256"]


def test_empty_v4_has_no_invented_sources_and_missing_budget_is_rejected() -> None:
    request = request_for(())
    payload = json.loads(_generation_user_content(request))
    assert payload["evidence"] == []
    assert payload["source_reading"]["contiguous_spans"] == []
    invalid = replace(request, profile=replace(request.profile, evidence_budget=None))
    with pytest.raises(ValueError, match="explicit evidence budget"):
        _generation_user_content(invalid)
