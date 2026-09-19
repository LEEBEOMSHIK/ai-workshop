"""Transaction boundaries for tracked prepare; no external I/O before admission commit."""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord, RetrievalChunkRecord
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, IndexDocument
from ai_workshop.labs.rag.indexing.resource_models import RagIndexAttemptRecord
from ai_workshop.labs.rag.indexing.resource_repository import SqlAlchemyRagIndexRepository
from ai_workshop.labs.rag.indexing.tracked_elasticsearch import (
    IndexPreparationFailed,
    TrackedElasticsearchIndex,
    TrackedIndexObservation,
    index_input_fingerprint,
)
from ai_workshop.labs.rag.indexing.tracking_contracts import (
    IndexBinding,
    IndexResource,
    IndexTrackingError,
    index_chunk_ids_fingerprint,
)
from ai_workshop.labs.rag.models.document_processing import (
    index_namespace_document_processing_profile_id,
)


class TrackedIndexPort(Protocol):
    async def prepare(
        self,
        resource: IndexResource,
        documents: Sequence[IndexDocument],
        on_identity: Callable[[str], Awaitable[None]],
    ) -> TrackedIndexObservation: ...

    async def observe(
        self,
        resource: IndexResource,
        expected_chunk_ids: Sequence[UUID],
    ) -> TrackedIndexObservation: ...


type TrackedIndexSession = Callable[[], AbstractAsyncContextManager[TrackedIndexPort]]
type StageLock = Callable[[AsyncSession], Awaitable[None]]


def configured_index_binding(settings: Settings) -> IndexBinding:
    if settings.rag_index_store_id is None or settings.rag_index_cluster_uuid is None:
        raise IndexTrackingError("rag_index_binding_mismatch")
    return IndexBinding(settings.rag_index_store_id, settings.rag_index_cluster_uuid)


@asynccontextmanager
async def tracked_index_session(settings: Settings) -> AsyncIterator[TrackedIndexPort]:
    binding = configured_index_binding(settings)
    client = create_elasticsearch(settings)
    try:
        yield TrackedElasticsearchIndex(client, binding)
    finally:
        await client.close()


def require_registered_configuration(resource: IndexResource, settings: Settings) -> None:
    if resource.binding != configured_index_binding(settings):
        raise IndexTrackingError("rag_index_binding_mismatch")
    descriptor = IndexDescriptor(
        resource.vector_dimension, resource.similarity, mapping_version=resource.mapping_version
    )
    processing_id = index_namespace_document_processing_profile_id(
        resource.document_processing_profile_id,
    )
    if resource.index_name != descriptor.concrete_index_name(
        settings.elasticsearch_index_prefix,
        resource.indexing_profile_id,
        resource.build_id,
        document_processing_profile_id=processing_id,
    ) or resource.alias != descriptor.active_alias(
        settings.elasticsearch_index_prefix,
        resource.indexing_profile_id,
        document_processing_profile_id=processing_id,
    ):
        raise IndexTrackingError("rag_index_identity_conflict")


