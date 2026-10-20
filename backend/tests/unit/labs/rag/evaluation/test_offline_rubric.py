"""Public synthetic replay; no runtime, network, or model imports/calls."""

import json
from pathlib import Path
from uuid import UUID

import pytest

from ai_workshop.labs.rag.evaluation.offline_rubric import (
    Answer,
    Claim,
    Evidence,
    Rubric,
    assess,
)
from ai_workshop.labs.rag.generation.citation_validation import CitationValidator
from ai_workshop.labs.rag.generation.domain import (
    GeneratedClaim,
    GenerationStatus,
    GroundingEvidence,
    StructuredGeneration,
)

FIXTURE = Path(__file__).parents[4] / "fixtures/rag/offline_payment_rubric.json"


def benchmark() -> tuple[Rubric, tuple[Evidence, ...], Answer]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return (
        Rubric.model_validate(data["rubric"]),
        tuple(Evidence.model_validate(item) for item in data["evidence"]),
        Answer.model_validate(data["observed_answer"]),
    )


def with_claims(*claims: Claim) -> Answer:
    return Answer(
        status="answered",
        answer=" ".join(c.text for c in claims),
        claims=claims,
        citation_validation="passed",
    )


def rule_claim(rubric: Rubric, text: str | None = None) -> Claim:
    return Claim(
        text=text or "AM-SYN-101은 접수일 T+4 영업일에 대금을 지급한다.",
        evidence_ids=tuple(e.evidence_id for e in rubric.rules[0].support),
    )


def codes(answer: Answer, rubric: Rubric, evidence: tuple[Evidence, ...]) -> set[str]:
    return {f.code for f in assess(answer, rubric, evidence).findings}


def test_stored_failure_is_not_semantically_passed_by_valid_citations() -> None:
    rubric, evidence, answer = benchmark()
    assert answer.citation_validation == "passed"
    report = assess(answer, rubric, evidence)
    assert report.status == "failed"
    assert report.semantic_correctness == "unreviewed"
    assert {f.code for f in report.findings} >= {
        "required_rule_missing",
        "example_condition_missing",
        "example_support_incomplete",
    }


def test_actual_lexical_validator_and_offline_rubric_have_distinct_outcomes() -> None:
    rubric, evidence, answer = benchmark()
    # Synthetic provenance only: this exercises the real validator without DB access.
    source_id = UUID(int=100)
    grounding = tuple(
        GroundingEvidence(
            evidence_id=e.evidence_id,
            text=e.text,
            document_id=source_id,
            asset_version_id=source_id,
            projection_id=source_id,
            chunk_id=e.evidence_id,
            element_id=e.evidence_id,
            page=2,
            char_start=0,
            char_end=len(e.text),
            bbox=None,
        )
        for e in evidence
    )
    draft = StructuredGeneration(
        schema_version=1,
        claims=tuple(
            GeneratedClaim(text=c.text, evidence_ids=c.evidence_ids) for c in answer.claims
        ),
    )
    outcome = CitationValidator().validate(draft, allowed_evidence=grounding)
    assert outcome.status is GenerationStatus.ANSWERED
    assert outcome.text == answer.answer
    assert assess(answer, rubric, evidence).status == "failed"


@pytest.mark.parametrize(
    "text",
    [
        "AM-SYN-101은 접수일 T+4 영업일에 대금을 지급한다.",
        "AM-SYN-101 대금은 접수일 기준 4 영업일 후 지급됩니다.",
        "AM-SYN-101은 접수일 기준 네 영업일 뒤 지급됩니다.",
    ],
)
def test_rule_only_variants_need_review_but_no_example_condition(text: str) -> None:
    rubric, evidence, _ = benchmark()
    report = assess(with_claims(rule_claim(rubric, text)), rubric, evidence)
    assert report.status == "unreviewed"
    assert report.findings == ()
    assert report.semantic_review_required is True


@pytest.mark.parametrize(
    "text",
    [
        "AM-SYN-101은 접수일 T+9 영업일에 대금을 지급한다.",
        "AM-SYN-101은 접수일 T+4일에 대금을 지급한다.",
        "AM-SYN-202는 접수일 T+4 영업일에 대금을 지급한다.",
        "AM-SYN-101은 신청일 T+4 영업일에 대금을 지급한다.",
    ],
)
def test_rule_dimensions_are_not_interchangeable(text: str) -> None:
    rubric, evidence, _ = benchmark()
    assert "required_rule_missing" in codes(with_claims(rule_claim(rubric, text)), rubric, evidence)


def test_example_citations_cannot_support_general_rule() -> None:
    rubric, evidence, observed = benchmark()
    claim = rule_claim(rubric).model_copy(update={"evidence_ids": observed.claims[1].evidence_ids})
    assert "rule_support_incomplete" in codes(with_claims(claim), rubric, evidence)


def test_rule_components_cannot_be_pooled_between_claims() -> None:
    rubric, evidence, _ = benchmark()
    first = rule_claim(rubric, "AM-SYN-101은 접수일을 기준으로 한다.")
    second = rule_claim(rubric, "T+4 영업일에 지급한다.")
    assert "required_rule_missing" in codes(with_claims(first, second), rubric, evidence)


