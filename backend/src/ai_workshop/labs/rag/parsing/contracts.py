from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from ai_workshop.labs.rag.documents.domain import ParsedDocument


@dataclass(frozen=True, slots=True)
class ParseRequest:
    path: Path
    media_type: str
    filename: str
    asset_version_id: UUID


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
