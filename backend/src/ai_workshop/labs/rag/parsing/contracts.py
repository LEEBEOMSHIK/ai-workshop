from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from ai_workshop.labs.rag.documents.domain import ParsedDocument


class ParserTemporaryWorkspace(Protocol):
    def create_file(self, name: str) -> Path: ...


@dataclass(frozen=True, slots=True)
class ParseRequest:
    path: Path
    media_type: str
    filename: str
    asset_version_id: UUID
    temporary_workspace: ParserTemporaryWorkspace | None = None
    opaque_runtime_started: Callable[[], None] | None = None

    def mark_opaque_runtime_started(self) -> None:
        if self.temporary_workspace is None or self.opaque_runtime_started is None:
            raise ParsingError(
                "temporary_workspace_required", "Tracked temporary workspace required."
            )
        self.opaque_runtime_started()

    def create_temporary_file(self, name: str) -> Path:
        if self.temporary_workspace is None or self.opaque_runtime_started is None:
            raise ParsingError(
                "temporary_workspace_required", "Tracked temporary workspace required."
            )
        return self.temporary_workspace.create_file(name)


class ParserPort(Protocol):
    def parse(self, request: ParseRequest) -> ParsedDocument: ...


class ParsingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class UnsupportedEncodingError(ParsingError):
    def __init__(self) -> None:
        super().__init__("unsupported_encoding", "Only UTF-8 text sources are supported.")


class OcrRequiredError(ParsingError):
    def __init__(self, page_number: int) -> None:
        super().__init__("ocr_required", f"PDF page {page_number} has no extractable text.")


class UnsupportedParserError(ParsingError):
    def __init__(self, media_type: str, filename: str) -> None:
        super().__init__(
            "unsupported_format", f"Unsupported source format: {media_type} ({filename})."
        )


class ConflictingFormatError(ParsingError):
    def __init__(self, media_type: str, filename: str) -> None:
        super().__init__(
            "conflicting_format",
            f"Media type {media_type} conflicts with filename extension in {filename}.",
        )


class InvalidPdfCoordinatesError(ParsingError):
    def __init__(self, page_number: int) -> None:
        super().__init__(
            "invalid_pdf_coordinates",
            f"PDF page {page_number} has text coordinates outside page bounds.",
        )


class PdfProcessingLimitError(ParsingError):
    def __init__(self) -> None:
        super().__init__(
            "pdf_processing_limit_exceeded", "PDF exceeds the configured processing limits."
        )


class InvalidPdfError(ParsingError):
    def __init__(self) -> None:
        super().__init__("pdf_invalid", "PDF is malformed, encrypted or unreadable.")


class EmptyPdfOcrError(ParsingError):
    def __init__(self, page_number: int) -> None:
        super().__init__(
            "pdf_ocr_empty", f"OCR returned no text or table content for PDF page {page_number}."
        )


class DocxPackageError(ParsingError):
    pass


class InvalidDocxError(DocxPackageError):
    def __init__(self) -> None:
        super().__init__("docx_invalid", "The DOCX package is malformed or unreadable.")


class UnsafeDocxPackageError(DocxPackageError):
    def __init__(self) -> None:
        super().__init__("docx_package_unsafe", "The DOCX package exceeds safe processing limits.")


class ExternalDocxRelationshipError(DocxPackageError):
    def __init__(self) -> None:
        super().__init__(
            "docx_external_relationship",
            "The DOCX package contains an external relationship.",
        )


class UnsupportedEmbeddedImageError(DocxPackageError):
    def __init__(self) -> None:
        super().__init__(
            "docx_image_unsupported",
            "The DOCX package contains an unsupported embedded image.",
        )
