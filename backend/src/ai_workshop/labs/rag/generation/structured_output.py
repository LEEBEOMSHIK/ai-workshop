from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from typing import Any
from uuid import UUID

from ai_workshop.labs.rag.generation.domain import GeneratedClaim, StructuredGeneration

CONTEXTUALIZATION_SCHEMA_V1: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["resolved_query"],
    "properties": {
        "resolved_query": {"type": "string"},
    },
}

GROUNDED_GENERATION_SCHEMA_V1: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "claims"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "evidence_ids"],
                "properties": {
                    "text": {"type": "string"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    },
}


class StructuredOutputValidationError(ValueError):
    pass


def parse_contextualization_v1(content: str) -> str:
    parsed = _json_object(content)
    if set(parsed) != {"resolved_query"}:
        raise StructuredOutputValidationError("Invalid contextualization output.")
    resolved_query = parsed["resolved_query"]
    if not isinstance(resolved_query, str) or not resolved_query.strip():
        raise StructuredOutputValidationError("Invalid contextualization output.")
    return resolved_query.strip()


def parse_grounded_generation_v1(
    content: str,
    *,
    allowed_evidence_ids: Collection[UUID],
) -> StructuredGeneration:
    parsed = _json_object(content)
    if set(parsed) != {"schema_version", "claims"}:
        raise StructuredOutputValidationError("Invalid grounded generation output.")
    if type(parsed["schema_version"]) is not int or parsed["schema_version"] != 1:
        raise StructuredOutputValidationError("Invalid grounded generation output.")
    raw_claims = parsed["claims"]
    if not isinstance(raw_claims, list) or not raw_claims:
        raise StructuredOutputValidationError("Invalid grounded generation output.")

    allowed = set(allowed_evidence_ids)
    claims: list[GeneratedClaim] = []
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, Mapping) or set(raw_claim) != {
            "text",
            "evidence_ids",
        }:
            raise StructuredOutputValidationError("Invalid grounded generation output.")
        text = raw_claim["text"]
        raw_evidence_ids = raw_claim["evidence_ids"]
        if not isinstance(text, str) or not text.strip():
            raise StructuredOutputValidationError("Invalid grounded generation output.")
        if not isinstance(raw_evidence_ids, list) or not raw_evidence_ids:
            raise StructuredOutputValidationError("Invalid grounded generation output.")
        if any(not isinstance(value, str) for value in raw_evidence_ids):
            raise StructuredOutputValidationError("Invalid grounded generation output.")
        try:
            evidence_ids = tuple(UUID(value) for value in raw_evidence_ids)
        except (TypeError, ValueError):
            raise StructuredOutputValidationError(
                "Invalid grounded generation output."
            ) from None
        if len(set(evidence_ids)) != len(evidence_ids) or any(
            evidence_id not in allowed for evidence_id in evidence_ids
        ):
            raise StructuredOutputValidationError("Invalid grounded generation output.")
        claims.append(GeneratedClaim(text=text, evidence_ids=evidence_ids))
    return StructuredGeneration(schema_version=1, claims=tuple(claims))


def _json_object(content: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise StructuredOutputValidationError("Invalid structured output.") from None
    if not isinstance(parsed, Mapping):
        raise StructuredOutputValidationError("Invalid structured output.")
    return parsed


__all__ = [
    "CONTEXTUALIZATION_SCHEMA_V1",
    "GROUNDED_GENERATION_SCHEMA_V1",
    "StructuredOutputValidationError",
    "parse_contextualization_v1",
    "parse_grounded_generation_v1",
]
