"""Synthetic lexical support cases; no source-specific answer rules."""

from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.citation_validation import CitationValidator
from ai_workshop.labs.rag.generation.domain import (
    GeneratedClaim,
    GenerationStatus,
    GroundingEvidence,
    StructuredGeneration,
)
from ai_workshop.labs.rag.generation.exact_values import exact_values

FIRST = UUID("10000000-0000-0000-0000-000000000011")
SECOND = UUID("10000000-0000-0000-0000-000000000012")


def _evidence(identity: UUID, text: str) -> GroundingEvidence:
    return GroundingEvidence(
        evidence_id=identity,
        text=text,
        document_id=UUID("20000000-0000-0000-0000-000000000011"),
        asset_version_id=UUID("30000000-0000-0000-0000-000000000011"),
        projection_id=UUID("40000000-0000-0000-0000-000000000011"),
        chunk_id=identity,
        element_id=UUID("50000000-0000-0000-0000-000000000011"),
        page=None,
        char_start=0,
        char_end=len(text),
        bbox=None,
    )


@pytest.mark.parametrize("schema", [1, 2])
@pytest.mark.parametrize("cite_second", [False, True])
def test_short_values_must_come_from_cited_fragments(schema: int, cite_second: bool) -> None:
    text = "검수는 2031-04-02에 접수되며 확인은 04-04, 발송은 04-08이다."
    citations = (FIRST, SECOND) if cite_second else (FIRST,)
    outcome = CitationValidator().validate(
        StructuredGeneration(schema, (GeneratedClaim(text, citations),)),
        allowed_evidence=(
            _evidence(FIRST, "검수는 2031-04-02에 접수된다."),
            _evidence(SECOND, "확인은 04-04, 발송은 04-08이다."),
        ),
    )

    if cite_second:
        assert outcome.status is GenerationStatus.ANSWERED
        assert outcome.text == text
        assert outcome.citations[0].evidence_ids == (FIRST, SECOND)
    else:
        assert outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
        assert outcome.reason_codes == ("exact_value_not_supported",)
        assert outcome.text is None
        assert outcome.citations == ()
        assert text not in repr(outcome)


@pytest.mark.parametrize(
    ("source", "claim"),
    [
        ("04-08", "04-09"),
        ("04-08", "4-8"),
        ("2031-04-08", "04-08"),
        ("04/08", "04-08"),
        ("4월 8일", "04-08"),
        ("04 - 08", "04-08"),
        ("MODEL-04-08", "04-08"),
        ("수량 범위 8-12", "수량 범위 8-13"),
        ("99-99", "99-98"),
        ("100-200", "100-201"),
        ("T+5", "T+6"),
        ("T-5", "T+5"),
        ("S+5", "T+5"),
        ("t+5", "T+5"),
        ("T-0", "T+0"),
        ("T+5 영업일", "T+6 영업일"),
        ("T+5 영업일", "5 영업일 후 T+6"),
        ("5 영업일", "T+5 영업일"),
        ("5일", "5 영업일"),
        ("5개월", "5 영업일"),
        ("5 영업일", "6 영업일"),
        ("-5 영업일", "5 영업일"),
        ("0 영업일", "1 영업일"),
        ("1.5 영업일", "5 영업일"),
        ("1,005 영업일", "5 영업일"),
    ],
)
def test_changed_lexical_values_are_rejected_without_inference(source: str, claim: str) -> None:
    outcome = CitationValidator().validate(
        StructuredGeneration(2, (GeneratedClaim(claim, (FIRST,)),)),
        allowed_evidence=(_evidence(FIRST, source),),
    )

    assert outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
    assert outcome.reason_codes == ("exact_value_not_supported",)
    assert outcome.text is None
    assert outcome.citations == ()


@pytest.mark.parametrize(
    ("source", "claim"),
    [
        ("검수일 04-08", "검수일은 04-08이다."),
        ("검수일 04-08", "검수일: (04-08)."),
        ("수량은 8-12", "수량 범위는 8-12."),
        ("99-99", "99-99"),
        ("T+5", "T + 5"),
        ("S-5", "S - 5"),
        ("T+0", "T + 0"),
        ("T+05", "T+5"),
        ("T+5 영업일", "5 영업일"),
        ("T-5영업일", "-5 영업일"),
        ("5영업일", "5 영업일"),
        ("-5 영업일", "−5영업일"),
        ("0 영업일", "+0 영업일"),
        ("2031-04-08", "2031년 4월 8일"),
        ("2031-02-30", "2031-02-30"),
    ],
)
def test_supported_values_keep_original_answer_text(source: str, claim: str) -> None:
    outcome = CitationValidator().validate(
        StructuredGeneration(2, (GeneratedClaim(claim, (FIRST,)),)),
        allowed_evidence=(_evidence(FIRST, source),),
    )

    assert outcome.status is GenerationStatus.ANSWERED
    assert outcome.text == claim


@pytest.mark.parametrize(
    "text",
    [
        "MODEL-04-08",
        "A04-08",
        "04-08B",
        "id_04-08",
        "04-08_suffix",
        "04-08-12",
        "1.04-08",
        "04-08.5",
        "1,004-008",
        "4-8,000",
        "2031/04-08",
        "+04-08",
        "-04-08",
        "04--08",
        "MODEL-T+5",
        "TT+5",
        "T+5B",
        "T+5-12",
        "T++5",
        "T+5.5",
        "T+5,000",
        "T+",
        "5.5 영업일",
        "1,005 영업일",
        "N5 영업일",
        "--5 영업일",
        "-- 5 영업일",
        "+ - 5 영업일",
        "S - -5 영업일",
    ],
)
def test_identifiers_decimals_and_malformed_tokens_are_not_partially_extracted(text: str) -> None:
    assert exact_values(text) == set()


def test_short_values_do_not_imply_an_uncited_relative_rule() -> None:
    outcome = CitationValidator().validate(
        StructuredGeneration(2, (GeneratedClaim("발송은 T+5 영업일이다.", (FIRST,)),)),
        allowed_evidence=(
            _evidence(FIRST, "발송 예시: 04-08"),
            _evidence(SECOND, "발송은 T+5 영업일"),
        ),
    )

    assert outcome.status is GenerationStatus.CITATION_VALIDATION_FAILED
    assert outcome.reason_codes == ("exact_value_not_supported",)