def test_unrelated_claim_cannot_supply_example_condition_or_citations() -> None:
    rubric, evidence, observed = benchmark()
    condition = Claim(
        text="다른 상품의 예시 기간에는 휴일이 없다.",
        evidence_ids=tuple(q.evidence_id for q in rubric.examples[0].support),
    )
    answer = with_claims(rule_claim(rubric), observed.claims[1], condition)
    assert codes(answer, rubric, evidence) >= {
        "example_condition_missing",
        "example_support_incomplete",
    }


def test_complete_rule_and_conditional_example_still_require_semantic_review() -> None:
    rubric, evidence, _ = benchmark()
    example = Claim(
        text="예시 기간에 휴일이 없으면 AM-SYN-101의 대금 지급일은 09-14이다.",
        evidence_ids=tuple(q.evidence_id for q in rubric.examples[0].support),
    )
    report = assess(with_claims(rule_claim(rubric), example), rubric, evidence)
    assert report.status == "unreviewed"
    assert report.findings == ()


def test_example_text_triggers_check_even_with_unrelated_citation() -> None:
    rubric, evidence, _ = benchmark()
    example = rule_claim(rubric, "대금 지급일은 09-14이다.")
    assert "example_condition_missing" in codes(
        with_claims(rule_claim(rubric), example), rubric, evidence
    )


def test_unknown_paraphrase_and_negation_never_become_semantic_success() -> None:
    rubric, evidence, _ = benchmark()
    # A false negative and false positives of literal matching are deliberately visible.
    paraphrase = "이 상품은 접수 후 나흘의 업무일이 지나 돈을 돌려준다."
    report = assess(with_claims(rule_claim(rubric, paraphrase)), rubric, evidence)
    assert report.status == "failed"
    assert report.semantic_review_required
    for text in [
        "AM-SYN-101은 접수일 T+4 영업일에 대금을 지급하지 않는다.",
        "AM-SYN-101 / 접수일 / T+4 영업일 / 지급",
    ]:
        report = assess(with_claims(rule_claim(rubric, text)), rubric, evidence)
        assert report.status == "unreviewed"
        assert report.semantic_review_required


@pytest.mark.parametrize("mutation", ["altered", "missing", "duplicate"])
def test_invalid_source_is_not_reported_as_model_error(mutation: str) -> None:
    rubric, evidence, observed = benchmark()
    target = rubric.rules[0].support[0].evidence_id
    if mutation == "altered":
        evidence = tuple(
            e.model_copy(update={"text": "altered"}) if e.evidence_id == target else e
            for e in evidence
        )
    elif mutation == "missing":
        evidence = tuple(e for e in evidence if e.evidence_id != target)
    else:
        evidence = (*evidence, evidence[0])
    assert assess(observed, rubric, evidence).status == "invalid_input"


def test_unknown_citation_and_answer_claim_mismatch_are_invalid() -> None:
    rubric, evidence, _ = benchmark()
    claim = rule_claim(rubric).model_copy(update={"evidence_ids": (UUID(int=1),)})
    assert assess(with_claims(claim), rubric, evidence).status == "invalid_input"
    answer = with_claims(rule_claim(rubric)).model_copy(update={"answer": "unrelated"})
    assert assess(answer, rubric, evidence).status == "invalid_input"


def test_invalid_citation_status_cannot_disappear_behind_rubric() -> None:
    rubric, evidence, _ = benchmark()
    answer = with_claims(rule_claim(rubric)).model_copy(update={"citation_validation": "failed"})
    assert "citation_validation_not_passed" in codes(answer, rubric, evidence)


def test_abstention_and_execution_error_do_not_pass_positive_rubric() -> None:
    rubric, evidence, _ = benchmark()
    for status, expected in [("insufficient_evidence", "failed"), ("error", "unreviewed")]:
        answer = Answer.model_validate(
            {
                "status": status,
                "answer": "",
                "claims": [],
                "citation_validation": "not_applicable_no_claims",
            }
        )
        assert assess(answer, rubric, evidence).status == expected


def test_rubric_is_data_driven_and_digests_bind_exact_inputs() -> None:
    rubric, evidence, _ = benchmark()
    data = rubric.model_dump_json().replace("AM-SYN-101", "ZX-73").replace("T+4", "T+7")
    changed_rubric = Rubric.model_validate_json(data)
    changed_evidence = tuple(
        Evidence.model_validate_json(
            e.model_dump_json().replace("AM-SYN-101", "ZX-73").replace("T+4", "T+7")
        )
        for e in evidence
    )
    answer = with_claims(rule_claim(changed_rubric, "ZX-73은 접수일 T+7 영업일에 지급한다."))
    report = assess(answer, changed_rubric, changed_evidence)
    original = assess(with_claims(rule_claim(rubric)), rubric, evidence)
    assert report.findings == ()
    assert report.status == "unreviewed"
    assert report.rubric_digest != original.rubric_digest
    assert report.input_digest != original.input_digest


def test_empty_terms_and_unbound_trigger_are_rejected() -> None:
    rubric, _, _ = benchmark()
    data = rubric.model_dump(mode="json")
    data["rules"][0]["terms"] = [[]]
    with pytest.raises(ValueError):
        Rubric.model_validate(data)
    data = rubric.model_dump(mode="json")
    data["examples"][0]["trigger_evidence_ids"] = [str(UUID(int=1))]
    with pytest.raises(ValueError):
        Rubric.model_validate(data)
