from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.citation_validation import CitationValidator
from ai_workshop.labs.rag.generation.domain import (
    GeneratedClaim,
    GenerationStatus,
    GroundingEvidence,
    StructuredGeneration,
)

EVIDENCE_ID = UUID("10000000-0000-0000-0000-000000000001")
PROJECTION_ID = UUID("20000000-0000-0000-0000-000000000001")


def evidence(
    *,
    evidence_id: UUID = EVIDENCE_ID,
    text: str = "위험 한도는 순자산의 7%이며 적용일은 2026-09-01입니다.",
    projection_id: UUID | None = PROJECTION_ID,
) -> GroundingEvidence:
    return GroundingEvidence(
        evidence_id=evidence_id,
        text=text,
        document_id=UUID("30000000-0000-0000-0000-000000000001"),
        asset_version_id=UUID("40000000-0000-0000-0000-000000000001"),
        projection_id=projection_id,
        chunk_id=UUID("50000000-0000-0000-0000-000000000001"),
        element_id=UUID("60000000-0000-0000-0000-000000000001"),
        page=None,
        char_start=10,
        char_end=44,
        bbox=None,
    )


def generation(*claims: GeneratedClaim) -> StructuredGeneration:
    return StructuredGeneration(schema_version=1, claims=claims)


def test_valid_claims_become_answered_with_sentence_level_citations() -> None:
    draft = generation(
        GeneratedClaim(
            text="위험 한도는 순자산의 7%입니다.",
            evidence_ids=(EVIDENCE_ID,),
        ),
        GeneratedClaim(
            text="적용일은 2026-09-01입니다.",
            evidence_ids=(EVIDENCE_ID,),
        ),
    )

    outcome = CitationValidator().validate(draft, allowed_evidence=(evidence(),))

    assert outcome.status is GenerationStatus.ANSWERED
    assert outcome.text == "위험 한도는 순자산의 7%입니다. 적용일은 2026-09-01입니다."
    assert [item.claim_index for item in outcome.citations] == [0, 1]
    assert outcome.citations[0].evidence_ids == (EVIDENCE_ID,)


def test_claim_without_citation_is_rejected_without_exposing_draft() -> None:
    outcome = CitationValidator().validate(
        generation(GeneratedClaim(text="근거 없는 생성 초안", evidence_ids=())),
        allowed_evidence=(evidence(),),
    )

    assert outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
    assert outcome.text is None
    assert outcome.citations == ()
    assert outcome.reason_codes == ("claim_citation_missing",)
    assert "근거 없는 생성 초안" not in repr(outcome)


def test_evidence_outside_current_authorized_search_result_is_rejected() -> None:
    unknown_id = UUID("10000000-0000-0000-0000-000000000099")

    outcome = CitationValidator().validate(
        generation(GeneratedClaim(text="위험 한도입니다.", evidence_ids=(unknown_id,))),
        allowed_evidence=(evidence(),),
    )

    assert outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
    assert outcome.reason_codes == ("evidence_not_allowed",)


def test_numeric_or_date_claim_must_match_at_least_one_cited_evidence() -> None:
    outcome = CitationValidator().validate(
        generation(
            GeneratedClaim(
                text="위험 한도는 9%이며 적용일은 2026-10-01입니다.",
                evidence_ids=(EVIDENCE_ID,),
            )
        ),
        allowed_evidence=(evidence(),),
    )

    assert outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
    assert outcome.reason_codes == ("exact_value_not_supported",)


@pytest.mark.parametrize(
    ("evidence_text", "claim_text"),
    [
        ("투자 기간은 3년입니다.", "투자 기간은 9년입니다."),
        (
            "적용일은 2026년 9월 1일입니다.",
            "적용일은 2026년 10월 1일입니다.",
        ),
    ],
    ids=("korean-year-duration", "korean-calendar-date"),
)
def test_korean_numeric_or_date_claim_must_match_cited_evidence(
    evidence_text: str,
    claim_text: str,
) -> None:
    outcome = CitationValidator().validate(
        generation(
            GeneratedClaim(
                text=claim_text,
                evidence_ids=(EVIDENCE_ID,),
            )
        ),
        allowed_evidence=(evidence(text=evidence_text),),
    )

    assert outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
    assert outcome.reason_codes == ("exact_value_not_supported",)


