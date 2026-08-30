import re
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
        for match in re.finditer(r"\S(?:.*?\S)?(?=\n{2,}|\Z)", normalized, re.DOTALL):
            element_id = uuid4()
            elements.append(
                StructuralElement(
                    id=element_id,
                    ordinal=len(elements),
                    kind="paragraph",
                    text=match.group(),
                    section_path=(),
                    location=SourceLocation(
                        element_id=element_id,
                        page=None,
                        char_start=match.start(),
                        char_end=match.end(),
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
