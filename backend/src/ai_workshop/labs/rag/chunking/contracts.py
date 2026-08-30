from dataclasses import dataclass
from typing import Protocol

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, RetrievalChunk


class TokenCounter(Protocol):
    def count(self, text: str) -> int:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    target_tokens: int = 380
    overlap_tokens: int = 60
    hard_ceiling_tokens: int = 440

    def __post_init__(self) -> None:
        if self.target_tokens < 1:
            raise ValueError("The chunk target must be positive.")
        if self.overlap_tokens < 0:
            raise ValueError("The chunk overlap cannot be negative.")
        if self.overlap_tokens > self.target_tokens:
            raise ValueError("The chunk overlap cannot exceed the chunk target.")
        if self.hard_ceiling_tokens < self.target_tokens:
            raise ValueError("The chunk ceiling cannot be lower than the chunk target.")


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    chunks: tuple[RetrievalChunk, ...]
    evidence_units: tuple[EvidenceUnit, ...]
