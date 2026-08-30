from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from ai_workshop.labs.rag.documents.domain import EvidenceUnit
from ai_workshop.labs.rag.retrieval.domain import RetrievedChunk


class AnswerStatus(StrEnum):
    SUPPORTED = "supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class HighlightKind(StrEnum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"


class ConflictState(StrEnum):
    NONE = "none"
    SEPARATE_SOURCES = "separate_sources"


@dataclass(frozen=True, slots=True)
class AnswerPolicy:
    min_semantic_score: float
    min_keyword_coverage: float
    require_complete_provenance: bool = True
    conflict_mode: str = "separate_sources"

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_semantic_score <= 1.0:
            raise ValueError("Minimum semantic score must be between zero and one.")
        if not 0.0 <= self.min_keyword_coverage <= 1.0:
            raise ValueError("Minimum keyword coverage must be between zero and one.")
        if self.require_complete_provenance is not True:
            raise ValueError("The extractive V1 policy requires complete provenance.")
        if self.conflict_mode != "separate_sources":
            raise ValueError("The extractive V1 policy requires separate source conflicts.")


@dataclass(frozen=True, slots=True)
class HighlightSpan:
    kind: HighlightKind
    evidence_unit_id: UUID
    text: str
    char_start: int
    char_end: int
    page: int | None
    bbox: tuple[float, float, float, float] | None
    score: float | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KeywordHighlightResult:
    coverage: float
    highlights: tuple[HighlightSpan, ...]


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    document_id: UUID
    asset_version_number: int
    media_type: str
    chunk: RetrievedChunk
    fused_score: float


@dataclass(frozen=True, slots=True)
class EvidenceAnswer:
    source: EvidenceSource
    evidence: EvidenceUnit
    excerpt: str
    highlights: tuple[HighlightSpan, ...]
    keyword_coverage: float | None
    semantic_score: float | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceSelection:
    status: AnswerStatus
    answer: EvidenceAnswer | None
    conflict_state: ConflictState
    conflicts: tuple[EvidenceAnswer, ...]
    warnings: tuple[str, ...] = ()
