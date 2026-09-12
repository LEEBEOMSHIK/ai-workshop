from __future__ import annotations

import traceback
from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.domain import (
    GeneratedClaim,
    GenerationStatus,
    StructuredGeneration,
)
from ai_workshop.labs.rag.generation.structured_output import (
    StructuredOutputValidationError,
)
from ai_workshop.labs.rag.generation.structured_output_v2 import (
    GROUNDED_GENERATION_SCHEMA_V2,
    GroundedGenerationResultV2,
    parse_grounded_generation_v2,
)

EVIDENCE_ID = UUID("11111111-1111-4111-8111-111111111111")
SECOND_EVIDENCE_ID = UUID("22222222-2222-4222-8222-222222222222")
DISALLOWED_EVIDENCE_ID = UUID("33333333-3333-4333-8333-333333333333")


def test_insufficient_has_no_claims() -> None:
    result = parse_grounded_generation_v2(
        '{"schema_version":2,"status":"insufficient_evidence"}',
        allowed_evidence_ids=(),
    )

    assert result.status is GenerationStatus.INSUFFICIENT_EVIDENCE
    assert result.generation is None


def test_answered_preserves_claim_text_and_evidence_order() -> None:
    result = parse_grounded_generation_v2(
        '{"schema_version":2,"status":"answered","claims":['
        '{"text":"첫 번째 근거 답변입니다.","evidence_ids":['
        '"11111111-1111-4111-8111-111111111111",'
        '"22222222-2222-4222-8222-222222222222"]}]}',
        allowed_evidence_ids=(EVIDENCE_ID, SECOND_EVIDENCE_ID),
    )

    assert result.status is GenerationStatus.ANSWERED
    assert result.generation is not None
    assert result.generation.schema_version == 2
    assert len(result.generation.claims) == 1
    assert result.generation.claims[0].text == "첫 번째 근거 답변입니다."
    assert result.generation.claims[0].evidence_ids == (
        EVIDENCE_ID,
        SECOND_EVIDENCE_ID,
    )


def test_grounded_generation_schema_v2_has_two_closed_exact_status_shapes() -> None:
    branches = GROUNDED_GENERATION_SCHEMA_V2["oneOf"]
    branches_by_status = {branch["properties"]["status"]["enum"][0]: branch for branch in branches}

    assert set(branches_by_status) == {"answered", "insufficient_evidence"}
    answered = branches_by_status["answered"]
    insufficient = branches_by_status["insufficient_evidence"]
    assert set(answered) == {
        "type",
        "additionalProperties",
        "required",
        "properties",
    }
    assert answered["type"] == "object"
    assert answered["additionalProperties"] is False
    assert set(answered["required"]) == {"schema_version", "status", "claims"}
    assert set(answered["properties"]) == {"schema_version", "status", "claims"}
    assert set(insufficient) == {
        "type",
        "additionalProperties",
        "required",
        "properties",
    }
    assert insufficient["type"] == "object"
    assert insufficient["additionalProperties"] is False
    assert set(insufficient["required"]) == {"schema_version", "status"}
    assert set(insufficient["properties"]) == {"schema_version", "status"}


def test_grounded_generation_schema_v2_expresses_static_claim_constraints() -> None:
    branches = GROUNDED_GENERATION_SCHEMA_V2["oneOf"]
    answered = next(
        branch for branch in branches if branch["properties"]["status"]["enum"] == ["answered"]
    )
    claims = answered["properties"]["claims"]
    claim = claims["items"]
    text = claim["properties"]["text"]
    evidence_ids = claim["properties"]["evidence_ids"]

    assert claims["minItems"] == 1
    assert claim["type"] == "object"
    assert claim["additionalProperties"] is False
    assert set(claim["required"]) == {"text", "evidence_ids"}
    assert set(claim["properties"]) == {"text", "evidence_ids"}
    assert text == {"type": "string", "pattern": r"\S"}
    assert evidence_ids["minItems"] == 1
    assert evidence_ids["uniqueItems"] is True
    assert evidence_ids["items"] == {"type": "string"}


