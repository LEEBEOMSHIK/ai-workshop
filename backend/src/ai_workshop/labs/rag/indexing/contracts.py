import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from ai_workshop.labs.rag.documents.domain import EvidenceUnit

_SAFE_ELASTICSEARCH_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")


def canonical_active_targets(alias: str, index_names: Sequence[str]) -> tuple[str, ...]:
    targets = tuple(index_names)
    if not targets:
        raise ValueError("An active RAG alias requires at least one concrete target.")
    if len(targets) != len(set(targets)):
        raise ValueError("An active RAG alias target set cannot contain duplicates.")
    if _SAFE_ELASTICSEARCH_NAME.fullmatch(alias) is None or not alias.endswith("-active"):
        raise ValueError("An active RAG alias must use a safe profile alias name.")
    alias_base = alias.removesuffix("-active")
    if len(alias_base) < 38 or alias_base[-37] != "-":
        raise ValueError("An active RAG alias must identify its immutable profile.")
    profile_text = alias_base[-36:]
    try:
        profile_id = UUID(profile_text)
    except ValueError as exc:
        raise ValueError("An active RAG alias must identify its immutable profile.") from exc
    if str(profile_id) != profile_text or not alias_base[:-37]:
        raise ValueError("An active RAG alias must use a canonical profile identity.")
    target_prefix = f"{alias_base}-"
    for target in targets:
        if (
            _SAFE_ELASTICSEARCH_NAME.fullmatch(target) is None
            or not target.startswith(target_prefix)
        ):
            raise ValueError("Every active alias target must belong to the exact profile.")
        build_text = target.removeprefix(target_prefix)
        try:
            build_id = UUID(build_text)
        except ValueError as exc:
            raise ValueError(
                "Every active alias target must identify an immutable build."
            ) from exc
        if str(build_id) != build_text:
            raise ValueError("Every active alias target must use a canonical build identity.")
    return tuple(sorted(targets))


@dataclass(frozen=True, slots=True)
class IndexDescriptor:
    vector_dimension: int
    similarity: str
    index_name: str | None = None
    indexing_profile_id: UUID | None = None
    index_build_id: UUID | None = None
    projection_id: UUID | None = None
    mapping_version: int = 1

    def __post_init__(self) -> None:
        if self.vector_dimension < 1:
            raise ValueError("A vector dimension must be positive.")
        if self.similarity != "cosine":
            raise ValueError("The RAG projection supports cosine similarity only.")

    def concrete_index_name(self, prefix: str, profile_id: UUID, build_id: UUID) -> str:
        return f"{prefix}-{profile_id}-{build_id}"

    def active_alias(self, prefix: str, profile_id: UUID) -> str:
        return f"{prefix}-{profile_id}-active"

    def for_index(
        self,
        index_name: str,
        *,
        indexing_profile_id: UUID | None = None,
        index_build_id: UUID | None = None,
        projection_id: UUID | None = None,
    ) -> "IndexDescriptor":
        return replace(
            self,
            index_name=index_name,
            indexing_profile_id=indexing_profile_id,
            index_build_id=index_build_id,
            projection_id=projection_id,
        )

    def require_physical_metadata(self) -> tuple[UUID, UUID, UUID]:
        if (
            self.indexing_profile_id is None
            or self.index_build_id is None
            or self.projection_id is None
        ):
            raise ValueError("A physical RAG index requires immutable descriptor metadata.")
        return self.indexing_profile_id, self.index_build_id, self.projection_id


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
    indexing_profile_id: UUID | None = None
    rag_mapping_version: int = 1

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
                    "chunk_id": str(evidence.chunk_id),
                    "projection_id": str(evidence.projection_id),
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
            "indexing_profile_id": (
                str(self.indexing_profile_id)
                if self.indexing_profile_id is not None
                else None
            ),
            "rag_mapping_version": self.rag_mapping_version,
        }


class SearchIndexPort(Protocol):
    async def create(self, descriptor: IndexDescriptor) -> None:
        raise NotImplementedError

    async def bulk_upsert(self, index_name: str, documents: Sequence[IndexDocument]) -> int:
        raise NotImplementedError

    async def count_projection(self, index_name: str, projection_id: UUID) -> int:
        raise NotImplementedError

    async def replace_active_targets(
        self, alias: str, index_names: Sequence[str]
    ) -> bool:
        raise NotImplementedError

    async def active_targets(self, alias: str) -> tuple[str, ...]:
        raise NotImplementedError
