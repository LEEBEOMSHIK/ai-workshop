"""Codex-compatible closed wire object for response schema3."""

import json
from collections.abc import Collection
from uuid import UUID

from ai_workshop.labs.rag.models.numeric_proof_policy import NumericProofPolicy

from .structured_output_v2 import _raise_invalid_output, _strict_json_object
from .structured_output_v3 import (
    NUMERIC_CLAIM_SCHEMA,
    GroundedGenerationResultV3,
    parse_grounded_generation_v3,
)

CODEX_GROUNDED_WIRE_SCHEMA_V2: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "status", "claims"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [3]},
        "status": {"type": "string", "enum": ["answered", "insufficient_evidence"]},
        "claims": {"type": "array", "items": NUMERIC_CLAIM_SCHEMA},
    },
}


def parse_codex_grounded_wire_v2(
    content: str, *, allowed_evidence_ids: Collection[UUID], policy: NumericProofPolicy
) -> GroundedGenerationResultV3:
    parsed = dict(_strict_json_object(content))
    if set(parsed) != {"schema_version", "status", "claims"}:
        _raise_invalid_output()
    if parsed.get("status") == "insufficient_evidence":
        if type(parsed["claims"]) is not list or parsed["claims"]:
            _raise_invalid_output()
        del parsed["claims"]
    return parse_grounded_generation_v3(
        json.dumps(parsed, ensure_ascii=False, allow_nan=False),
        allowed_evidence_ids=allowed_evidence_ids,
        policy=policy,
    )
