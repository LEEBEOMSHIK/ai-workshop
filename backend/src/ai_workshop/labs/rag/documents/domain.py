from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID, uuid4


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


@dataclass(frozen=True, slots=True)
class SourceLocation:
    element_id: UUID
    page: int | None
    char_start: int
    char_end: int
    bbox: tuple[float, float, float, float] | None

    def __post_init__(self) -> None:
        if self.char_start < 0 or self.char_end < self.char_start:
            raise ProvenanceError("Source character offsets must be non-negative and ordered.")
        if self.page is not None and self.page < 1:
            raise ProvenanceError("Source page numbers must be one-based.")
        if self.bbox is not None and len(self.bbox) != 4:
            raise ProvenanceError("PDF coordinates must contain four values.")


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

    @classmethod
    def create(
        cls,
        *,
        text: str,
        location: SourceLocation | None,
        ordinal: int,
        chunk_id: UUID | None = None,
    ) -> "EvidenceUnit":
        if location is None:
            raise ProvenanceError("Evidence units require a source location.")
        return cls(uuid4(), chunk_id, ordinal, text, location)


@dataclass(frozen=True, slots=True)
class RetrievalChunk:
    id: UUID
    projection_id: UUID
    ordinal: int
    text: str
    section_path: tuple[str, ...]
    evidence_units: tuple[EvidenceUnit, ...]


@dataclass(frozen=True, slots=True)
class RagProjection:
    id: UUID
    asset_version_id: UUID
    indexing_profile_id: UUID
    status: ProjectionStatus

    @classmethod
    def pending(cls, *, asset_version_id: UUID, indexing_profile_id: UUID) -> "RagProjection":
        return cls(uuid4(), asset_version_id, indexing_profile_id, ProjectionStatus.PENDING)

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
