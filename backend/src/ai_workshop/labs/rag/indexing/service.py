from collections.abc import Sequence
from dataclasses import dataclass, replace
from uuid import UUID

from ai_workshop.labs.rag.indexing.contracts import (
    IndexDescriptor,
    IndexDocument,
    SearchIndexPort,
    canonical_active_targets,
)


class AliasActivationNotAcknowledgedError(ValueError):
    """Elasticsearch received the alias update but did not acknowledge it."""


class ActiveAliasTargetMismatchError(ValueError):
    """The active alias does not identify the exact intended build set."""


@dataclass(frozen=True, slots=True)
class IndexingResult:
    descriptor: IndexDescriptor
    profile_id: UUID
    build_id: UUID
    projection_id: UUID
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
        prepared = await self.prepare_projection(
            descriptor=descriptor,
            profile_id=profile_id,
            build_id=build_id,
            projection_id=projection_id,
            expected_chunk_count=expected_chunk_count,
            documents=documents,
        )
        existing_targets = await self.search_index.active_targets(prepared.alias)
        intended_targets = tuple(sorted({*existing_targets, prepared.index_name}))
        return await self.activate_prepared(
            prepared,
            intended_targets=intended_targets,
        )

    async def prepare_projection(
        self,
        *,
        descriptor: IndexDescriptor,
        profile_id: UUID,
        build_id: UUID,
        projection_id: UUID,
        expected_chunk_count: int,
        documents: Sequence[IndexDocument],
    ) -> IndexingResult:
        if expected_chunk_count <= 0:
            raise ValueError("The expected chunk count must be positive.")
        if len(documents) != expected_chunk_count:
            raise ValueError("The supplied chunks must equal the expected chunk count.")
        if len({document.chunk_id for document in documents}) != len(documents):
            raise ValueError("Every supplied chunk must have a unique ID.")
        self._validate_documents(documents, projection_id, build_id, descriptor.vector_dimension)
        index_name = descriptor.concrete_index_name(self.index_prefix, profile_id, build_id)
        alias = descriptor.active_alias(self.index_prefix, profile_id)
        await self.search_index.create(
            descriptor.for_index(
                index_name,
                indexing_profile_id=profile_id,
                index_build_id=build_id,
                projection_id=projection_id,
            )
        )
        physical_documents = tuple(
            replace(
                document,
                indexing_profile_id=profile_id,
                rag_mapping_version=descriptor.mapping_version,
            )
            for document in documents
        )
        written_count = await self.search_index.bulk_upsert(index_name, physical_documents)
        if written_count != len(documents):
            raise ValueError("Elasticsearch bulk indexing did not write every supplied chunk.")
        indexed_document_count = await self.search_index.count_projection(index_name, projection_id)
        if indexed_document_count != expected_chunk_count:
            raise ValueError(
                "Elasticsearch projection count mismatch: "
                f"expected {expected_chunk_count}, found {indexed_document_count}."
            )
        return IndexingResult(
            descriptor=descriptor,
            profile_id=profile_id,
            build_id=build_id,
            projection_id=projection_id,
            index_name=index_name,
            alias=alias,
            indexed_document_count=indexed_document_count,
            alias_verified=False,
        )

    async def activate_prepared(
        self,
        prepared: IndexingResult,
        *,
        intended_targets: Sequence[str],
    ) -> IndexingResult:
        expected_alias = prepared.descriptor.active_alias(
            self.index_prefix,
            prepared.profile_id,
        )
        expected_name = prepared.descriptor.concrete_index_name(
            self.index_prefix,
            prepared.profile_id,
            prepared.build_id,
        )
        if prepared.alias != expected_alias or prepared.index_name != expected_name:
            raise ValueError(
                "The prepared index identity must match its service prefix, profile, and build."
            )
        targets = canonical_active_targets(prepared.alias, intended_targets)
        if prepared.index_name not in targets:
            raise ValueError("The exact active target set must include the prepared build.")
        if not await self.search_index.replace_active_targets(prepared.alias, targets):
            raise AliasActivationNotAcknowledgedError(
                "Elasticsearch did not acknowledge alias activation."
            )
        await self.revalidate_active_targets(
            alias=prepared.alias,
            intended_targets=targets,
        )
        return replace(prepared, alias_verified=True)

    async def revalidate_active_targets(
        self,
        *,
        alias: str,
        intended_targets: Sequence[str],
    ) -> bool:
        targets = canonical_active_targets(alias, intended_targets)
        if await self.search_index.active_targets(alias) != targets:
            raise ActiveAliasTargetMismatchError(
                "The active alias must resolve exactly to the verified index set."
            )
        return True

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
            for evidence in document.evidence_units:
                if evidence.chunk_id != document.chunk_id:
                    raise ValueError("Every evidence unit must declare its containing chunk.")
                if evidence.projection_id != document.projection_id:
                    raise ValueError("Every evidence unit must declare its containing projection.")
            if document.embedding is not None and len(document.embedding) != vector_dimension:
                raise ValueError("An embedding must match the immutable index vector dimension.")
