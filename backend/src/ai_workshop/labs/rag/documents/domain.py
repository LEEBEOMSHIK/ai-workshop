from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID, uuid4

from ai_workshop.labs.rag.models.document_processing import (
    LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
)


class ProjectionStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    PARTIAL_READY = "partial_ready"


class InvalidProjectionTransition(ValueError):
    pass


class ProvenanceError(ValueError):
    pass


class SourceKind(StrEnum):
    NORMALIZED_TEXT = "normalized_text"
    PDF_PAGE = "pdf_page"
    DOCX_IMAGE = "docx_image"


@dataclass(frozen=True, slots=True)
class TableCellLocation:
    row: int
    column: int
    row_span: int = 1
    column_span: int = 1

    def __post_init__(self) -> None:
        if self.row < 0 or self.column < 0:
            raise ProvenanceError("Table cell coordinates must be non-negative.")
        if self.row_span < 1 or self.column_span < 1:
            raise ProvenanceError("Table cell spans must be positive.")


@dataclass(frozen=True, slots=True)
class SourceLocation:
    element_id: UUID
    page: int | None
    char_start: int
    char_end: int
    bbox: tuple[float, float, float, float] | None
    source_kind: SourceKind = SourceKind.NORMALIZED_TEXT
    source_part: str | None = None
    image_sha256: str | None = None
    table_cell: TableCellLocation | None = None

    def __post_init__(self) -> None:
        if (
            self.source_kind is SourceKind.NORMALIZED_TEXT
            and self.page is not None
            and self.source_part is None
            and self.image_sha256 is None
        ):
            object.__setattr__(self, "source_kind", SourceKind.PDF_PAGE)
        if self.char_start < 0 or self.char_end < self.char_start:
            raise ProvenanceError("Source character offsets must be non-negative and ordered.")
        if self.page is not None and self.page < 1:
            raise ProvenanceError("Source page numbers must be one-based.")
        if self.bbox is not None:
            if len(self.bbox) != 4:
                raise ProvenanceError("Source coordinates must contain four values.")
            left, top, right, bottom = self.bbox
            if left > right or top > bottom:
                raise ProvenanceError("Source coordinates must be ordered.")
        if self.source_kind is SourceKind.PDF_PAGE and self.page is None:
            raise ProvenanceError("PDF source locations require a page number.")
        if self.source_kind is SourceKind.DOCX_IMAGE:
            if not self.source_part or not self.source_part.startswith("word/media/"):
                raise ProvenanceError("DOCX image locations require a safe source part.")
            if (
                self.image_sha256 is None
                or len(self.image_sha256) != 64
                or any(character not in "0123456789abcdef" for character in self.image_sha256)
            ):
                raise ProvenanceError("DOCX image locations require a SHA-256 identity.")
            if self.bbox is None or any(value < 0 or value > 1 for value in self.bbox):
                raise ProvenanceError("DOCX image coordinates must be normalized to [0, 1].")

    @classmethod
    def docx_image(
        cls,
        *,
        element_id: UUID,
        char_start: int,
        char_end: int,
        source_part: str,
        image_sha256: str,
        bbox: tuple[float, float, float, float],
        table_cell: TableCellLocation | None = None,
    ) -> "SourceLocation":
        return cls(
            element_id=element_id,
            page=None,
            char_start=char_start,
            char_end=char_end,
            bbox=bbox,
            source_kind=SourceKind.DOCX_IMAGE,
            source_part=source_part,
            image_sha256=image_sha256,
            table_cell=table_cell,
        )


@dataclass(frozen=True, slots=True)
class StructuralElement:
    id: UUID
    ordinal: int
    kind: str
    text: str
    section_path: tuple[str, ...]
    location: SourceLocation
    parser_name: str
    parser_version: str
    confidence: float | None
    evidence_eligible: bool = True
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.location.element_id != self.id:
            raise ProvenanceError("Structural element provenance must reference the element ID.")


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    asset_version_id: UUID
    parser_name: str
    parser_version: str
    elements: tuple[StructuralElement, ...]


@dataclass(frozen=True, slots=True)
class EvidenceUnit:
    id: UUID
    chunk_id: UUID | None
    ordinal: int
    text: str
    location: SourceLocation
    projection_id: UUID | None = None

    @classmethod
    def create(
        cls,
        *,
        text: str,
        location: SourceLocation | None,
        ordinal: int,
        chunk_id: UUID | None = None,
        projection_id: UUID | None = None,
    ) -> "EvidenceUnit":
        if location is None:
            raise ProvenanceError("Evidence units require a source location.")
        return cls(uuid4(), chunk_id, ordinal, text, location, projection_id)


@dataclass(frozen=True, slots=True)
class RetrievalChunk:
    id: UUID
    projection_id: UUID
    ordinal: int
    text: str
    section_path: tuple[str, ...]
    evidence_units: tuple[EvidenceUnit, ...]

    def __post_init__(self) -> None:
        for evidence in self.evidence_units:
            if evidence.chunk_id != self.id:
                raise ProvenanceError(
                    "Evidence units must declare their containing retrieval chunk."
                )
            if evidence.projection_id != self.projection_id:
                raise ProvenanceError("Evidence units must declare the chunk projection.")


@dataclass(frozen=True, slots=True)
class RagProjection:
    id: UUID
    asset_version_id: UUID
    indexing_profile_id: UUID
    status: ProjectionStatus
    document_processing_profile_id: UUID = LEGACY_DOCUMENT_PROCESSING_PROFILE_ID

    @classmethod
    def pending(
        cls,
        *,
        asset_version_id: UUID,
        indexing_profile_id: UUID,
        document_processing_profile_id: UUID = LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
    ) -> "RagProjection":
        return cls(
            uuid4(),
            asset_version_id,
            indexing_profile_id,
            ProjectionStatus.PENDING,
            document_processing_profile_id,
        )

    def transition(self, status: ProjectionStatus) -> "RagProjection":
        allowed = {
            ProjectionStatus.PENDING: {
                ProjectionStatus.PARSING,
                ProjectionStatus.FAILED,
                ProjectionStatus.PARTIAL_READY,
            },
            ProjectionStatus.PARSING: {
                ProjectionStatus.CHUNKING,
                ProjectionStatus.FAILED,
                ProjectionStatus.PARTIAL_READY,
            },
            ProjectionStatus.CHUNKING: {
                ProjectionStatus.EMBEDDING,
                ProjectionStatus.FAILED,
                ProjectionStatus.PARTIAL_READY,
            },
            ProjectionStatus.EMBEDDING: {
                ProjectionStatus.INDEXING,
                ProjectionStatus.FAILED,
                ProjectionStatus.PARTIAL_READY,
            },
            ProjectionStatus.INDEXING: {
                ProjectionStatus.READY,
                ProjectionStatus.FAILED,
                ProjectionStatus.PARTIAL_READY,
            },
            ProjectionStatus.READY: set(),
            ProjectionStatus.FAILED: set(),
            ProjectionStatus.PARTIAL_READY: set(),
        }
        if status not in allowed[self.status]:
            raise InvalidProjectionTransition(
                f"Cannot transition a {self.status.value} projection to {status.value}."
            )
        return replace(self, status=status)