async def _lock_build(session: AsyncSession, build_id: UUID) -> RagIndexBuildRecord:
    build = await session.scalar(
        select(RagIndexBuildRecord)
        .where(
            RagIndexBuildRecord.id == build_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if build is None:
        raise IndexTrackingError("rag_index_identity_conflict")
    return build


async def _require_closed(session: AsyncSession, build_id: UUID) -> None:
    if (
        await session.scalar(
            select(RagIndexAttemptRecord.id).where(
                RagIndexAttemptRecord.build_id == build_id,
                RagIndexAttemptRecord.state == "open",
            )
        )
        is not None
    ):
        raise IndexTrackingError("rag_index_attempt_busy")


async def prepare_tracked_index(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    build_id: UUID,
    documents: Sequence[IndexDocument],
    adapters: TrackedIndexSession,
    lock_stage: StageLock,
) -> None:
    fingerprint = index_input_fingerprint(documents)
    chunk_ids = tuple(document.chunk_id for document in documents)
    chunk_digest = index_chunk_ids_fingerprint(chunk_ids)
    async with sessions.begin() as session:
        await lock_stage(session)
        build = await _lock_build(session, build_id)
        repository = SqlAlchemyRagIndexRepository(session)
        resource = await repository.get(build_id)
        if resource is None:
            raise IndexTrackingError("rag_index_inventory_incomplete")
        require_registered_configuration(resource, settings)
        reusable = build.status in {"prepared", "ready"}
        if reusable:
            await _require_closed(session, build_id)
            if (
                resource.input_fingerprint != fingerprint
                or resource.chunk_ids_sha256 != chunk_digest
            ):
                raise IndexTrackingError("rag_index_input_conflict")
            claim = None
        else:
            if build.status != "building":
                raise IndexTrackingError("rag_index_identity_conflict")
            claim = await repository.reserve(build_id, fingerprint, chunk_ids_sha256=chunk_digest)
            resource = claim.resource

    async def on_identity(index_uuid: str) -> None:
        nonlocal claim
        if claim is None:
            raise IndexTrackingError("rag_index_identity_conflict")
        async with sessions.begin() as session:
            await lock_stage(session)
            await _lock_build(session, build_id)
            claim = await SqlAlchemyRagIndexRepository(session).observe_uuid(claim, index_uuid)

    # A failed final commit leaves the previously committed open attempt visible.
    # No catch block tries to infer server termination or claim ownership from age.
    try:
        async with adapters() as adapter:
            observation = (
                await adapter.observe(resource, chunk_ids)
                if reusable
                else await adapter.prepare(resource, documents, on_identity)
            )
        if (
            not observation.exists
            or observation.index_uuid is None
            or observation.chunk_count != len(documents)
            or any(alias != resource.alias for alias in observation.aliases)
        ):
            raise IndexTrackingError("rag_index_identity_conflict")
        if reusable:
            if observation.index_uuid != resource.index_uuid:
                raise IndexTrackingError("rag_index_identity_conflict")
            return
        if claim is None or claim.resource.index_uuid != observation.index_uuid:
            raise IndexTrackingError("rag_index_identity_conflict")
        async with sessions.begin() as session:
            await lock_stage(session)
            build = await _lock_build(session, build_id)
            if build.status != "building":
                raise IndexTrackingError("rag_index_identity_conflict")
            build.index_name = resource.index_name
            build.expected_document_count = len(documents)
            build.indexed_document_count = observation.chunk_count
            build.vector_dimension = resource.vector_dimension
            build.status = "prepared"
            await SqlAlchemyRagIndexRepository(session).finish(claim, "prepared")
            await session.flush()
    except IndexPreparationFailed as error:
        if claim is not None and error.writer_confirmed_ended:
            try:
                async with sessions.begin() as session:
                    await lock_stage(session)
                    await _lock_build(session, build_id)
                    await SqlAlchemyRagIndexRepository(session).finish(claim, error.code)
            except Exception:
                # Failure to commit the closure cannot authorize another writer.
                raise IndexTrackingError("rag_index_writer_unconfirmed") from None
        raise
    except SQLAlchemyError:
        raise IndexTrackingError("rag_index_writer_unconfirmed") from None


async def validate_tracked_targets(
    session: AsyncSession,
    settings: Settings,
    builds: Sequence[RagIndexBuildRecord],
    adapters: TrackedIndexSession,
    *,
    require_alias_parity: bool = False,
) -> None:
    """Caller holds every build lock before entering resource/physical validation."""
    resources = []
    for build in sorted(builds, key=lambda item: str(item.id)):
        resource = await SqlAlchemyRagIndexRepository(session).get(build.id)
        if resource is None:
            continue  # Legacy keeps its existing activation contract, never backfilled.
        require_registered_configuration(resource, settings)
        await _require_closed(session, build.id)
        if (
            resource.index_uuid is None
            or resource.index_name != build.index_name
            or resource.projection_id != build.projection_id
            or resource.vector_dimension != build.vector_dimension
        ):
            raise IndexTrackingError("rag_index_identity_conflict")
        ids = tuple(
            await session.scalars(
                select(RetrievalChunkRecord.id)
                .where(
                    RetrievalChunkRecord.projection_id == build.projection_id,
                )
                .order_by(RetrievalChunkRecord.id)
            )
        )
        if resource.chunk_ids_sha256 != index_chunk_ids_fingerprint(ids):
            raise IndexTrackingError("rag_index_input_conflict")
        resources.append((resource, ids, build.is_active))
    if not resources:
        return
    async with adapters() as adapter:
        for resource, ids, active in resources:
            observation = await adapter.observe(resource, ids)
            if (
                not observation.exists
                or observation.index_uuid != resource.index_uuid
                or observation.chunk_count != len(ids)
                or any(alias != resource.alias for alias in observation.aliases)
            ):
                raise IndexTrackingError("rag_index_identity_conflict")
            if require_alias_parity and ((resource.alias in observation.aliases) != active):
                raise IndexTrackingError("rag_index_identity_conflict")
