import re
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
class FrozenIndexIdentity:
    index_name: str
    index_uuid: str
    index_build_id: UUID
    projection_id: UUID
    indexing_profile_id: UUID
    vector_dimension: int
    mapping_version: int

    def __post_init__(self) -> None:
        if not self.index_name.strip() or not self.index_uuid.strip():
            raise ValueError("A frozen index identity requires its physical name and UUID.")
        if self.vector_dimension < 1 or self.mapping_version < 1:
            raise ValueError("A frozen index identity requires a valid immutable descriptor.")


@dataclass(frozen=True, slots=True)
class FrozenIndexTarget:
    descriptor: IndexDescriptor
    index_prefix: str
    indexing_profile_id: UUID
    identities: tuple[FrozenIndexIdentity, ...]
    asset_version_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[a-z0-9][a-z0-9._-]*", self.index_prefix) is None
            or self.index_prefix in {".", ".."}
        ):
            raise ValueError("A frozen target requires a safe physical index prefix.")
        if not self.identities:
            raise ValueError("A frozen index target requires concrete index identities.")
        index_names = self.index_names
        index_build_ids = self.index_build_ids
        if len(index_names) != len(set(index_names)):
            raise ValueError("Concrete index names must be unique.")
        if len(index_build_ids) != len(set(index_build_ids)):
            raise ValueError("Concrete index build IDs must be unique.")
        if not self.asset_version_ids or len(self.asset_version_ids) != len(
            set(self.asset_version_ids)
        ):
            raise ValueError("A frozen target requires unique Asset Versions.")
        expected_names = tuple(
            self.descriptor.concrete_index_name(
                self.index_prefix,
                self.indexing_profile_id,
                build_id,
            )
            for build_id in index_build_ids
        )
        if index_names != expected_names:
            raise ValueError(
                "A frozen target must use the exact physical index for its profile/build."
            )
        if any(
            identity.indexing_profile_id != self.indexing_profile_id
            or identity.vector_dimension != self.descriptor.vector_dimension
            or identity.mapping_version != self.descriptor.mapping_version
            for identity in self.identities
        ):
            raise ValueError("A frozen target descriptor must match every index identity.")

    @property
    def index_names(self) -> tuple[str, ...]:
        return tuple(item.index_name for item in self.identities)

    @property
    def index_build_ids(self) -> tuple[UUID, ...]:
        return tuple(item.index_build_id for item in self.identities)

    @property
    def projection_ids(self) -> tuple[UUID, ...]:
        return tuple(item.projection_id for item in self.identities)


type SearchIndexTarget = ActiveIndexAlias | FrozenIndexTarget


@dataclass(frozen=True, slots=True)
class ResolvedSearchScope:
    workspace_ids: tuple[UUID, ...]
    folder_ids: tuple[UUID, ...]
    active_only: bool = True
    ready_only: bool = True
    asset_version_ids: tuple[UUID, ...] = ()
    index_build_ids: tuple[UUID, ...] = ()


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
