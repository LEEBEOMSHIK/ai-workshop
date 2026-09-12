from __future__ import annotations

import importlib.util
import json
from typing import Any
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.domain import GenerationStatus
from ai_workshop.labs.rag.generation.structured_output import StructuredOutputValidationError

EVIDENCE_ID = UUID("11111111-1111-4111-8111-111111111111")


def _wire() -> Any:
    assert importlib.util.find_spec("ai_workshop.labs.rag.generation.codex_wire") is not None, (
        "Codex wire parser is not implemented"
    )
    from ai_workshop.labs.rag.generation import codex_wire

    return codex_wire


def test_insufficient_empty_claims_normalizes_to_existing_v2_result() -> None:
    result = _wire().parse_codex_grounded_wire_v1(
        '{"schema_version":2,"status":"insufficient_evidence","claims":[]}',
        allowed_evidence_ids=(),
    )
    assert result.status is GenerationStatus.INSUFFICIENT_EVIDENCE
    assert result.generation is None


def test_answered_preserves_semantic_version_text_and_citation() -> None:
    result = _wire().parse_codex_grounded_wire_v1(
        '{"schema_version":2,"status":"answered","claims":['
        '{"text":"Synthetic grounded claim","evidence_ids":['
        '"11111111-1111-4111-8111-111111111111"]}]}',
        allowed_evidence_ids=(EVIDENCE_ID,),
    )
    assert result.status is GenerationStatus.ANSWERED
    assert result.generation.schema_version == 2
    assert result.generation.claims[0].text == "Synthetic grounded claim"
    assert result.generation.claims[0].evidence_ids == (EVIDENCE_ID,)


@pytest.mark.parametrize("content", [
    '[]', 'null', '{',
    '{"schema_version":2,"status":"insufficient_evidence"}',
    '{"schema_version":2,"status":"insufficient_evidence","claims":null}',
    '{"schema_version":2,"status":"insufficient_evidence","claims":{}}',
    '{"schema_version":2,"status":"insufficient_evidence","claims":[{}]}',
    '{"schema_version":2,"status":"insufficient_evidence","claims":[],"extra":"private"}',
    '{"schema_version":2,"status":"answered","claims":[]}',
    '{"schema_version":2,"status":"unknown","claims":[]}',
    '{"schema_version":2,"status":true,"claims":[]}',
    '{"schema_version":true,"status":"insufficient_evidence","claims":[]}',
    '{"schema_version":2.0,"status":"insufficient_evidence","claims":[]}',
    '{"schema_version":1,"status":"insufficient_evidence","claims":[]}',
    '{"schema_version":NaN,"status":"insufficient_evidence","claims":[]}',
    '{"schema_version":1e999,"status":"insufficient_evidence","claims":[]}',
    '{"schema_version":2,"schema_version":2,"status":"insufficient_evidence","claims":[]}',
    '{"schema_version":2,"status":"answered","claims":[{"text":"private",'
    '"text":"changed","evidence_ids":["11111111-1111-4111-8111-111111111111"]}]}',
])
def test_invalid_wire_shape_is_rejected_before_normalization(content: str) -> None:
    parser = _wire().parse_codex_grounded_wire_v1
    with pytest.raises(StructuredOutputValidationError) as caught:
        parser(content, allowed_evidence_ids=(EVIDENCE_ID,))
    assert "private" not in str(caught.value)
    assert caught.value.__context__ is None


@pytest.mark.parametrize("claim", [
    {"text": "", "evidence_ids": [str(EVIDENCE_ID)]},
    {"text": "  ", "evidence_ids": [str(EVIDENCE_ID)]},
    {"text": True, "evidence_ids": [str(EVIDENCE_ID)]},
    {"text": "claim", "evidence_ids": []},
    {"text": "claim", "evidence_ids": [str(UUID(int=99))]},
    {"text": "claim", "evidence_ids": [str(EVIDENCE_ID), str(EVIDENCE_ID)]},
    {"text": "claim", "evidence_ids": [str(EVIDENCE_ID), EVIDENCE_ID.hex]},
    {"text": "claim", "evidence_ids": [str(EVIDENCE_ID)], "extra": "private"},
])
def test_wire_answered_retains_all_existing_semantic_checks(claim: dict[str, Any]) -> None:
    content = json.dumps({"schema_version": 2, "status": "answered", "claims": [claim]})
    with pytest.raises(StructuredOutputValidationError):
        _wire().parse_codex_grounded_wire_v1(content, allowed_evidence_ids=(EVIDENCE_ID,))


def test_wire_schema_is_closed_object_without_unsupported_combinators() -> None:
    schema = _wire().CODEX_GROUNDED_WIRE_SCHEMA_V1
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"schema_version", "status", "claims"}
    assert set(schema["properties"]) == {"schema_version", "status", "claims"}
    assert schema["properties"]["schema_version"] == {"type": "integer", "enum": [2]}
    assert schema["properties"]["status"]["enum"] == ["answered", "insufficient_evidence"]
    claim = schema["properties"]["claims"]["items"]
    assert claim["additionalProperties"] is False
    assert set(claim["required"]) == {"text", "evidence_ids"}

    def check(value: Any) -> None:
        if isinstance(value, dict):
            assert not {"oneOf", "anyOf", "uniqueItems", "minItems"}.intersection(value)
            for nested in value.values():
                check(nested)
        elif isinstance(value, list):
            for nested in value:
                check(nested)

    check(schema)
