from pathlib import Path
from uuid import UUID

import pytest

from ai_workshop.labs.rag.parsing.contracts import (
    ParseRequest,
    ParsingError,
    UnsupportedParserError,
)
from ai_workshop.labs.rag.parsing.markdown import MarkdownParser
from ai_workshop.labs.rag.parsing.pdf import PdfParser
from ai_workshop.labs.rag.parsing.plain_text import PlainTextParser
from ai_workshop.labs.rag.parsing.registry import ParserRegistry


def test_registry_resolves_format_adapters_from_media_type_and_filename() -> None:
    registry = ParserRegistry((PlainTextParser(), MarkdownParser(), PdfParser()))

    parser = registry.resolve("text/plain", "investment-notes.txt")

    assert isinstance(parser, PlainTextParser)
    assert isinstance(
        registry.resolve("application/octet-stream", "risk-register.md"), MarkdownParser
    )
    assert isinstance(registry.resolve("application/pdf", "report.pdf"), PdfParser)


def test_registry_rejects_an_unsupported_format_with_a_typed_error() -> None:
    registry = ParserRegistry((PlainTextParser(), MarkdownParser(), PdfParser()))

    with pytest.raises(UnsupportedParserError) as error:
        registry.resolve(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "x.docx"
        )

    assert error.value.code == "unsupported_format"


@pytest.mark.parametrize(
    ("media_type", "filename"),
    [
        ("application/pdf", "note.txt"),
        ("text/markdown; charset=utf-8", "report.pdf"),
    ],
)
def test_registry_rejects_conflicting_supported_media_type_and_filename(
    media_type: str,
    filename: str,
) -> None:
    registry = ParserRegistry((PlainTextParser(), MarkdownParser(), PdfParser()))

    with pytest.raises(ParsingError) as error:
        registry.resolve(media_type, filename)

    assert error.value.code == "conflicting_format"


@pytest.mark.parametrize(
    ("media_type", "filename", "expected_type"),
    [
        ("application/octet-stream", "risk-register.md", MarkdownParser),
        ("", "report.pdf", PdfParser),
    ],
)
def test_registry_uses_filename_fallback_only_for_generic_or_absent_media_type(
    media_type: str,
    filename: str,
    expected_type: type[object],
) -> None:
    registry = ParserRegistry((PlainTextParser(), MarkdownParser(), PdfParser()))

    assert isinstance(registry.resolve(media_type, filename), expected_type)


def test_parse_request_retains_the_immutable_asset_version_identity(tmp_path: Path) -> None:
    asset_version_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    request = ParseRequest(
        path=tmp_path / "risk.txt",
        media_type="text/plain",
        filename="risk.txt",
        asset_version_id=asset_version_id,
    )

    assert request.asset_version_id == asset_version_id
