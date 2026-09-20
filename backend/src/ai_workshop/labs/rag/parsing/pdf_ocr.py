from hashlib import sha256
from math import ceil, floor, isfinite
from typing import Any
from unicodedata import normalize
from uuid import uuid4

import pymupdf

from ai_workshop.labs.rag.documents.domain import (
    ParsedDocument,
    SourceKind,
    SourceLocation,
    StructuralElement,
    TableCellLocation,
)
from ai_workshop.labs.rag.ocr.contracts import (
    OcrConfigurationError,
    OcrProfileSpec,
    OcrRequest,
    OcrRuntimeError,
    OcrRuntimePort,
    OcrTableCell,
    OcrTextUnit,
)
from ai_workshop.labs.rag.parsing.contracts import (
    EmptyPdfOcrError,
    InvalidPdfError,
    ParseRequest,
    PdfProcessingLimitError,
)
from ai_workshop.labs.rag.parsing.pdf import _validated_bbox


class PdfOcrParser:
    media_types = frozenset({"application/pdf"})
    suffixes = frozenset({".pdf"})
    parser_name = "pymupdf-ocr"
    parser_version = "1"

    def __init__(
        self,
        *,
        ocr_runtime: OcrRuntimePort,
        ocr_profile: OcrProfileSpec,
        raster_dpi: int,
        max_page_pixels: int,
        max_pages: int,
        parser_version: str = "1",
    ) -> None:
        if parser_version not in ("1", "2"):
            raise OcrConfigurationError("Unsupported PDF OCR parser version.")
        if any(
            type(value) is not int or value < 1
            for value in (raster_dpi, max_page_pixels, max_pages)
        ):
            raise OcrConfigurationError("PDF raster and page limits must be positive integers.")
        self.ocr_runtime = ocr_runtime
        self.ocr_profile = ocr_profile
        self.raster_dpi = raster_dpi
        self.max_page_pixels = max_page_pixels
        self.max_pages = max_pages
        self.parser_version = parser_version

    def parse(self, request: ParseRequest) -> ParsedDocument:
        try:
            document: Any = pymupdf.open(request.path)  # type: ignore[no-untyped-call]
        except (RuntimeError, ValueError, OSError):
            raise InvalidPdfError() from None
        try:
            if document.needs_pass or not document.is_pdf or document.page_count == 0:
                raise InvalidPdfError()
            if document.page_count > self.max_pages:
                raise PdfProcessingLimitError()
            elements: list[StructuralElement] = []
            for page_number, page in enumerate(document, start=1):
                try:
                    spans = [
                        span
                        for block in page.get_text(
                            "dict",
                            sort=False,
                            flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES,
                        )["blocks"]
                        if block["type"] == 0
                        for line in block["lines"]
                        for span in line["spans"]
                        if span["text"].rstrip("\r\n")
                    ]
                except (RuntimeError, ValueError):
                    raise InvalidPdfError() from None
                if any(span["text"].strip() for span in spans):
                    for span in spans:
                        # Text extraction returns unrotated crop-local coordinates.
                        bbox = pymupdf.Rect(span["bbox"]) * page.rotation_matrix  # type: ignore[no-untyped-call]
                        self._append(
                            elements,
                            text=span["text"].rstrip("\r\n"),
                            kind="paragraph",
                            page_number=page_number,
                            bbox=_validated_bbox(bbox, page.rect, page_number),
                            confidence=1.0,
                        )
                    if self.parser_version == "2":
                        self._ocr_image_regions(page, page_number, elements, request)
                else:
                    self._ocr_page(page, page_number, elements, request)
        finally:
            document.close()
        return ParsedDocument(
            request.asset_version_id, self.parser_name, self.parser_version, tuple(elements)
        )

    def _ocr_image_regions(
        self, page: Any, page_number: int, elements: list[StructuralElement], request: ParseRequest
    ) -> None:
        regions: list[Any] = []
        try:
            # Metadata only: do not decode embedded source images into Python bytes.
            for info in page.get_image_info():
                if not all(isfinite(float(value)) for value in info["bbox"]):
                    raise InvalidPdfError()
                region = (pymupdf.Rect(info["bbox"]) * page.rotation_matrix) & page.rect  # type: ignore[no-untyped-call]
                if region.is_empty:
                    continue
                # Recheck after each union: the union may intersect an earlier region.
                index = 0
                while index < len(regions):
                    if region.intersects(regions[index]):
                        region |= regions.pop(index)
                        index = 0
                    else:
                        index += 1
                regions.append(region)
        except (RuntimeError, ValueError, TypeError, OverflowError):
            raise InvalidPdfError() from None
        scale = self.raster_dpi / 72
        pixels = sum(
            (ceil(rect.x1 * scale) - floor(rect.x0 * scale))
            * (ceil(rect.y1 * scale) - floor(rect.y0 * scale))
            for rect in regions
        )
        if pixels > self.max_page_pixels:
            raise PdfProcessingLimitError()
        native = tuple(e for e in elements if e.location.page == page_number)
        for region in sorted(regions, key=lambda rect: (rect.y0, rect.x0, rect.y1, rect.x1)):
            self._ocr_page(page, page_number, elements, request, region=region, native=native)

    def _ocr_page(
        self,
        page: Any,
        page_number: int,
        elements: list[StructuralElement],
        request: ParseRequest,
        *,
        region: Any = None,
        native: tuple[StructuralElement, ...] = (),
    ) -> None:
        width, height = float(page.rect.width), float(page.rect.height)
        if region is not None:
            width, height = float(region.width), float(region.height)
        scale = self.raster_dpi / 72
        if (
            not all(isfinite(value) and value > 0 for value in (width, height, scale))
            or ceil(width * scale) * ceil(height * scale) > self.max_page_pixels
        ):
            raise PdfProcessingLimitError()
        image_path = request.create_temporary_file(f"{uuid4()}.png")
        try:
            pixmap = page.get_pixmap(
                dpi=self.raster_dpi, colorspace=pymupdf.csRGB, alpha=False, clip=region
            )
            blob = pixmap.tobytes("png")
            image_path.write_bytes(blob)
        except (RuntimeError, ValueError, OSError):
            raise InvalidPdfError() from None
        request.mark_opaque_runtime_started()
        try:
            result = self.ocr_runtime.recognize(
                OcrRequest(
                    image_path=image_path,
                    media_type="image/png",
                    source_part=f"pdf/pages/{page_number}",
                    image_sha256=sha256(blob).hexdigest(),
                    pixel_width=pixmap.width,
                    pixel_height=pixmap.height,
                ),
                self.ocr_profile,
            )
        except OcrRuntimeError as error:
            raise OcrRuntimeError(error.code, "Configured PDF OCR processing failed.") from None
        count_before = len(elements)
        units: tuple[OcrTextUnit | OcrTableCell, ...] = (*result.text_units, *result.table_cells)
        for unit in units:
            if not unit.text.strip():
                continue
            low_confidence = not (self.ocr_profile.confidence_threshold <= unit.confidence <= 1)
            warnings = result.warnings
            if low_confidence:
                warnings += ("ocr_confidence_below_threshold",)
            elif not unit.evidence_eligible:
                warnings += ("ocr_evidence_ineligible",)
            left, top, right, bottom = unit.bbox
            if region is None:
                mapped_bbox = (left * width, top * height, right * width, bottom * height)
            else:
                # Pixmap origins are rounded outward to integer device coordinates.
                # Map through those actual pixels, then trim raster padding to the clip.
                mapped_bbox = (
                    max(region.x0, (pixmap.x + left * pixmap.width) / scale),
                    max(region.y0, (pixmap.y + top * pixmap.height) / scale),
                    min(region.x1, (pixmap.x + right * pixmap.width) / scale),
                    min(region.y1, (pixmap.y + bottom * pixmap.height) / scale),
                )
            bbox = _validated_bbox(mapped_bbox, page.rect, page_number)
            overlapping_text = [
                element.text
                for element in native
                if element.location.bbox is not None
                and _same_text_location(bbox, element.location.bbox)
            ]
            # Native extraction can split a single line at a font/style change.
            candidates = [*overlapping_text, "".join(overlapping_text), " ".join(overlapping_text)]
            duplicate = _normalized_text(unit.text) in {
                _normalized_text(candidate) for candidate in candidates
            }
            if duplicate:
                warnings += ("pdf_ocr_native_duplicate",)
            table_cell = None
            if isinstance(unit, OcrTableCell):
                if unit.row_index is not None and unit.column_index is not None:
                    table_cell = TableCellLocation(unit.row_index, unit.column_index)
                kind = "ocr_table_cell"
            else:
                kind = "ocr_text"
            self._append(
                elements,
                text=unit.text,
                kind=kind,
                page_number=page_number,
                bbox=bbox,
                confidence=unit.confidence,
                evidence_eligible=unit.evidence_eligible and not low_confidence and not duplicate,
                warnings=warnings,
                table_cell=table_cell,
            )
        if len(elements) == count_before and region is None:
            raise EmptyPdfOcrError(page_number)

    def _append(
        self,
        elements: list[StructuralElement],
        *,
        text: str,
        kind: str,
        page_number: int,
        bbox: tuple[float, float, float, float],
        confidence: float,
        evidence_eligible: bool = True,
        warnings: tuple[str, ...] = (),
        table_cell: TableCellLocation | None = None,
    ) -> None:
        element_id = uuid4()
        offset = elements[-1].location.char_end if elements else 0
        elements.append(
            StructuralElement(
                id=element_id,
                ordinal=len(elements),
                kind=kind,
                text=text,
                section_path=(),
                location=SourceLocation(
                    element_id=element_id,
                    page=page_number,
                    char_start=offset,
                    char_end=offset + len(text),
                    bbox=bbox,
                    source_kind=SourceKind.PDF_PAGE,
                    table_cell=table_cell,
                ),
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                confidence=confidence,
                evidence_eligible=evidence_eligible,
                warnings=warnings,
            )
        )


def _normalized_text(value: str) -> str:
    return " ".join(normalize("NFC", value).split())


def _same_text_location(
    first: tuple[float, float, float, float], second: tuple[float, float, float, float]
) -> bool:
    """V2 invariant: intersection covers strictly over half the smaller text box."""
    intersection_width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    intersection_height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    smaller_area = min(
        (first[2] - first[0]) * (first[3] - first[1]),
        (second[2] - second[0]) * (second[3] - second[1]),
    )
    return smaller_area > 0 and intersection_width * intersection_height > smaller_area / 2
