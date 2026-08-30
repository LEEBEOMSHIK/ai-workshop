"""Extractive evidence selection and truthful source highlighting."""

from ai_workshop.labs.rag.highlighting.domain import (
    AnswerPolicy,
    AnswerStatus,
    ConflictState,
    EvidenceAnswer,
    EvidenceSelection,
    EvidenceSource,
    HighlightKind,
    HighlightSpan,
)
from ai_workshop.labs.rag.highlighting.service import EvidenceSelector

__all__ = [
    "AnswerPolicy",
    "AnswerStatus",
    "ConflictState",
    "EvidenceAnswer",
    "EvidenceSelection",
    "EvidenceSelector",
    "EvidenceSource",
    "HighlightKind",
    "HighlightSpan",
]
