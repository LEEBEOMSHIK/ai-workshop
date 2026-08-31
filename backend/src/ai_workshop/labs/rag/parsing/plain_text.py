import re
from collections.abc import Iterator
from uuid import uuid4

from ai_workshop.labs.rag.documents.domain import ParsedDocument, SourceLocation, StructuralElement
from ai_workshop.labs.rag.parsing.contracts import (
    ParseRequest,
    UnsupportedEncodingError,
)


class PlainTextParser:
    media_types = frozenset({"text/plain"})
    suffixes = frozenset({".txt"})
    parser_name = "plain_text"
    parser_version = "1"

    def parse(self, request: ParseRequest) -> ParsedDocument:
        try:
            text = request.path.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise UnsupportedEncodingError() from error
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        elements: list[StructuralElement] = []
        for start, end in _paragraph_spans(normalized):
            element_id = uuid4()
            elements.append(
                StructuralElement(
                    id=element_id,
                    ordinal=len(elements),
                    kind="paragraph",
                    text=normalized[start:end],
                    section_path=(),
                    location=SourceLocation(
                        element_id=element_id,
                        page=None,
                        char_start=start,
                        char_end=end,
                        bbox=None,
                    ),
                    parser_name=self.parser_name,
                    parser_version=self.parser_version,
                    confidence=1.0,
                )
            )
        return ParsedDocument(
            asset_version_id=request.asset_version_id,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            elements=tuple(elements),
        )


def _paragraph_spans(text: str) -> Iterator[tuple[int, int]]:
    cursor = 0
    separators = re.finditer(r"\n[^\S\n]*\n(?:[^\S\n]*\n)*", text)
    for separator in separators:
        span = _trimmed_nonempty_span(text, cursor, separator.start())
        if span is not None:
            yield span
        cursor = separator.end()
    span = _trimmed_nonempty_span(text, cursor, len(text))
    if span is not None:
        yield span


def _trimmed_nonempty_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        return start, end
    return None
