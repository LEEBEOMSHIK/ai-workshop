from dataclasses import dataclass
from uuid import UUID

import pytest

from ai_workshop.labs.rag.chunking.contracts import ChunkingConfig
from ai_workshop.labs.rag.chunking.service import ChunkOverflowError, StructuralChunker
from ai_workshop.labs.rag.documents.domain import ParsedDocument, SourceLocation, StructuralElement


@dataclass(frozen=True)
class MarkerTokenCounter:
    """Counts whitespace-delimited test markers, not characters."""

    def count(self, text: str) -> int:
        return len(text.split())


def _element(
    ordinal: int,
    text: str,
    *,
    kind: str = "paragraph",
    section_path: tuple[str, ...] = ("투자 정책", "위험 한도"),
) -> StructuralElement:
    element_id = UUID(f"00000000-0000-0000-0000-{ordinal + 1:012d}")
    return StructuralElement(
        id=element_id,
        ordinal=ordinal,
        kind=kind,
        text=text,
        section_path=section_path,
        location=SourceLocation(
            element_id=element_id,
            page=ordinal + 1,
            char_start=100 + ordinal,
            char_end=200 + ordinal,
            bbox=(1.0, 2.0, 3.0, 4.0),
        ),
        parser_name="test",
        parser_version="1",
        confidence=1.0,
    )


def _document(*elements: StructuralElement) -> ParsedDocument:
    return ParsedDocument(
        asset_version_id=UUID("00000000-0000-0000-0000-000000000099"),
        parser_name="test",
        parser_version="1",
        elements=elements,
    )


def _tokens(prefix: str, count: int) -> str:
    return " ".join(f"{prefix}{ordinal}" for ordinal in range(count)) + "."


def test_chunker_preserves_indivisible_evidence_and_applies_context_ceiling_and_overlap() -> None:
    first = _element(0, _tokens("first", 160))
    second = _element(1, _tokens("second", 60))
    third = _element(2, _tokens("third", 160))
    fourth = _element(3, _tokens("fourth", 160))
    document = _document(first, second, third, fourth)
    counter = MarkerTokenCounter()
    config = ChunkingConfig(target_tokens=380, overlap_tokens=60, hard_ceiling_tokens=440)

    result = StructuralChunker(counter).chunk(
        document,
        projection_id=UUID("00000000-0000-0000-0000-000000000123"),
        config=config,
    )

    assert len(result.chunks) == 3
    assert all(chunk.text.startswith("투자 정책 > 위험 한도\n\n") for chunk in result.chunks)
    assert all(counter.count(chunk.text) <= 440 for chunk in result.chunks)
    assert [unit.text for unit in result.chunks[0].evidence_units] == [first.text, second.text]
    assert [unit.text for unit in result.chunks[1].evidence_units] == [second.text, third.text]
    assert [unit.text for unit in result.chunks[2].evidence_units] == [fourth.text]
    assert counter.count(result.chunks[0].text) == 5 + 160 + 60
    assert counter.count(result.chunks[1].text) == 5 + 60 + 160
    assert counter.count(result.chunks[2].text) == 5 + 160
    assert sum(counter.count(unit.text) for unit in result.chunks[1].evidence_units[:-1]) == 60
    assert sum(counter.count(unit.text) for unit in result.chunks[2].evidence_units[:-1]) == 0
    assert result.chunks[0].evidence_units[0].location is first.location
    assert result.chunks[0].evidence_units[1].location is second.location
    assert result.chunks[1].evidence_units[0].location is second.location
    assert result.chunks[1].evidence_units[1].location is third.location
    assert result.chunks[2].evidence_units[0].location is fourth.location
    assert all(
        unit.projection_id == result.chunks[0].projection_id for unit in result.evidence_units
    )
    assert all(
        unit.chunk_id in {chunk.id for chunk in result.chunks} for unit in result.evidence_units
    )


def test_chunker_keeps_list_items_and_table_cells_as_indivisible_evidence() -> None:
    list_item = _element(0, "- 손실 한도: 5%", kind="list_item")
    table_cell = _element(1, "자산군 | 한도 | 10%", kind="table_cell")

    result = StructuralChunker(MarkerTokenCounter()).chunk(
        _document(list_item, table_cell),
        projection_id=UUID("00000000-0000-0000-0000-000000000124"),
        config=ChunkingConfig(target_tokens=20, overlap_tokens=0, hard_ceiling_tokens=24),
    )

    assert [unit.text for unit in result.evidence_units] == [list_item.text, table_cell.text]
    assert [unit.location for unit in result.evidence_units] == [
        list_item.location,
        table_cell.location,
    ]


def test_chunker_preserves_exact_offsets_for_repeated_unicode_sentences() -> None:
    element = _element(
        0,
        "반복 문장입니다.  \n반복 문장입니다. 마지막 📈 문장입니다.",
    )
    element = StructuralElement(
        id=element.id,
        ordinal=element.ordinal,
        kind=element.kind,
        text=element.text,
        section_path=element.section_path,
        location=SourceLocation(
            element_id=element.id,
            page=None,
            char_start=100,
            char_end=134,
            bbox=None,
        ),
        parser_name=element.parser_name,
        parser_version=element.parser_version,
        confidence=element.confidence,
    )

    result = StructuralChunker(MarkerTokenCounter()).chunk(
        _document(element),
        projection_id=UUID("00000000-0000-0000-0000-000000000126"),
        config=ChunkingConfig(target_tokens=40, overlap_tokens=0, hard_ceiling_tokens=50),
    )

    assert [unit.text for unit in result.evidence_units] == [
        "반복 문장입니다.",
        "반복 문장입니다.",
        "마지막 📈 문장입니다.",
    ]
    assert [
        (unit.location.char_start, unit.location.char_end)
        for unit in result.evidence_units
    ] == [(100, 109), (112, 121), (122, 134)]


def test_chunker_keeps_pdf_bbox_element_indivisible_without_sentence_geometry() -> None:
    element = _element(0, "첫 문장입니다. 두 번째 문장입니다.")

    result = StructuralChunker(MarkerTokenCounter()).chunk(
        _document(element),
        projection_id=UUID("00000000-0000-0000-0000-000000000127"),
        config=ChunkingConfig(target_tokens=40, overlap_tokens=0, hard_ceiling_tokens=50),
    )

    assert len(result.evidence_units) == 1
    assert result.evidence_units[0].text == element.text
    assert result.evidence_units[0].location == element.location


def test_chunker_rejects_an_indivisible_unit_that_exceeds_the_hard_ceiling() -> None:
    element = _element(0, "one two three four five")

    with pytest.raises(ChunkOverflowError, match=str(element.id)):
        StructuralChunker(MarkerTokenCounter()).chunk(
            _document(element),
            projection_id=UUID("00000000-0000-0000-0000-000000000125"),
            config=ChunkingConfig(target_tokens=3, overlap_tokens=1, hard_ceiling_tokens=4),
        )
