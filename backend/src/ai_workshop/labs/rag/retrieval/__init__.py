"""Permission-filtered sparse and dense retrieval for RAG."""

from ai_workshop.labs.rag.retrieval.domain import (
    DenseHit,
    FusedHit,
    RankedHit,
    ResolvedSearchScope,
    RetrievedChunk,
    SparseHit,
)
from ai_workshop.labs.rag.retrieval.rrf import rrf_fuse
from ai_workshop.labs.rag.retrieval.scope import SearchScopeResolver
from ai_workshop.labs.rag.retrieval.service import HybridRetrievalService

__all__ = [
    "DenseHit",
    "FusedHit",
    "HybridRetrievalService",
    "RankedHit",
    "ResolvedSearchScope",
    "RetrievedChunk",
    "SearchScopeResolver",
    "SparseHit",
    "rrf_fuse",
]
