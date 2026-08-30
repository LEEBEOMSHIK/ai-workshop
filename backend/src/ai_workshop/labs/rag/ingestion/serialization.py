import json
from typing import Any, cast
from uuid import UUID

from ai_workshop.labs.rag.chunking.contracts import ChunkingResult
from ai_workshop.labs.rag.documents.domain import (
    EvidenceUnit,
    ParsedDocument,
    RetrievalChunk,
    SourceLocation,
    StructuralElement,
)


def _location_to_json(location: SourceLocation) -> dict[str, object]:
    return {
        "element_id": str(location.element_id),
        "page": location.page,
        "char_start": location.char_start,
        "char_end": location.char_end,
        "bbox": list(location.bbox) if location.bbox is not None else None,
    }


def _location_from_json(value: dict[str, Any]) -> SourceLocation:
    bbox_value = value["bbox"]
    return SourceLocation(
        element_id=UUID(value["element_id"]),
        page=value["page"],
        char_start=value["char_start"],
        char_end=value["char_end"],
        bbox=tuple(bbox_value) if bbox_value is not None else None,
    )


def _encode(value: dict[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _decode(content: bytes) -> dict[str, Any]:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("A RAG artifact must contain a JSON object.")
    return cast(dict[str, Any], value)


def serialize_parsed_document(document: ParsedDocument) -> bytes:
    return _encode(
        {
            "asset_version_id": str(document.asset_version_id),
            "parser_name": document.parser_name,
            "parser_version": document.parser_version,
            "elements": [
                {
                    "id": str(element.id),
                    "ordinal": element.ordinal,
                    "kind": element.kind,
                    "text": element.text,
                    "section_path": list(element.section_path),
                    "location": _location_to_json(element.location),
                    "parser_name": element.parser_name,
                    "parser_version": element.parser_version,
                    "confidence": element.confidence,
                }
                for element in document.elements
            ],
        }
    )


def deserialize_parsed_document(content: bytes) -> ParsedDocument:
    value = _decode(content)
    return ParsedDocument(
        asset_version_id=UUID(value["asset_version_id"]),
        parser_name=value["parser_name"],
        parser_version=value["parser_version"],
        elements=tuple(
            StructuralElement(
                id=UUID(element["id"]),
                ordinal=element["ordinal"],
                kind=element["kind"],
                text=element["text"],
                section_path=tuple(element["section_path"]),
                location=_location_from_json(element["location"]),
                parser_name=element["parser_name"],
                parser_version=element["parser_version"],
                confidence=element["confidence"],
            )
            for element in value["elements"]
        ),
    )


def serialize_chunking_result(result: ChunkingResult) -> bytes:
    return _encode(
        {
            "chunks": [
                {
                    "id": str(chunk.id),
                    "projection_id": str(chunk.projection_id),
                    "ordinal": chunk.ordinal,
                    "text": chunk.text,
                    "section_path": list(chunk.section_path),
                    "evidence_unit_ids": [str(unit.id) for unit in chunk.evidence_units],
                }
                for chunk in result.chunks
            ],
            "evidence_units": [
                {
                    "id": str(unit.id),
                    "chunk_id": str(unit.chunk_id) if unit.chunk_id is not None else None,
                    "projection_id": (
                        str(unit.projection_id) if unit.projection_id is not None else None
                    ),
                    "ordinal": unit.ordinal,
                    "text": unit.text,
                    "location": _location_to_json(unit.location),
                }
                for unit in result.evidence_units
            ],
        }
    )


def deserialize_chunking_result(content: bytes) -> ChunkingResult:
    value = _decode(content)
    evidence_by_id = {
        UUID(unit["id"]): EvidenceUnit(
            id=UUID(unit["id"]),
            chunk_id=UUID(unit["chunk_id"]) if unit["chunk_id"] is not None else None,
            projection_id=(
                UUID(unit["projection_id"]) if unit["projection_id"] is not None else None
            ),
            ordinal=unit["ordinal"],
            text=unit["text"],
            location=_location_from_json(unit["location"]),
        )
        for unit in value["evidence_units"]
    }
    chunks = tuple(
        RetrievalChunk(
            id=UUID(chunk["id"]),
            projection_id=UUID(chunk["projection_id"]),
            ordinal=chunk["ordinal"],
            text=chunk["text"],
            section_path=tuple(chunk["section_path"]),
            evidence_units=tuple(
                evidence_by_id[UUID(evidence_id)] for evidence_id in chunk["evidence_unit_ids"]
            ),
        )
        for chunk in value["chunks"]
    )
    return ChunkingResult(chunks=chunks, evidence_units=tuple(evidence_by_id.values()))
