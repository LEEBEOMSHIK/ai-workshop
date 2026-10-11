"""Closed source-numeric proof response contract; legacy parsers stay intact."""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from ai_workshop.labs.rag.models.numeric_proof_policy import NumericProofPolicy

from .domain import GeneratedClaim, GenerationStatus, StructuredGeneration
from .numeric_proof_types import CalculationOperation, CalculationProposal
from .structured_output import StructuredOutputValidationError
from .structured_output_v2 import _raise_invalid_output, _strict_json_object

CALCULATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["operation", "operand_token_ids", "result_start", "result_end"],
    "properties": {
        "operation": {
            "type": "string",
            "enum": ["percentage_point_difference", "convert_krw_unit"],
        },
        "operand_token_ids": {"type": "array", "items": {"type": "string"}},
        "result_start": {"type": "integer"},
        "result_end": {"type": "integer"},
    },
}
NUMERIC_CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["text", "evidence_ids", "calculations"],
    "properties": {
        "text": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "calculations": {"type": "array", "items": CALCULATION_SCHEMA},
    },
}


@dataclass(frozen=True, slots=True)
class GroundedGenerationResultV3:
    status: GenerationStatus
    generation: StructuredGeneration | None


def parse_grounded_generation_v3(
    content: str, *, allowed_evidence_ids: Collection[UUID], policy: NumericProofPolicy
) -> GroundedGenerationResultV3:
    parsed = _strict_json_object(content)
    if type(parsed.get("schema_version")) is not int or parsed["schema_version"] != 3:
        _raise_invalid_output()
    if parsed.get("status") == "insufficient_evidence" and set(parsed) == {
        "schema_version",
        "status",
    }:
        return GroundedGenerationResultV3(GenerationStatus.INSUFFICIENT_EVIDENCE, None)
    if parsed.get("status") != "answered" or set(parsed) != {"schema_version", "status", "claims"}:
        _raise_invalid_output()
    raw = parsed["claims"]
    if type(raw) is not list or not raw:
        _raise_invalid_output()
    if len(raw) > policy.max_claims:
        raise StructuredOutputValidationError("calculation_limit_exceeded")
    claims: list[GeneratedClaim] = []
    total = 0
    for claim in raw:
        if type(claim) is not dict or set(claim) != {"text", "evidence_ids", "calculations"}:
            _raise_invalid_output()
        text = claim["text"]
        if (
            type(text) is not str
            or not text
            or text != text.strip()
            or "\0" in text
            or any(0xD800 <= ord(c) <= 0xDFFF for c in text)
        ):
            _raise_invalid_output()
        ids, raw_proofs = claim["evidence_ids"], claim["calculations"]
        if type(ids) is not list or not ids or any(type(identity) is not str for identity in ids):
            _raise_invalid_output()
        try:
            evidence_ids = tuple(UUID(identity) for identity in ids)
        except ValueError:
            _raise_invalid_output()
        if len(set(evidence_ids)) != len(evidence_ids) or not set(evidence_ids) <= set(
            allowed_evidence_ids
        ):
            _raise_invalid_output()
        if type(raw_proofs) is not list:
            _raise_invalid_output()
        total += len(raw_proofs)
        if len(raw_proofs) > policy.max_calculations_per_claim or total > policy.max_calculations:
            raise StructuredOutputValidationError("calculation_limit_exceeded")
        proofs: list[CalculationProposal] = []
        for proof in raw_proofs:
            if type(proof) is not dict or set(proof) != {
                "operation",
                "operand_token_ids",
                "result_start",
                "result_end",
            }:
                _raise_invalid_output()
            operation = proof["operation"]
            if operation not in ("percentage_point_difference", "convert_krw_unit"):
                _raise_invalid_output()
            operands = proof["operand_token_ids"]
            if type(operands) is not list or len(operands) != (
                2 if operation == "percentage_point_difference" else 1
            ):
                _raise_invalid_output()
            if any(
                type(token) is not str
                or len(token) != 64
                or any(c not in "0123456789abcdef" for c in token)
                for token in operands
            ):
                _raise_invalid_output()
            start, end = proof["result_start"], proof["result_end"]
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                _raise_invalid_output()
            proofs.append(
                CalculationProposal(
                    cast(CalculationOperation, operation), tuple(operands), start, end
                )
            )
        value = GeneratedClaim(text, evidence_ids, tuple(proofs))
        if value in claims:
            _raise_invalid_output()
        claims.append(value)
    return GroundedGenerationResultV3(
        GenerationStatus.ANSWERED, StructuredGeneration(3, tuple(claims))
    )