def test_incomplete_projection_provenance_is_rejected() -> None:
    outcome = CitationValidator().validate(
        generation(GeneratedClaim(text="위험 한도입니다.", evidence_ids=(EVIDENCE_ID,))),
        allowed_evidence=(evidence(projection_id=None),),
    )

    assert outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
    assert outcome.reason_codes == ("evidence_provenance_incomplete",)


@pytest.mark.parametrize(
    ("evidence_text", "claim_text"),
    [
        ("2026-09-01", "2026년 9월 1일"),
        ("2026년 09월 01일", "2026-9-1"),
        ("7%", "7.0 %"),
        ("7퍼센트", "7%"),
        ("1,000원", "1000원"),
        ("1000원", "1,000.00 원"),
        ("-7%", "−7.00%"),
        ("0.15%p", "0.150 퍼센트포인트"),
        ("0.15%p", "0.15 % p"),
        ("0.15%p", "0.15 퍼센트 포인트"),
        ("0.15%p", "0.15％p"),
        ("3년", "3.0 년"),
    ],
)
def test_equivalent_numeric_spellings_keep_exact_claim_text(
    evidence_text: str,
    claim_text: str,
) -> None:
    outcome = CitationValidator().validate(
        generation(GeneratedClaim(text=claim_text, evidence_ids=(EVIDENCE_ID,))),
        allowed_evidence=(evidence(text=evidence_text),),
    )

    assert outcome.status is GenerationStatus.ANSWERED
    assert outcome.text == claim_text
    assert outcome.citations[0].claim_text == claim_text


@pytest.mark.parametrize(
    ("evidence_text", "claim_text"),
    [
        ("-7%", "7%"),
        ("7%", "-7%"),
        ("0.15%p", "0.15%"),
        ("0.15%", "0.15%p"),
        ("0.15%", "0.15% p"),
        ("0.15%", "0.15퍼센트 포인트"),
        ("0.15%", "0.15％p"),
        ("1000원", "2000원"),
        ("1000원", "1,00원"),
        ("1억원", "10000만원"),
        ("7.01%", "7.0%"),
        ("2026-09-01", "2026년 9월 2일"),
        ("2026-09-01", "2026년"),
        ("0.15%", "15%"),
        ("2026-02-28", "2026년 2월 30일"),
    ],
)
def test_numeric_sign_unit_or_value_changes_remain_rejected(
    evidence_text: str,
    claim_text: str,
) -> None:
    outcome = CitationValidator().validate(
        generation(GeneratedClaim(text=claim_text, evidence_ids=(EVIDENCE_ID,))),
        allowed_evidence=(evidence(text=evidence_text),),
    )

    assert outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
    assert outcome.reason_codes == ("exact_value_not_supported",)
    assert outcome.text is None
    assert outcome.citations == ()


def test_numeric_equivalence_uses_only_cited_evidence() -> None:
    other_id = UUID("10000000-0000-0000-0000-000000000002")
    outcome = CitationValidator().validate(
        generation(GeneratedClaim(text="7.0 %", evidence_ids=(EVIDENCE_ID,))),
        allowed_evidence=(evidence(text="8%"), evidence(evidence_id=other_id, text="7%")),
    )

    assert outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
    assert outcome.reason_codes == ("exact_value_not_supported",)
    assert outcome.text is None


def test_calendar_date_is_not_reinterpreted_as_year_duration_in_prose() -> None:
    outcome = CitationValidator().validate(
        generation(GeneratedClaim(text="적용일은 2026-09-01입니다.", evidence_ids=(EVIDENCE_ID,))),
        allowed_evidence=(evidence(text="적용일은 2026년 9월 1일입니다."),),
    )

    assert outcome.status is GenerationStatus.ANSWERED
