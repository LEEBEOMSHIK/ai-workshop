from math import isfinite
from typing import Any
from uuid import uuid4

import pymupdf

from ai_workshop.labs.rag.documents.domain import ParsedDocument, SourceLocation, StructuralElement
from ai_workshop.labs.rag.parsing.contracts import (
    InvalidPdfCoordinatesError,
    OcrRequiredError,
    ParseRequest,
)


def _validated_bbox(
    raw_bbox: Any,
    page_rect: Any,
    page_number: int,
) -> tuple[float, float, float, float]:
    try:
        left, top, right, bottom = (float(value) for value in raw_bbox)
        page_left = float(page_rect.x0)
        page_top = float(page_rect.y0)
        page_right = float(page_rect.x1)
        page_bottom = float(page_rect.y1)
    except (TypeError, ValueError) as error:
        raise InvalidPdfCoordinatesError(page_number) from error
    values = (left, top, right, bottom, page_left, page_top, page_right, page_bottom)
    if (
        not all(isfinite(value) for value in values)
        or left > right
        or top > bottom
        or left < page_left
        or top < page_top
        or right > page_right
        or bottom > page_bottom
    ):
        raise InvalidPdfCoordinatesError(page_number)
    return left, top, right, bottom


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
                                        bbox=_validated_bbox(span["bbox"], page.rect, page_number),
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
