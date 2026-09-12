from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from contextlib import suppress
from dataclasses import dataclass
from math import isfinite
from typing import Any, NoReturn, cast
from uuid import UUID

from ai_workshop.labs.rag.generation.domain import (
    GenerationStatus,
    StructuredGeneration,
)
from ai_workshop.labs.rag.generation.structured_output import (
    StructuredOutputValidationError,
    parse_grounded_generation_v1,
)

_CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "evidence_ids"],
    "properties": {
        "text": {"type": "string", "pattern": r"\S"},
        "evidence_ids": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string"},
        },
    },
}

GROUNDED_GENERATION_SCHEMA_V2: dict[str, Any] = {
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "status", "claims"],
            "properties": {
                "schema_version": {"type": "integer", "enum": [2]},
                "status": {"type": "string", "enum": ["answered"]},
                "claims": {
                    "type": "array",
                    "minItems": 1,
                    "items": _CLAIM_SCHEMA,
                },
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "status"],
            "properties": {
                "schema_version": {"type": "integer", "enum": [2]},
                "status": {
                    "type": "string",
                    "enum": ["insufficient_evidence"],
                },
            },
        },
    ]
}


@dataclass(frozen=True, slots=True)
class GroundedGenerationResultV2:
    status: GenerationStatus
    generation: StructuredGeneration | None

    def __post_init__(self) -> None:
        if self.status is GenerationStatus.ANSWERED:
            if (
                self.generation is None
                or self.generation.schema_version != 2
                or not self.generation.claims
            ):
                raise ValueError("Invalid grounded generation result.")
            return
        if self.status is not GenerationStatus.INSUFFICIENT_EVIDENCE or self.generation is not None:
            raise ValueError("Invalid grounded generation result.")


def parse_grounded_generation_v2(
    content: str,
    *,
    allowed_evidence_ids: Collection[UUID],
) -> GroundedGenerationResultV2:
    parsed = _strict_json_object(content)
    if type(parsed.get("schema_version")) is not int or parsed["schema_version"] != 2:
        _raise_invalid_output()

    status = parsed.get("status")
    if type(status) is not str:
        _raise_invalid_output()
    if status == "insufficient_evidence":
        if set(parsed) != {"schema_version", "status"}:
            _raise_invalid_output()
        return GroundedGenerationResultV2(
            GenerationStatus.INSUFFICIENT_EVIDENCE,
            None,
        )
    if status != "answered" or set(parsed) != {
        "schema_version",
        "status",
        "claims",
    }:
        _raise_invalid_output()

    v1_content = json.dumps(
        {"schema_version": 1, "claims": parsed["claims"]},
        ensure_ascii=False,
        allow_nan=False,
    )
    validated_v1: StructuredGeneration | None = None
    with suppress(StructuredOutputValidationError):
        validated_v1 = parse_grounded_generation_v1(
            v1_content,
            allowed_evidence_ids=allowed_evidence_ids,
        )
    if validated_v1 is None:
        _raise_invalid_output()
    generation = StructuredGeneration(
        schema_version=2,
        claims=validated_v1.claims,
    )
    return GroundedGenerationResultV2(GenerationStatus.ANSWERED, generation)


class _InvalidStrictJson(ValueError):
    pass


def _strict_json_object(content: str) -> Mapping[str, Any]:
    failed = False
    try:
        parsed = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
            parse_float=_parse_finite_float,
        )
    except (TypeError, ValueError, RecursionError):
        failed = True
        parsed = None
    if failed or not isinstance(parsed, Mapping):
        _raise_invalid_output()
    return cast(Mapping[str, Any], parsed)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise _InvalidStrictJson
        parsed[key] = value
    return parsed


def _reject_nonstandard_constant(_value: str) -> NoReturn:
    raise _InvalidStrictJson


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not isfinite(parsed):
        raise _InvalidStrictJson
    return parsed


def _raise_invalid_output() -> NoReturn:
    raise StructuredOutputValidationError("Invalid grounded generation output.")


__all__ = [
    "GROUNDED_GENERATION_SCHEMA_V2",
    "GroundedGenerationResultV2",
    "parse_grounded_generation_v2",
]
