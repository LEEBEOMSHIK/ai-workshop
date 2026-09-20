"""Shared contextual evidence representation; original text is never rewritten."""

import json
from dataclasses import asdict

from ai_workshop.labs.rag.generation.domain import GroundingEvidence


def serialize_evidence(evidence: tuple[GroundingEvidence, ...]) -> list[dict[str, object]]:
    return [{
        "evidence_id": str(item.evidence_id), "text": item.text,
        "group_id": ":".join(str(value) for value in (
            item.document_id, item.asset_version_id, item.projection_id, item.chunk_id)),
        "document_id": str(item.document_id), "asset_version_id": str(item.asset_version_id),
        "projection_id": str(item.projection_id), "chunk_id": str(item.chunk_id),
        "element_id": str(item.element_id), "page": item.page,
        "char_start": item.char_start, "char_end": item.char_end,
        "bbox": list(item.bbox) if item.bbox is not None else None,
        "source_kind": item.source_kind,
        "source_part": item.source_part,
        "table_cell": asdict(item.table_cell) if item.table_cell is not None else None,
        "section_path": list(item.section_path), "ordinal": item.ordinal,
        "context_notice": "section_path is navigation context, not citable evidence",
    } for item in evidence]


def evidence_payload(
    evidence: tuple[GroundingEvidence, ...], *, contextual: bool,
) -> list[dict[str, object]]:
    if contextual:
        return serialize_evidence(evidence)
    return [{"evidence_id": str(item.evidence_id), "text": item.text} for item in evidence]


def is_context_abstention(content: str) -> bool:
    """Only the contextual v1 wire permits an explicit empty-claims abstention."""
    try:
        parsed = json.loads(content, object_pairs_hook=_unique_object)
    except (TypeError, ValueError):
        return False
    return (isinstance(parsed, dict) and set(parsed) == {"schema_version", "claims"}
            and type(parsed["schema_version"]) is int and parsed["schema_version"] == 1
            and parsed["claims"] == [])


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate structured response key.")
        value[key] = item
    return value
