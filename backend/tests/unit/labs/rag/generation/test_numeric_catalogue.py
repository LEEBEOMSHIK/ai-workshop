from dataclasses import replace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.profile import resolve_evidence_budget

from .numeric_proof_fixtures import numeric_evidence, numeric_fixture, numeric_profile


def test_v6_accepts_explicit_context_budget():
    budget = resolve_evidence_budget(
        {
            "prompt_ref": "rag-codex-answer-v6",
            "context_evidence": {
                "version": 1,
                "max_groups": 2,
                "max_units": 4,
                "max_characters": 1000,
            },
        }
    )
    assert budget is not None and budget.max_units == 4


def test_nonce_and_occurrence_bindings():
    first = numeric_fixture(("rate 0.90% twice 0.90%", "rate 0.90%"))
    second = numeric_fixture(("rate 0.90% twice 0.90%", "rate 0.90%"))
    assert len({t.token_id for t in first.catalogue.tokens}) == 3
    assert first.catalogue.tokens[0].token_id != second.catalogue.tokens[0].token_id
    assert [(t.start, t.end, str(t.value), t.unit) for t in first.catalogue.tokens] == [
        (5, 10, "0.90", "%"),
        (17, 22, "0.90", "%"),
        (5, 10, "0.90", "%"),
    ]


def test_bare_cell_and_invalid_literals_are_not_operands():
    fixture = numeric_fixture(("1234 2026-10-05 malformed 1,00원 valid −1.2% and 2 만원",))
    assert [(str(t.value), t.unit) for t in fixture.catalogue.tokens] == [
        ("-1.2", "%"),
        ("2", "만원"),
    ]


@pytest.mark.parametrize("text", ["1e3원", "1E+3원", "1e-3원", "0x10원", "1/3원"])
def test_unsupported_numeric_literal_does_not_supply_a_suffix_operand(text):
    assert numeric_fixture((text,)).catalogue.tokens == ()


def test_unsupported_numeric_result_cannot_be_a_calculation_span():
    from ai_workshop.labs.rag.generation.numeric_catalogue import numeric_occurrences

    assert numeric_occurrences("1e3만원", max_digits=30) == ()


@pytest.mark.parametrize(
    "text", ["1원 " * 513, "1" * 31 + "원"], ids=["token-count", "digit-count"]
)
def test_catalogue_and_digit_limits(text):
    with pytest.raises(ValueError, match="calculation_limit_exceeded"):
        numeric_fixture((text,))


def test_unknown_policy_and_legacy_policy_injection_rejected():
    from ai_workshop.labs.rag.models.numeric_proof_policy import resolve_numeric_proof_policy

    assert resolve_numeric_proof_policy({}) is None
    for schema, ref, prompt in [
        (3, "unknown", "rag-codex-answer-v6"),
        (2, "source-numeric-proof-v1", "rag-codex-answer-v5"),
        (3, None, "rag-codex-answer-v6"),
    ]:
        with pytest.raises(ValueError):
            resolve_numeric_proof_policy(
                {
                    "prompt_ref": prompt,
                    "generation": {
                        "response_schema_version": schema,
                        "numeric_proof_policy_ref": ref,
                    },
                }
            )


def test_changed_source_revision_changes_identity():
    from ai_workshop.labs.rag.generation.numeric_catalogue import build_source_value_catalogue

    evidence = numeric_evidence("1원")
    first = build_source_value_catalogue(
        (evidence,),
        request_id=UUID(int=30),
        configuration_version_id=UUID(int=20),
        profile=numeric_profile(),
    )
    second = build_source_value_catalogue(
        (replace(evidence, asset_version_id=UUID(int=90)),),
        request_id=UUID(int=30),
        configuration_version_id=UUID(int=20),
        profile=numeric_profile(),
    )
    assert first.digest != second.digest
    assert first.tokens[0].token_id != second.tokens[0].token_id
