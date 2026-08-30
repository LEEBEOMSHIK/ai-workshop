from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from ai_workshop.labs.rag.indexing.contracts import (
    IndexDescriptor,
    IndexDocument,
    SearchIndexPort,
)


@dataclass(frozen=True, slots=True)
class IndexingResult:
    index_name: str
    alias: str
    indexed_document_count: int
    alias_verified: bool


class IndexingService:
    def __init__(self, search_index: SearchIndexPort, *, index_prefix: str) -> None:
        self.search_index = search_index
        self.index_prefix = index_prefix

    async def index_projection(
        self,
        *,
        descriptor: IndexDescriptor,
        profile_id: UUID,
        build_id: UUID,
        projection_id: UUID,
        expected_chunk_count: int,
        documents: Sequence[IndexDocument],
    ) -> IndexingResult:
        if expected_chunk_count < 0:
            raise ValueError("The expected chunk count cannot be negative.")
        self._validate_documents(documents, projection_id, build_id, descriptor.vector_dimension)
        index_name = descriptor.concrete_index_name(self.index_prefix, profile_id, build_id)
        alias = descriptor.active_alias(self.index_prefix, profile_id)
        await self.search_index.create(descriptor.for_index(index_name))
        written_count = await self.search_index.bulk_upsert(index_name, documents)
        if written_count != len(documents):
            raise ValueError("Elasticsearch bulk indexing did not write every supplied chunk.")
        indexed_document_count = await self.search_index.count_projection(index_name, projection_id)
        if indexed_document_count != expected_chunk_count:
            raise ValueError(
                "Elasticsearch projection count mismatch: "
                f"expected {expected_chunk_count}, found {indexed_document_count}."
            )
        await self.search_index.activate(alias, index_name)
        return IndexingResult(index_name, alias, indexed_document_count, alias_verified=True)

    @staticmethod
    def _validate_documents(
        documents: Sequence[IndexDocument],
        projection_id: UUID,
        build_id: UUID,
        vector_dimension: int,
    ) -> None:
        for document in documents:
            if document.projection_id != projection_id:
                raise ValueError("Every indexed chunk must belong to the requested projection.")
            if document.index_build_id != build_id:
                raise ValueError("Every indexed chunk must preserve the requested index build ID.")
            if document.embedding is not None and len(document.embedding) != vector_dimension:
                raise ValueError("An embedding must match the immutable index vector dimension.")
