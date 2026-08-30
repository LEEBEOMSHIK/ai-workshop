from uuid import UUID

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.highlighting.domain import HighlightKind
from ai_workshop.labs.rag.highlighting.service import (
    find_keyword_highlights,
    semantic_highlight,
)

EVIDENCE_ID = UUID("10000000-0000-0000-0000-000000000001")
ELEMENT_ID = UUID("10000000-0000-0000-0000-000000000002")
CHUNK_ID = UUID("10000000-0000-0000-0000-000000000003")
PROJECTION_ID = UUID("10000000-0000-0000-0000-000000000004")


def test_keyword_normalization_maps_casefolded_and_nfkc_matches_to_original_offsets() -> None:
    text = "Straße　수수료"
    location = SourceLocation(
        element_id=ELEMENT_ID,
        page=None,
        char_start=50,
        char_end=60,
        bbox=None,
    )

    result = find_keyword_highlights(
        query="STRASSE 수수료",
        text=text,
        location=location,
        evidence_unit_id=EVIDENCE_ID,
    )

    assert result.coverage == 1.0
    assert [item.kind for item in result.highlights] == [
        HighlightKind.KEYWORD,
        HighlightKind.KEYWORD,
    ]
    assert [(item.char_start, item.char_end, item.text) for item in result.highlights] == [
        (50, 56, "Straße"),
        (57, 60, "수수료"),
    ]


def test_keyword_normalization_maps_combining_sequence_to_complete_original_span() -> None:
    text = "Cafe\u0301 수수료"
    location = SourceLocation(
        element_id=ELEMENT_ID,
        page=None,
        char_start=10,
        char_end=20,
        bbox=None,
    )

    result = find_keyword_highlights(
        query="CAFÉ",
        text=text,
        location=location,
        evidence_unit_id=EVIDENCE_ID,
    )

    assert result.coverage == 1.0
    assert [(item.char_start, item.char_end, item.text) for item in result.highlights] == [
        (10, 15, "Cafe\u0301"),
    ]


def test_keyword_normalization_maps_decomposed_hangul_to_complete_original_span() -> None:
    text = "\u1100\u1161 환매"
    location = SourceLocation(
        element_id=ELEMENT_ID,
        page=None,
        char_start=30,
        char_end=35,
        bbox=None,
    )

    result = find_keyword_highlights(
        query="가",
        text=text,
        location=location,
        evidence_unit_id=EVIDENCE_ID,
    )

    assert result.coverage == 1.0
    assert [(item.char_start, item.char_end, item.text) for item in result.highlights] == [
        (30, 32, "\u1100\u1161"),
    ]


def test_partial_pdf_keyword_match_does_not_fabricate_a_precise_bbox() -> None:
    location = SourceLocation(
        element_id=ELEMENT_ID,
        page=2,
        char_start=20,
        char_end=30,
        bbox=(10.0, 20.0, 200.0, 40.0),
    )

    result = find_keyword_highlights(
        query="수수료",
        text="환매 수수료는 1%",
        location=location,
        evidence_unit_id=EVIDENCE_ID,
    )

    assert result.highlights[0].bbox is None
    assert result.highlights[0].warnings == ("pdf_keyword_bbox_unavailable",)


def test_semantic_highlight_covers_the_complete_evidence_unit() -> None:
    location = SourceLocation(
        element_id=ELEMENT_ID,
        page=3,
        char_start=120,
        char_end=135,
        bbox=(12.0, 18.0, 180.0, 34.0),
    )
    evidence = EvidenceUnit(
        id=EVIDENCE_ID,
        chunk_id=CHUNK_ID,
        projection_id=PROJECTION_ID,
        ordinal=0,
        text="가입 후 해지 조건입니다.",
        location=location,
    )

    result = semantic_highlight(evidence, score=0.91)

    assert result.kind is HighlightKind.SEMANTIC
    assert result.text == evidence.text
    assert (result.char_start, result.char_end) == (120, 135)
    assert result.bbox == location.bbox
    assert result.score == 0.91
