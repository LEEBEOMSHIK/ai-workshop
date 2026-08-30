from collections.abc import Sequence

from ai_workshop.labs.rag.retrieval.domain import (
    ChunkIdentifier,
    DenseHit,
    FusedHit,
    RankedHit,
    RetrievedChunk,
    SparseHit,
)

type RankedInput = RankedHit | SparseHit | DenseHit


def rrf_fuse(
    sparse: Sequence[RankedInput],
    dense: Sequence[RankedInput],
    *,
    k: int = 60,
) -> tuple[FusedHit, ...]:
    if k < 0:
        raise ValueError("RRF k must not be negative.")

    sparse_ranks = _best_ranks(sparse)
    dense_ranks = _best_ranks(dense)
    first_seen: dict[ChunkIdentifier, int] = {}
    for chunk_id in (*sparse_ranks, *dense_ranks):
        first_seen.setdefault(chunk_id, len(first_seen))
    chunks = _chunks((*sparse, *dense))

    fused = []
    for chunk_id in first_seen:
        sparse_rank = sparse_ranks.get(chunk_id)
        dense_rank = dense_ranks.get(chunk_id)
        ranks = tuple(rank for rank in (sparse_rank, dense_rank) if rank is not None)
        fused.append(
            FusedHit(
                chunk_id=chunk_id,
                score=sum(1 / (k + rank) for rank in ranks),
                best_rank=min(ranks),
                sparse_rank=sparse_rank,
                dense_rank=dense_rank,
                chunk=chunks.get(chunk_id),
            )
        )

    return tuple(
        sorted(
            fused,
            key=lambda hit: (-hit.score, hit.best_rank, first_seen[hit.chunk_id]),
        )
    )


def _best_ranks(hits: Sequence[RankedInput]) -> dict[ChunkIdentifier, int]:
    ranks: dict[ChunkIdentifier, int] = {}
    for hit in hits:
        if hit.rank < 1:
            raise ValueError("RRF ranks must be positive.")
        current = ranks.get(hit.chunk_id)
        if current is None or hit.rank < current:
            ranks[hit.chunk_id] = hit.rank
    return ranks


def _chunks(hits: Sequence[RankedInput]) -> dict[ChunkIdentifier, RetrievedChunk]:
    chunks: dict[ChunkIdentifier, RetrievedChunk] = {}
    for hit in hits:
        if isinstance(hit, RankedHit):
            continue
        existing = chunks.get(hit.chunk_id)
        if existing is not None and existing != hit.chunk:
            raise ValueError("Sparse and dense hits disagree on immutable chunk provenance.")
        chunks[hit.chunk_id] = hit.chunk
    return chunks