@pytest.mark.parametrize(
    "content",
    [
        '{"schema_version":1,"status":"answered","claims":['
        '{"text":"answer","evidence_ids":['
        '"11111111-1111-4111-8111-111111111111"]}]}',
        '{"schema_version":true,"status":"insufficient_evidence"}',
        '{"schema_version":2.0,"status":"insufficient_evidence"}',
        '{"schema_version":2,"status":"answered","claims":['
        '{"text":"answer","evidence_ids":['
        '"11111111-1111-4111-8111-111111111111"]}],"extra":null}',
        '{"schema_version":2,"status":"insufficient_evidence","claims":[]}',
        '{"schema_version":2,"status":"insufficient_evidence","explanation":"근거가 없습니다."}',
        '{"schema_version":2,"status":"answered","claims":[]}',
        '{"schema_version":2,"status":"answered","claims":['
        '{"text":"","evidence_ids":['
        '"11111111-1111-4111-8111-111111111111"]}]}',
        '{"schema_version":2,"status":"answered","claims":['
        '{"text":"   ","evidence_ids":['
        '"11111111-1111-4111-8111-111111111111"]}]}',
        '{"schema_version":2,"status":"answered","claims":[{"text":"answer","evidence_ids":[]}]}',
        '{"schema_version":2,"status":"answered","claims":['
        '{"text":"answer","evidence_ids":['
        '"11111111-1111-4111-8111-111111111111",'
        '"11111111-1111-4111-8111-111111111111"]}]}',
        '{"schema_version":2,"status":"answered","claims":['
        '{"text":"answer","evidence_ids":['
        '"11111111-1111-4111-8111-111111111111",'
        '"{11111111-1111-4111-8111-111111111111}"]}]}',
        '{"schema_version":2,"status":"answered","claims":['
        '{"text":"answer","evidence_ids":['
        '"33333333-3333-4333-8333-333333333333"]}]}',
        '{"schema_version":2,"status":"answered","claims":['
        '{"text":"answer","evidence_ids":["not-a-uuid"]}]}',
        '{"schema_version":2,"schema_version":2,"status":"insufficient_evidence"}',
        '{"schema_version":2,"status":"answered","claims":['
        '{"text":"answer","text":"replacement","evidence_ids":['
        '"11111111-1111-4111-8111-111111111111"]}]}',
        "[]",
        '{"schema_version":2,"status":"insufficient_evidence"',
        '{"schema_version":2,"status":"insufficient_evidence"} {}',
        '{"schema_version":NaN,"status":"insufficient_evidence"}',
        '{"schema_version":Infinity,"status":"insufficient_evidence"}',
        '{"schema_version":-Infinity,"status":"insufficient_evidence"}',
    ],
    ids=[
        "v1-payload",
        "boolean-schema-version",
        "float-schema-version",
        "answered-extra-key",
        "insufficient-claims",
        "insufficient-explanation",
        "empty-claims",
        "empty-text",
        "whitespace-text",
        "empty-evidence-ids",
        "duplicate-evidence-id",
        "normalized-duplicate-evidence-id",
        "disallowed-evidence-id",
        "invalid-evidence-id",
        "duplicate-root-key",
        "duplicate-nested-key",
        "non-object",
        "truncated-json",
        "multiple-json-values",
        "nan",
        "infinity",
        "negative-infinity",
    ],
)
def test_invalid_grounded_generation_output_is_rejected(content: str) -> None:
    with pytest.raises(
        StructuredOutputValidationError,
        match=r"^Invalid grounded generation output\.$",
    ):
        parse_grounded_generation_v2(
            content,
            allowed_evidence_ids=(EVIDENCE_ID,),
        )


@pytest.mark.parametrize(
    "content",
    [
        '{"schema_version":2,"status":"answered","claims":['
        '{"text":1e999,"evidence_ids":['
        '"11111111-1111-4111-8111-111111111111"]}]}',
        '{"schema_version":2,"status":"answered","claims":['
        '{"text":"answer","evidence_ids":[1e999]}]}',
    ],
    ids=["claim-text", "evidence-id"],
)
def test_nested_overflow_number_is_rejected_without_an_exception_chain(
    content: str,
) -> None:
    with pytest.raises(
        StructuredOutputValidationError,
        match=r"^Invalid grounded generation output\.$",
    ) as captured:
        parse_grounded_generation_v2(
            content,
            allowed_evidence_ids=(EVIDENCE_ID,),
        )

    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize(
    ("status", "generation"),
    [
        (GenerationStatus.ANSWERED, None),
        (
            GenerationStatus.INSUFFICIENT_EVIDENCE,
            StructuredGeneration(
                schema_version=2,
                claims=(GeneratedClaim("answer", (EVIDENCE_ID,)),),
            ),
        ),
        (
            GenerationStatus.ANSWERED,
            StructuredGeneration(
                schema_version=1,
                claims=(GeneratedClaim("answer", (EVIDENCE_ID,)),),
            ),
        ),
        (
            GenerationStatus.ANSWERED,
            StructuredGeneration(schema_version=2, claims=()),
        ),
        (GenerationStatus.NOT_REQUESTED, None),
    ],
    ids=[
        "answered-without-generation",
        "insufficient-with-generation",
        "answered-with-v1-generation",
        "answered-without-claims",
        "unsupported-status",
    ],
)
def test_result_rejects_conflicting_status_and_generation(
    status: GenerationStatus,
    generation: StructuredGeneration | None,
) -> None:
    with pytest.raises(ValueError, match=r"^Invalid grounded generation result\.$"):
        GroundedGenerationResultV2(status=status, generation=generation)


def test_result_is_frozen() -> None:
    result = GroundedGenerationResultV2(
        status=GenerationStatus.INSUFFICIENT_EVIDENCE,
        generation=None,
    )

    with pytest.raises(FrozenInstanceError):
        result.generation = StructuredGeneration(  # type: ignore[misc]
            schema_version=2,
            claims=(),
        )


def test_malformed_output_does_not_leak_content_through_the_exception_chain() -> None:
    canary = "SENSITIVE-CONTENT-CANARY-8d4f"
    content = f'{{"schema_version":2,"status":"{canary}"'

    with pytest.raises(StructuredOutputValidationError) as captured:
        parse_grounded_generation_v2(content, allowed_evidence_ids=())

    error = captured.value
    rendered = "".join(traceback.format_exception(error))
    assert canary not in str(error)
    assert canary not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None


def test_malformed_uuid_does_not_leak_content_through_the_exception_chain() -> None:
    canary = "PRIVATECANARY".ljust(32, "z")
    content = (
        '{"schema_version":2,"status":"answered","claims":['
        f'{{"text":"answer","evidence_ids":["{canary}"]}}]}}'
    )

    with pytest.raises(StructuredOutputValidationError) as captured:
        parse_grounded_generation_v2(content, allowed_evidence_ids=())

    error = captured.value
    rendered = "".join(traceback.format_exception(error))
    assert canary not in str(error)
    assert canary not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None
