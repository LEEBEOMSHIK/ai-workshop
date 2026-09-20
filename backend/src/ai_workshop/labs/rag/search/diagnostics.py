"""Private request-local diagnostics. Never persist candidate text here."""

from dataclasses import dataclass

from ai_workshop.labs.rag.highlighting.context import CandidateDiagnostic
from ai_workshop.labs.rag.highlighting.domain import EvidenceSource
from ai_workshop.labs.rag.retrieval.domain import FusedHit


@dataclass(frozen=True, slots=True)
class SearchDiagnostics:
    candidates: tuple[CandidateDiagnostic, ...]
    hits: tuple[FusedHit, ...]
    sources: tuple[EvidenceSource, ...]
    stages_ms: dict[str, float | None]
    min_keyword_coverage: float
    min_semantic_score: float
    warning: str | None = None
