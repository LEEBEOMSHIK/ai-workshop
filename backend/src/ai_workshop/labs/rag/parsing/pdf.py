from typing import Any
from uuid import uuid4

import pymupdf

from ai_workshop.labs.rag.documents.domain import ParsedDocument, SourceLocation, StructuralElement
from ai_workshop.labs.rag.parsing.contracts import OcrRequiredError, ParseRequest


class PdfParser:
    media_types = frozenset({"application/pdf"})
    suffixes = frozenset({".pdf"})
    parser_name = "pymupdf"
    parser_version = pymupdf.VersionBind

    def parse(self, request: ParseRequest) -> ParsedDocument:
        document: Any = pymupdf.open(request.path)  # type: ignore[no-untyped-call]
        try:
            elements: list[StructuralElement] = []
            char_offset = 0
            for page_number, page in enumerate(document, start=1):
                page_has_text = False
                for block in page.get_text("dict", sort=False)["blocks"]:
                    if block["type"] != 0:
                        continue
                    for line in block["lines"]:
                        for span in line["spans"]:
                            value = span["text"].rstrip("\r\n")
                            if not value:
                                continue
                            page_has_text = True
                            element_id = uuid4()
                            elements.append(
                                StructuralElement(
                                    id=element_id,
                                    ordinal=len(elements),
                                    kind="paragraph",
                                    text=value,
                                    section_path=(),
                                    location=SourceLocation(
                                        element_id=element_id,
                                        page=page_number,
                                        char_start=char_offset,
                                        char_end=char_offset + len(value),
                                        bbox=tuple(span["bbox"]),
                                    ),
                                    parser_name=self.parser_name,
                                    parser_version=self.parser_version,
                                    confidence=1.0,
                                )
                            )
                            char_offset += len(value)
                if not page_has_text:
                    raise OcrRequiredError(page_number)
        finally:
            document.close()
        return ParsedDocument(
            asset_version_id=request.asset_version_id,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            elements=tuple(elements),
        )
