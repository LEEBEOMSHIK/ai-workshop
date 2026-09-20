from __future__ import annotations

import hashlib
import posixpath
from collections.abc import Iterable
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.image.exceptions import UnrecognizedImageError
from docx.image.image import Image
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from ai_workshop.labs.rag.documents.domain import (
    ParsedDocument,
    SourceLocation,
    StructuralElement,
    TableCellLocation,
)
from ai_workshop.labs.rag.ocr.contracts import (
    OcrProfileSpec,
    OcrRequest,
    OcrResult,
    OcrRuntimePort,
)
from ai_workshop.labs.rag.parsing.contracts import (
    ExternalDocxRelationshipError,
    InvalidDocxError,
    ParseRequest,
    UnsafeDocxPackageError,
    UnsupportedEmbeddedImageError,
)

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_SUPPORTED_IMAGES = {"image/png": ".png", "image/jpeg": ".jpg"}


class DocxStructureParser:
    media_types = frozenset({DOCX_MEDIA_TYPE})
    suffixes = frozenset({".docx"})
    parser_name = "docx-structure"
    parser_version = "1"

    def __init__(
        self,
        *,
        ocr_runtime: OcrRuntimePort | None = None,
        ocr_profile: OcrProfileSpec | None = None,
        max_entries: int = 2_000,
        max_uncompressed_bytes: int = 100 * 1024 * 1024,
        max_compression_ratio: float = 200.0,
    ) -> None:
        if (ocr_runtime is None) != (ocr_profile is None):
            raise ValueError("DOCX OCR runtime and profile must be configured together.")
        self.ocr_runtime = ocr_runtime
        self.ocr_profile = ocr_profile
        self.max_entries = max_entries
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_compression_ratio = max_compression_ratio

    def parse(self, request: ParseRequest) -> ParsedDocument:
        self._validate_package(request.path)
        try:
            document = Document(str(request.path))
        except (BadZipFile, KeyError, PackageNotFoundError, ValueError) as exc:
            raise InvalidDocxError() from exc
        elements: list[StructuralElement] = []
        section_path: list[str] = []
        char_offset = 0
        ocr_cache: dict[tuple[str, str], OcrResult] = {}

        def append(
            kind: str,
            text: str,
            *,
            location: SourceLocation | None = None,
            confidence: float | None = 1.0,
            evidence_eligible: bool = True,
            warnings: tuple[str, ...] = (),
        ) -> None:
            nonlocal char_offset
            element_id = location.element_id if location is not None else uuid4()
            actual_location = location or SourceLocation(
                element_id=element_id,
                page=None,
                char_start=char_offset,
                char_end=char_offset + len(text),
                bbox=None,
            )
            elements.append(
                StructuralElement(
                    id=element_id,
                    ordinal=len(elements),
                    kind=kind,
                    text=text,
                    section_path=tuple(section_path),
                    location=actual_location,
                    parser_name=self.parser_name,
                    parser_version=self.parser_version,
                    confidence=confidence,
                    evidence_eligible=evidence_eligible,
                    warnings=warnings,
                )
            )
            char_offset = max(char_offset, actual_location.char_end) + 1

        for child in document.element.body.iterchildren():
            if child.tag == qn("w:p"):
                paragraph = Paragraph(child, document)
                text = paragraph.text.strip()
                if text:
                    kind = _paragraph_kind(paragraph)
                    if kind == "heading":
                        level = _heading_level(paragraph)
                        section_path[:] = section_path[: max(level - 1, 0)]
                        section_path.append(text)
                    append(kind, text)
                for relationship_id in _image_relationship_ids(paragraph):
                    relationship = document.part.rels[relationship_id]
                    if relationship.is_external:
                        raise ExternalDocxRelationshipError()
                    part = relationship.target_part
                    media_type = str(part.content_type).lower()
                    if media_type not in _SUPPORTED_IMAGES:
                        raise UnsupportedEmbeddedImageError()
                    source_part = _safe_source_part(str(relationship.target_ref))
                    blob = bytes(part.blob)
                    digest = hashlib.sha256(blob).hexdigest()
                    try:
                        image = Image.from_blob(blob)
                    except UnrecognizedImageError as exc:
                        raise UnsupportedEmbeddedImageError() from exc
                    if self.ocr_runtime is None or self.ocr_profile is None:
                        element_id = uuid4()
                        append(
                            "image",
                            "",
                            location=SourceLocation.docx_image(
                                element_id=element_id,
                                char_start=char_offset,
                                char_end=char_offset,
                                source_part=source_part,
                                image_sha256=digest,
                                bbox=(0.0, 0.0, 1.0, 1.0),
                            ),
                            confidence=None,
                            evidence_eligible=False,
                            warnings=("ocr_disabled",),
                        )
                        continue
                    suffix = _SUPPORTED_IMAGES[media_type]
                    cache_key = (digest, self.ocr_profile.pipeline_version)
                    result = ocr_cache.get(cache_key)
                    if result is None:
                        image_path = request.create_temporary_file(f"{uuid4()}{suffix}")
                        image_path.write_bytes(blob)
                        request.mark_opaque_runtime_started()
                        result = self.ocr_runtime.recognize(
                            OcrRequest(
                                image_path=image_path,
                                media_type=media_type,
                                source_part=source_part,
                                image_sha256=digest,
                                pixel_width=image.px_width,
                                pixel_height=image.px_height,
                            ),
                            self.ocr_profile,
                        )
                        ocr_cache[cache_key] = result
                    for unit in result.text_units:
                        element_id = uuid4()
                        append(
                            "ocr_text",
                            unit.text,
                            location=SourceLocation.docx_image(
                                element_id=element_id,
                                char_start=char_offset,
                                char_end=char_offset + len(unit.text),
                                source_part=source_part,
                                image_sha256=digest,
                                bbox=unit.bbox,
                            ),
                            confidence=unit.confidence,
                            evidence_eligible=unit.evidence_eligible,
                            warnings=(
                                ("ocr_confidence_below_threshold",)
                                if not unit.evidence_eligible
                                else ()
                            ),
                        )
                    for cell in result.table_cells:
                        element_id = uuid4()
                        table_cell = (
                            TableCellLocation(cell.row_index, cell.column_index)
                            if cell.row_index is not None and cell.column_index is not None
                            else None
                        )
                        append(
                            "ocr_table_cell",
                            cell.text,
                            location=SourceLocation.docx_image(
                                element_id=element_id,
                                char_start=char_offset,
                                char_end=char_offset + len(cell.text),
                                source_part=source_part,
                                image_sha256=digest,
                                bbox=cell.bbox,
                                table_cell=table_cell,
                            ),
                            confidence=cell.confidence,
                            evidence_eligible=cell.evidence_eligible,
                            warnings=(
                                ("ocr_confidence_below_threshold",)
                                if not cell.evidence_eligible
                                else ()
                            ),
                        )
            elif child.tag == qn("w:tbl"):
                table = Table(child, document)
                for row in table.rows:
                    for cell in row.cells:
                        text = cell.text.strip()
                        if text:
                            append("table_cell", text)

        return ParsedDocument(
            asset_version_id=request.asset_version_id,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            elements=tuple(elements),
        )

    def _validate_package(self, path: Path) -> None:
        try:
            with ZipFile(path) as package:
                entries = package.infolist()
                if len(entries) > self.max_entries:
                    raise UnsafeDocxPackageError()
                total = sum(entry.file_size for entry in entries)
                compressed = sum(max(entry.compress_size, 1) for entry in entries)
                if (
                    total > self.max_uncompressed_bytes
                    or total / max(compressed, 1) > self.max_compression_ratio
                ):
                    raise UnsafeDocxPackageError()
                for entry in entries:
                    if entry.filename.endswith(".rels"):
                        content = package.read(entry)
                        if (
                            b'TargetMode="External"' in content
                            or b"TargetMode='External'" in content
                        ):
                            raise ExternalDocxRelationshipError()
        except BadZipFile as exc:
            raise InvalidDocxError() from exc


def _paragraph_kind(paragraph: Paragraph) -> str:
    style = paragraph.style.name if paragraph.style is not None else ""
    if style.lower().startswith("heading"):
        return "heading"
    if paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None:
        return "list_item"
    return "paragraph"


def _heading_level(paragraph: Paragraph) -> int:
    style = paragraph.style.name if paragraph.style is not None else ""
    suffix = style.rsplit(" ", maxsplit=1)[-1]
    return int(suffix) if suffix.isdigit() else 1


def _image_relationship_ids(paragraph: Paragraph) -> Iterable[str]:
    for blip in paragraph._p.xpath(".//a:blip"):
        relationship_id = blip.get(qn("r:embed"))
        if relationship_id:
            yield str(relationship_id)


def _safe_source_part(target_ref: str) -> str:
    normalized = posixpath.normpath(posixpath.join("word", target_ref.replace("\\", "/")))
    if not normalized.startswith("word/media/") or ".." in normalized.split("/"):
        raise InvalidDocxError()
    return normalized
