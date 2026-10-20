"""V5 input preservation contracts; these do not measure model answer quality."""

import hashlib
import json
from dataclasses import asdict, replace
from typing import Any
from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import TableCellLocation
from ai_workshop.labs.rag.generation.domain import GroundingEvidence
from ai_workshop.labs.rag.generation.openai_compatible import _generation_user_content
from ai_workshop.labs.rag.models.context_evidence import EvidenceBudget, resolve_evidence_budget
from tests.unit.labs.rag.generation.test_source_reading import (
    fixture,
    request_for,
    source_units,
    stored_evidence,
)

REF = "rag-answer-v5"


def packed(items: tuple[GroundingEvidence, ...]) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(
        _generation_user_content(request_for(items, reference=REF))
    )
    assert "evidence_blocks" in value, "V5 must emit the compact block representation"
    return value


def fragments(value: dict[str, Any]) -> list[dict[str, Any]]:
    return [fragment for block in value["evidence_blocks"] for fragment in block["fragments"]]


def test_saved_fragments_keep_exact_text_citation_and_geometry_in_input_order() -> None:
    items = stored_evidence()
    value = packed(items)
    actual = fragments(value)
    assert len(actual) == 28
    for source, sent in zip(items, actual, strict=True):
        assert sent["evidence_id"] == str(source.evidence_id)
        assert sent["text"] == source.text
        assert sent["bbox"] == (list(source.bbox) if source.bbox is not None else None)
        assert sent["char_range"] == [source.char_start, source.char_end]
        assert sent["ordinal"] == source.ordinal
    # Hand-inspected parser spans, not recomputed with the production span helper.
    assert [len(block["fragments"]) for block in value["evidence_blocks"]] == [8, 2, 2, 2, 2, 12]
    assert value["evidence_sources"][0]["page"] == 2
    assert value["evidence_sources"][0]["table_cell"] is None
    wire = json.dumps(value, ensure_ascii=False)
    assert all(wire.count(str(item.evidence_id)) == 1 for item in items)
    assert all(str(item.element_id) not in wire for item in items)


@pytest.mark.parametrize(
    "change",
    [
        {"document_id": UUID(int=1)},
        {"asset_version_id": UUID(int=1)},
        {"projection_id": UUID(int=1)},
        {"chunk_id": UUID(int=1)},
        {"page": 2},
        {"source_kind": "ocr"},
        {"source_part": "header"},
        {"section_path": ("another section",)},
        {"table_cell": TableCellLocation(1, 2)},
    ],
)
def test_distinct_source_boundaries_are_neither_merged_nor_given_the_same_reference(
    change: dict[str, Any],
) -> None:
    first, second = source_units(["ABC", "DEF"])
    second = replace(second, **change)
    value = packed((first, second))
    blocks = value["evidence_blocks"]
    assert len(blocks) == 2
    assert blocks[0]["source_ref"] != blocks[1]["source_ref"]
    metadata = value["evidence_sources"][blocks[1]["source_ref"]]
    assert metadata == {
        "page": second.page,
        "source_kind": second.source_kind,
        "source_part": second.source_part,
        "table_cell": asdict(second.table_cell) if second.table_cell else None,
        "section_path": list(second.section_path),
    }


@pytest.mark.parametrize(
    "change",
    [
        {"ordinal": 4},
        {"ordinal": -1},
        {"char_start": 50, "char_end": 55},
        {"char_start": -1},
        {"char_start": 3, "char_end": 3},
        {"char_start": 3, "char_end": 2},
        {"projection_id": None},
        {"chunk_id": None},
    ],
)
def test_gaps_and_unreliable_coordinates_do_not_claim_contiguity(change: dict[str, Any]) -> None:
    first, second = source_units(["ABC", "DEF"])
    value = packed((first, replace(second, **change)))
    assert [len(b["fragments"]) for b in value["evidence_blocks"]] == [1, 1]


def test_interleaved_and_reversed_sources_preserve_input_order() -> None:
    first, second = source_units(["ABC", "DEF"])
    other = replace(first, evidence_id=UUID(int=900), chunk_id=UUID(int=901))
    for items in ((first, other, second), (second, first)):
        value = packed(items)
        assert [f["evidence_id"] for f in fragments(value)] == [str(e.evidence_id) for e in items]
        assert all(len(b["fragments"]) == 1 for b in value["evidence_blocks"])


def test_duplicate_evidence_ids_fail_before_an_ambiguous_request_is_built() -> None:
    first, second = source_units(["ABC", "DEF"])
    for duplicate in (first, replace(second, evidence_id=first.evidence_id)):
        with pytest.raises(ValueError, match="Duplicate evidence identity"):
            _generation_user_content(request_for((first, duplicate), reference=REF))


def test_empty_and_single_inputs_do_not_invent_fragments() -> None:
    empty = packed(())
    assert empty["evidence_blocks"] == [] and empty["evidence_sources"] == []
    first = source_units(["ABC"])[0]
    assert len(fragments(packed((first,)))) == 1


@pytest.mark.parametrize("scenario", fixture()["scenarios"], ids=lambda c: c["name"])
def test_other_domains_and_no_rule_inputs_are_not_classified_or_rewritten(
    scenario: dict[str, Any],
) -> None:
    items = source_units(scenario["texts"])
    before = packed(items)
    assert [f["text"] for f in fragments(before)] == scenario["texts"]
    changed = tuple(replace(item, text="x" * len(item.text)) for item in items)
    after = packed(changed)
    for entry in fragments(before):
        entry["text"] = "x" * len(entry["text"])
    assert before == after


def test_v5_requires_an_explicit_context_budget() -> None:
    with pytest.raises(ValueError, match="explicit evidence budget"):
        resolve_evidence_budget({"prompt_ref": REF})
    config = {
        "prompt_ref": REF,
        "context_evidence": {
            "version": 1, "max_groups": 8, "max_units": 32, "max_characters": 12000,
        },
    }
    assert resolve_evidence_budget(config) == EvidenceBudget(8, 32, 12000)
    request = request_for((), reference=REF)
    with pytest.raises(ValueError, match="explicit evidence budget"):
        _generation_user_content(
            replace(request, profile=replace(request.profile, evidence_budget=None))
        )


def test_v5_reduces_saved_input_bytes_without_dropping_evidence() -> None:
    items = stored_evidence()
    old = _generation_user_content(request_for(items, reference="rag-answer-v4"))
    new = _generation_user_content(request_for(items, reference=REF))
    assert len(new.encode()) < len(old.encode()) * 0.85
    assert [f["text"] for f in fragments(packed(items))] == [e.text for e in items]


@pytest.mark.parametrize(
    ("schema", "digest"),
    [
        (1, "40f3d0bf387992516ddf79f6c399953130823a5cdca19858673b773401d5aad7"),
        (2, "d17405d79af1607ba873671be2885d6a7df1847aa983aa42217d736a293e4f78"),
    ],
)
def test_existing_v4_wire_bytes_are_unchanged(schema: int, digest: str) -> None:
    request = request_for(stored_evidence(), schema=schema)
    assert hashlib.sha256(_generation_user_content(request).encode()).hexdigest() == digest
