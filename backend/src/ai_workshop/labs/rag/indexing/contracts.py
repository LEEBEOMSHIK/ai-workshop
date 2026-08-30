from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from ai_workshop.labs.rag.documents.domain import EvidenceUnit


@dataclass(frozen=True, slots=True)
class IndexDescriptor:
    vector_dimension: int
    similarity: str
    index_name: str | None = None

    def __post_init__(self) -> None:
        if self.vector_dimension < 1:
            raise ValueError("A vector dimension must be positive.")
        if self.similarity != "cosine":
            raise ValueError("The RAG projection supports cosine similarity only.")

    def concrete_index_name(self, prefix: str, profile_id: UUID, build_id: UUID) -> str:
        return f"{prefix}-{profile_id}-{build_id}"

    def active_alias(self, prefix: str, profile_id: UUID) -> str:
        return f"{prefix}-{profile_id}-active"

    def for_index(self, index_name: str) -> "IndexDescriptor":
        return replace(self, index_name=index_name)


@dataclass(frozen=True, slots=True)
class IndexDocument:
    chunk_id: UUID
    projection_id: UUID
    asset_version_id: UUID
    workspace_id: UUID
    folder_id: UUID | None
    allowed_user_ids: tuple[UUID, ...]
    status: str
    title: str
    section_path: tuple[str, ...]
    text: str
    evidence_units: tuple[EvidenceUnit, ...]
    embedding: tuple[float, ...] | None
    index_build_id: UUID

    def to_projection(self) -> dict[str, object]:
        return {
            "chunk_id": str(self.chunk_id),
            "projection_id": str(self.projection_id),
            "asset_version_id": str(self.asset_version_id),
            "workspace_id": str(self.workspace_id),
            "folder_id": str(self.folder_id) if self.folder_id is not None else None,
            "allowed_user_ids": [str(user_id) for user_id in self.allowed_user_ids],
            "status": self.status,
            "title": self.title,
            "section_path": list(self.section_path),
            "text": self.text,
            "evidence_units": [
                {
                    "id": str(evidence.id),
                    "ordinal": evidence.ordinal,
                    "text": evidence.text,
                    "element_id": str(evidence.location.element_id),
                    "page": evidence.location.page,
                    "char_start": evidence.location.char_start,
                    "char_end": evidence.location.char_end,
                    "bbox": list(evidence.location.bbox)
                    if evidence.location.bbox is not None
                    else None,
                }
                for evidence in self.evidence_units
            ],
            "embedding": list(self.embedding) if self.embedding is not None else None,
            "index_build_id": str(self.index_build_id),
        }


class SearchIndexPort(Protocol):
    async def create(self, descriptor: IndexDescriptor) -> None:
        raise NotImplementedError

    async def bulk_upsert(self, index_name: str, documents: Sequence[IndexDocument]) -> int:
        raise NotImplementedError

    async def count_projection(self, index_name: str, projection_id: UUID) -> int:
        raise NotImplementedError

    async def activate(self, alias: str, index_name: str) -> None:
        raise NotImplementedError
