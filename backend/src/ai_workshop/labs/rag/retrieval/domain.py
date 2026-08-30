from dataclasses import dataclass
from uuid import UUID

from ai_workshop.labs.rag.documents.domain import EvidenceUnit
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor

type ChunkIdentifier = UUID | str


class QueryEmbeddingUnavailableError(RuntimeError):
    pass


class SearchBackendUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ActiveIndexAlias:
    descriptor: IndexDescriptor
    index_prefix: str
    indexing_profile_id: UUID

    def __post_init__(self) -> None:
        if not self.index_prefix.strip():
            raise ValueError("An active index alias requires a non-empty index prefix.")

    @property
    def name(self) -> str:
        return self.descriptor.active_alias(
            self.index_prefix,
            self.indexing_profile_id,
        )


@dataclass(frozen=True, slots=True)
class ResolvedSearchScope:
    workspace_ids: tuple[UUID, ...]
    folder_ids: tuple[UUID, ...]
    active_only: bool = True
    ready_only: bool = True


@dataclass(frozen=True, slots=True)
class RankedHit:
    chunk_id: ChunkIdentifier
    rank: int


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    projection_id: UUID
    asset_version_id: UUID
    workspace_id: UUID
    folder_id: UUID | None
    index_build_id: UUID
    title: str
    section_path: tuple[str, ...]
    text: str
    evidence_units: tuple[EvidenceUnit, ...]


@dataclass(frozen=True, slots=True)
class SparseHit:
    chunk: RetrievedChunk
    rank: int
    score: float

    @property
    def chunk_id(self) -> UUID:
        return self.chunk.chunk_id


@dataclass(frozen=True, slots=True)
class DenseHit:
    chunk: RetrievedChunk
    rank: int
    score: float

    @property
    def chunk_id(self) -> UUID:
        return self.chunk.chunk_id


@dataclass(frozen=True, slots=True)
class FusedHit:
    chunk_id: ChunkIdentifier
    score: float
    best_rank: int
    sparse_rank: int | None
    dense_rank: int | None
    chunk: RetrievedChunk | None = None
