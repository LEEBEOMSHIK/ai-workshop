from pathlib import Path
from uuid import UUID

import pytest

from ai_workshop.labs.rag.parsing.contracts import ParseRequest, UnsupportedEncodingError
from ai_workshop.labs.rag.parsing.plain_text import PlainTextParser


def test_plain_text_parser_normalizes_bom_crlf_and_paragraph_offsets(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_bytes("\ufeff첫 문단\r\n계속\r\n\r\n둘째 문단".encode("utf-8"))

    document = PlainTextParser().parse(
        ParseRequest(
            path=source,
            media_type="text/plain",
            filename=source.name,
            asset_version_id=UUID("11111111-1111-1111-1111-111111111111"),
        )
    )

    assert document.asset_version_id == UUID("11111111-1111-1111-1111-111111111111")
    assert [element.text for element in document.elements] == ["첫 문단\n계속", "둘째 문단"]
    assert [
        (element.location.char_start, element.location.char_end) for element in document.elements
    ] == [(0, 7), (9, 14)]
    assert all(element.location.page is None for element in document.elements)
    assert all(element.location.bbox is None for element in document.elements)


def test_plain_text_parser_excludes_one_terminal_lf_from_paragraph(tmp_path: Path) -> None:
    source = tmp_path / "terminal-lf.txt"
    source.write_bytes("종단 개행이 있는 문단\n".encode())

    document = PlainTextParser().parse(
        ParseRequest(
            path=source,
            media_type="text/plain",
            filename=source.name,
            asset_version_id=UUID("11111111-1111-1111-1111-111111111111"),
        )
    )

    assert [element.text for element in document.elements] == ["종단 개행이 있는 문단"]
    assert [
        (element.location.char_start, element.location.char_end) for element in document.elements
    ] == [(0, 12)]


def test_plain_text_parser_excludes_crlf_blank_lines_and_trailing_spaces(
    tmp_path: Path,
) -> None:
    source = tmp_path / "trailing-whitespace.txt"
    source.write_bytes("마지막 문단 \t\r\n \t\r\n\r\n".encode())

    document = PlainTextParser().parse(
        ParseRequest(
            path=source,
            media_type="text/plain",
            filename=source.name,
            asset_version_id=UUID("11111111-1111-1111-1111-111111111111"),
        )
    )

    assert [element.text for element in document.elements] == ["마지막 문단"]
    assert [
        (element.location.char_start, element.location.char_end) for element in document.elements
    ] == [(0, 6)]


def test_plain_text_parser_preserves_internal_newlines_and_exact_normalized_offsets(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paragraphs.txt"
    source.write_bytes(b"  Alpha\r\ncontinues  \r\n \t\r\n\r\nBeta line \t\r\n")

    document = PlainTextParser().parse(
        ParseRequest(
            path=source,
            media_type="text/plain",
            filename=source.name,
            asset_version_id=UUID("11111111-1111-1111-1111-111111111111"),
        )
    )

    assert [element.ordinal for element in document.elements] == [0, 1]
    assert [element.text for element in document.elements] == ["Alpha\ncontinues", "Beta line"]
    assert [
        (element.location.char_start, element.location.char_end) for element in document.elements
    ] == [(2, 17), (24, 33)]


def test_plain_text_parser_keeps_whitespace_only_source_empty(tmp_path: Path) -> None:
    source = tmp_path / "blank.txt"
    source.write_bytes(b" \t\r\n\r\n \t\r\n")

    document = PlainTextParser().parse(
        ParseRequest(
            path=source,
            media_type="text/plain",
            filename=source.name,
            asset_version_id=UUID("11111111-1111-1111-1111-111111111111"),
        )
    )

    assert document.elements == ()


def test_plain_text_parser_rejects_non_utf8_source_without_replacement(tmp_path: Path) -> None:
    source = tmp_path / "legacy.txt"
    source.write_bytes(b"\xff\xfelegacy")

    with pytest.raises(UnsupportedEncodingError) as error:
        PlainTextParser().parse(
            ParseRequest(
                path=source,
                media_type="text/plain",
                filename=source.name,
                asset_version_id=UUID("11111111-1111-1111-1111-111111111111"),
            )
        )

    assert error.value.code == "unsupported_encoding"
