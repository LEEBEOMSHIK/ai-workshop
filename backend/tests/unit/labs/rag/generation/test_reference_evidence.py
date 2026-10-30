"""Lossless reference packing contracts; no model quality claim."""

import json
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.compact_evidence import pack_compact_evidence
from ai_workshop.labs.rag.generation.reference_evidence import (
    MAX_REFERENCE_EVIDENCE,
    ReferenceEvidencePack,
    build_reference_map,
    pack_reference_evidence,
    resolve_evidence_refs,
    unpack_reference_evidence,
)
from tests.unit.labs.rag.generation.test_source_reading import source_units, stored_evidence


@pytest.mark.parametrize("texts", [[], ["single"], ["한글 e1\n  😀", "same", "same"]])
def test_roundtrip_empty_single_unicode_and_duplicate_text(texts: list[str]) -> None:
    items = source_units(texts)
    packed = pack_reference_evidence(items)
    assert unpack_reference_evidence(packed) == pack_compact_evidence(items)
    assert packed.reference_ids == tuple(item.evidence_id for item in items)
    assert list(packed.reference_map) == [f"e{i+1}" for i in range(len(items))]
    wire = json.dumps(packed.payload, ensure_ascii=False)
    assert all(str(item.evidence_id) not in wire for item in items)


def test_full_stored_fixture_preserves_every_field_and_reduces_bytes() -> None:
    items = stored_evidence()
    packed = pack_reference_evidence(items)
    old = pack_compact_evidence(items)
    assert unpack_reference_evidence(packed) == old
    assert len(json.dumps(packed.payload).encode()) < len(json.dumps(old).encode())
    assert packed.payload["fragment_columns"] == [
        "evidence_ref", "text", "bbox", "char_range", "ordinal"]


@pytest.mark.parametrize("change", [
    {"document_id": UUID(int=900)}, {"chunk_id": UUID(int=901)},
    {"projection_id": UUID(int=902)}, {"asset_version_id": UUID(int=903)},
    {"ordinal": 8}, {"char_start": -1}, {"bbox": (0.123456789, 0.0, 9.5, 12.0)},
])
def test_boundaries_positions_and_nonconsecutive_order(change: dict[str, Any]) -> None:
    first, second = source_units(["ABC", "DEF"])
    items = (replace(second, **change), first)
    assert unpack_reference_evidence(pack_reference_evidence(items)) == pack_compact_evidence(items)


def test_map_and_payload_cannot_be_mutated_through_returned_values() -> None:
    items = source_units(["e1 is literal text"])
    packed = pack_reference_evidence(items)
    payload = packed.payload
    payload["evidence_blocks"][0]["rows"][0][1] = "mutated"
    assert unpack_reference_evidence(packed) == pack_compact_evidence(items)
    with pytest.raises(TypeError):
        packed.reference_map["e1"] = UUID(int=9)  # type: ignore[index]
    mapping = build_reference_map(items)
    with pytest.raises(TypeError):
        mapping["e1"] = UUID(int=9)  # type: ignore[index]


def test_duplicate_ids_and_request_limit_fail_before_packing() -> None:
    item = source_units(["x"])[0]
    for items in ((item, item), tuple(replace(item, evidence_id=UUID(int=i+1))
                                    for i in range(MAX_REFERENCE_EVIDENCE+1))):
        with pytest.raises(ValueError):
            build_reference_map(items)
        with pytest.raises(ValueError):
            pack_reference_evidence(items)


@pytest.mark.parametrize("refs", [("e0",), ("e01",), ("E1",), ("e1 ",), ("e2",),
                                  (str(UUID(int=1)),), ("e1", "e1")])
def test_bad_aliases_and_raw_uuid_rejected(refs: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        resolve_evidence_refs(refs, {"e1": UUID(int=1)})


@pytest.mark.parametrize("mapping", [
    {"e2": UUID(int=1)}, {"e1": UUID(int=1), "e2": UUID(int=1)}, {"e1": "bad"},
])
def test_invalid_maps_rejected(mapping: Any) -> None:
    with pytest.raises(ValueError):
        resolve_evidence_refs((), mapping)


def test_request_maps_are_independent_and_output_order_preserved() -> None:
    first, second = source_units(["a", "b"])
    a, b = build_reference_map((first, second)), build_reference_map((second, first))
    assert resolve_evidence_refs(("e2", "e1"), a) == (second.evidence_id, first.evidence_id)
    assert resolve_evidence_refs(("e1",), b) == (second.evidence_id,)
    assert resolve_evidence_refs((), {}) == ()


def test_corrupted_rows_are_rejected_by_unpack() -> None:
    packed = pack_reference_evidence(source_units(["a"]))
    payload = packed.payload
    payload["evidence_blocks"][0]["rows"][0][0] = "e2"
    with pytest.raises(ValueError):
        unpack_reference_evidence(ReferenceEvidencePack(payload, packed.reference_map))
