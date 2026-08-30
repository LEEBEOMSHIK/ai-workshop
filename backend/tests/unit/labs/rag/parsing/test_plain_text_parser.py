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
