from uuid import UUID

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


def test_incomplete_projection_provenance_is_rejected() -> None:
    outcome = CitationValidator().validate(
        generation(
            GeneratedClaim(text="위험 한도입니다.", evidence_ids=(EVIDENCE_ID,))
        ),
        allowed_evidence=(evidence(projection_id=None),),
    )

    assert outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
    assert outcome.reason_codes == ("evidence_provenance_incomplete",)
