"""Codex-compatible wire object normalized into the unchanged RAG v2 contract.

The CLI schema describes a closed object using its supported keyword subset.
The parser retains stronger status, claim and evidence validation server-side.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from typing import Any, NoReturn
from uuid import UUID

from .structured_output import StructuredOutputValidationError
from .structured_output_v2 import GroundedGenerationResultV2, parse_grounded_generation_v2

CODEX_GROUNDED_WIRE_SCHEMA_V1: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "status", "claims"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [2]},
        "status": {"type": "string", "enum": ["answered", "insufficient_evidence"]},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "evidence_ids"],
                "properties": {
                    "text": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


def parse_codex_grounded_wire_v1(
    content: str, *, allowed_evidence_ids: Collection[UUID],
) -> GroundedGenerationResultV2:
    normalized: str | None = None
    try:
        parsed = json.loads(content, object_pairs_hook=_unique_keys, parse_constant=_invalid_json)
        if (type(parsed) is dict
                and set(parsed) == {"schema_version", "status", "claims"}):
            if parsed["status"] == "insufficient_evidence":
                if type(parsed["claims"]) is not list or parsed["claims"]:
                    raise ValueError("invalid claims")
                # Only this validated wire-only empty field may be removed.
                del parsed["claims"]
            normalized = json.dumps(
                parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
            )
    except (TypeError, ValueError, RecursionError):
        pass
    if normalized is None:
        raise StructuredOutputValidationError("Invalid grounded generation output.")
    return parse_grounded_generation_v2(normalized, allowed_evidence_ids=allowed_evidence_ids)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError("duplicate key")
        parsed[key] = value
    return parsed


def _invalid_json(_value: str) -> NoReturn:
    raise ValueError("nonstandard constant")
