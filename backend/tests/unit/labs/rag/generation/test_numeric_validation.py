from dataclasses import replace
from decimal import getcontext
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.domain import (
    GeneratedClaim,
    GenerationStatus,
    StructuredGeneration,
)
from ai_workshop.labs.rag.generation.numeric_proof_types import CalculationProposal

from .numeric_proof_fixtures import numeric_fixture


def validate(fixture, claim, **overrides):
    from ai_workshop.labs.rag.generation.numeric_validation import NumericProofValidator

    context = {
        "evidence": fixture.evidence,
        "catalogue": fixture.catalogue,
        "profile": fixture.profile,
        "request_id": fixture.catalogue.request_id,
        "configuration_version_id": UUID(int=20),
    }
    context.update(overrides)
    return NumericProofValidator().validate(StructuredGeneration(3, (claim,)), **context)


def claim(fixture, text, operation="percentage_point_difference", *, start=None, end=None):
    start = start if start is not None else text.index("result ") + 7
    return GeneratedClaim(
        text,
        tuple(e.evidence_id for e in fixture.evidence),
        (
            CalculationProposal(
                operation,
                tuple(t.token_id for t in fixture.catalogue.tokens),
                start,
                end if end is not None else len(text),
            ),
        ),
    )


@pytest.mark.parametrize(
    "left,right,result",
    [
        ("0.30%", "0.20%", "0.10%p"),
        ("-0.30%", "-0.20%", "-0.10%p"),
        ("0.20%", "0.30%", "-0.10%p"),
        ("0.2%", "0.2%", "0%p"),
    ],
)
def test_signed_percent_difference(left, right, result):
    fixture = numeric_fixture((left, right))
    validated = validate(fixture, claim(fixture, "result " + result))
    assert validated.outcome.status is GenerationStatus.ANSWERED
    proof = validated.outcome.citations[0].calculations[0]
    assert proof.operands[0].char_start == 10
    assert proof.operands[0].unit == "%"


@pytest.mark.parametrize(
    "source,result",
    [
        ("1억원", "10000만원"),
        ("12,300만원", "1.23억원"),
        ("1원", "0.0001만원"),
        ("-2만원", "-20000원"),
    ],
)
def test_exact_krw_conversion(source, result):
    fixture = numeric_fixture((source,))
    assert (
        validate(fixture, claim(fixture, "result " + result, "convert_krw_unit")).outcome.status
        is GenerationStatus.ANSWERED
    )


def test_proof_only_supports_its_claim_occurrence():
    fixture = numeric_fixture(("0.30%", "0.20%"))
    text = "result 0.10%p and 0.10%p"
    validated = validate(fixture, claim(fixture, text, end=13))
    assert validated.outcome.reason_codes == ("exact_value_not_supported",)
    assert validated.outcome.text is None and validated.payload is None


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("value", "calculation_result_mismatch"),
        ("unit", "calculation_unit_not_supported"),
        ("span", "calculation_result_span_invalid"),
        ("self-citation", "calculation_operand_not_supported"),
        ("request", "calculation_operand_not_supported"),
        ("same-token", "calculation_operand_not_supported"),
    ],
)
def test_wrong_result_unit_self_citation_or_request_rejected(mutation, reason):
    fixture = numeric_fixture(("0.30%", "0.20%"))
    value = claim(fixture, "result 0.10%p")
    overrides = {}
    if mutation == "value":
        value = replace(value, text="result 0.11%p")
    elif mutation == "unit":
        value = replace(
            value,
            text="result 0.10%",
            calculations=(replace(value.calculations[0], result_end=12),),
        )
    elif mutation == "span":
        value = replace(value, calculations=(replace(value.calculations[0], result_start=8),))
    elif mutation == "self-citation":
        value = replace(value, evidence_ids=(fixture.evidence[0].evidence_id,))
    elif mutation == "request":
        overrides["request_id"] = UUID(int=999)
    else:
        value = replace(
            value,
            calculations=(
                replace(
                    value.calculations[0],
                    operand_token_ids=(fixture.catalogue.tokens[0].token_id,) * 2,
                ),
            ),
        )
    validated = validate(fixture, value, **overrides)
    assert validated.outcome.reason_codes == (reason,)
    assert validated.outcome.text is None and validated.outcome.citations == ()
    assert validated.payload is None


def test_global_decimal_context_is_unchanged():
    fixture = numeric_fixture(("0.30%", "0.20%"))
    context = getcontext()
    previous = context.copy()
    context.prec = 2
    try:
        before = context.copy()
        assert (
            validate(fixture, claim(fixture, "result 0.10%p")).outcome.status
            is GenerationStatus.ANSWERED
        )
        assert (
            context.prec == before.prec
            and context.flags == before.flags
            and context.traps == before.traps
        )
    finally:
        context.prec = previous.prec
        context.clear_flags()


def test_invalid_proof_is_not_ignored_when_direct_value_exists():
    fixture = numeric_fixture(("0.30%", "0.20%", "0.11%p"))
    value = claim(fixture, "result 0.11%p")
    value = replace(
        value,
        calculations=(
            replace(
                value.calculations[0], operand_token_ids=value.calculations[0].operand_token_ids[:2]
            ),
        ),
    )
    assert validate(fixture, value).outcome.reason_codes == ("calculation_result_mismatch",)


def test_abstention_payload_has_no_fake_calculation():
    from ai_workshop.labs.rag.generation.numeric_validation import validated_numeric_abstention

    fixture = numeric_fixture(())
    result = validated_numeric_abstention(
        catalogue=fixture.catalogue,
        profile=fixture.profile,
        request_id=fixture.catalogue.request_id,
        configuration_version_id=UUID(int=20),
    )
    assert result.payload.answer is None and result.payload.claims == ()
    assert result.outcome.status is GenerationStatus.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize("source,text", [("1e3원", "3원"), ("3원", "1e3원")])
def test_unsupported_literal_is_not_direct_numeric_support(source, text):
    fixture = numeric_fixture((source,))
    result = validate(fixture, GeneratedClaim(text, fixture.catalogue.evidence_ids))
    assert result.payload is None and result.outcome.text is None
    assert result.outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
