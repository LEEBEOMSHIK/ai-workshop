import hashlib
import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from elastic_transport import (
    ApiError,
    ConnectionTimeout,
)
from elastic_transport import (
    ConnectionError as ElasticsearchConnectionError,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.config import Settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.chunking.contracts import ChunkingResult
from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.labs.rag.documents.models import (
    RagIndexBuildRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
)
from ai_workshop.labs.rag.documents.repository import SqlAlchemyRagDocumentRepository
from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingDescriptor,
    EmbeddingModelConfig,
    EmbeddingPort,
    EmbeddingResult,
    EmbeddingValidationError,
    EmbeddingVector,
)
from ai_workshop.labs.rag.embeddings.sentence_transformers import (
    SentenceTransformerEmbedding,
)
from ai_workshop.labs.rag.indexing.contracts import (
    IndexDescriptor,
    IndexDocument,
    SearchIndexPort,
)
from ai_workshop.labs.rag.indexing.elasticsearch import ElasticsearchSearchIndex
from ai_workshop.labs.rag.indexing.service import (
    ActiveAliasTargetMismatchError,
    AliasActivationNotAcknowledgedError,
    IndexingResult,
    IndexingService,
)
from ai_workshop.labs.rag.ingestion.domain import (
    ArtifactReference,
    RagIngestionError,
    ReadinessVerification,
)
from ai_workshop.labs.rag.ingestion.locking import lock_ingestion_source
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.ingestion.serialization import (
    deserialize_chunking_result,
    deserialize_embedding_result,
    serialize_embedding_result,
)
from ai_workshop.labs.rag.models.models import (
    ModelDefinitionRecord,
    ProfileModelBindingRecord,
    ProfileRecord,
)
from ai_workshop.labs.rag.models.repository import _model_to_domain
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.jobs.domain import JobStatus
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.shared.db import create_engine, create_session_factory


def _classify_activation_error(exc: Exception) -> RagIngestionError:
    if isinstance(
        exc,
        (
            AliasActivationNotAcknowledgedError,
            ElasticsearchConnectionError,
            ConnectionTimeout,
        ),
    ):
        return RagIngestionError(
            "index_activation_failed",
            "The prepared index alias activation failed transiently.",
            retryable=True,
        )
    if isinstance(exc, ApiError):
        retryable = exc.meta.status == 429 or exc.meta.status >= 500
        return RagIngestionError(
            "index_activation_failed" if retryable else "index_activation_rejected",
            (
                "The prepared index alias activation failed transiently."
                if retryable
                else "Elasticsearch rejected the prepared alias activation."
            ),
            retryable=retryable,
        )
    if isinstance(exc, ActiveAliasTargetMismatchError):
        return RagIngestionError(
            "index_activation_rejected",
            "The prepared index alias failed deterministic validation.",
            retryable=False,
        )
    raise exc


def embed_chunks(
    chunks: ChunkingResult,
    *,
    embedding: EmbeddingPort,
    descriptor: EmbeddingDescriptor,
) -> EmbeddingResult:
    if embedding.dimension != descriptor.dimension:
        raise EmbeddingValidationError(
            "The embedding port dimension does not match the immutable descriptor dimension."
        )
    for chunk in chunks.chunks:
        if chunk.projection_id != descriptor.projection_id:
            raise EmbeddingValidationError(
                "Every authoritative chunk must belong to the embedding projection."
            )
        if embedding.count_tokens(chunk.text) > descriptor.max_tokens:
            raise EmbeddingValidationError(
                f"Chunk {chunk.id} exceeds the selected model token limit."
            )
    values = embedding.encode_documents([chunk.text for chunk in chunks.chunks])
    if len(values) != len(chunks.chunks):
        raise EmbeddingValidationError(
            "The embedding output count does not match the authoritative chunk count."
        )
    return EmbeddingResult(
        descriptor,
        tuple(
            EmbeddingVector(chunk.id, tuple(float(value) for value in vector))
            for chunk, vector in zip(chunks.chunks, values, strict=True)
        ),
    )


def validate_indexing_inputs(
    chunks: ChunkingResult,
    embeddings: EmbeddingResult,
    *,
    expected_descriptor: EmbeddingDescriptor,
) -> None:
    if embeddings.descriptor != expected_descriptor:
        raise EmbeddingValidationError(
            "The embedding artifact descriptor no longer matches the immutable "
            "model/profile descriptor."
        )
    chunk_ids = tuple(chunk.id for chunk in chunks.chunks)
    vector_ids = tuple(vector.chunk_id for vector in embeddings.vectors)
    if chunk_ids != vector_ids:
        raise EmbeddingValidationError(
            "The authoritative chunk and embedding IDs must have exact one-to-one order."
        )


type EmbeddingFactory = Callable[[EmbeddingModelConfig, Path], EmbeddingPort]
type SearchIndexSession = Callable[[], AbstractAsyncContextManager[SearchIndexPort]]


@dataclass(frozen=True, slots=True)
class _ResolvedEmbedding:
    config: EmbeddingModelConfig
    descriptor: EmbeddingDescriptor


@dataclass(frozen=True, slots=True)
class _IndexSource:
    asset_version_id: UUID
    workspace_id: UUID
    folder_id: UUID | None
    title: str
    allowed_user_ids: tuple[UUID, ...]


async def _lock_active_stage_rows(
    session: AsyncSession,
    projection_id: UUID,
) -> tuple[RagIngestionJobRecord, RagProjectionRecord]:
    """Lock ingestion -> Job -> Projection -> AssetVersion -> Document."""
    ingestion = await session.scalar(
        select(RagIngestionJobRecord)
        .where(RagIngestionJobRecord.projection_id == projection_id)
        .with_for_update()
    )
    if ingestion is None:
        raise RagIngestionError(
            "ingestion_job_not_found",
            "The durable RAG ingestion job does not exist.",
            retryable=False,
        )
    job = await SqlAlchemyJobRepository(session).find_by_id_for_update(ingestion.job_id)
    projection = await session.scalar(
        select(RagProjectionRecord)
        .where(RagProjectionRecord.id == projection_id)
        .with_for_update()
    )
    if job is None or projection is None:
        raise RagIngestionError(
            "ingestion_dependency_missing",
            "A durable RAG ingestion dependency is missing.",
            retryable=False,
        )
    await lock_ingestion_source(session, ingestion.asset_version_id)
    return ingestion, projection


def _canonical_hash(value: object) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(content).hexdigest()


async def _resolve_embedding(
    session: AsyncSession,
    *,
    projection_id: UUID,
    indexing_profile_id: UUID,
) -> _ResolvedEmbedding:
    profile = await session.get(ProfileRecord, indexing_profile_id)
    if profile is None or profile.kind != "indexing":
        raise RagIngestionError(
            "indexing_profile_missing",
            "The immutable indexing profile does not exist.",
            retryable=False,
        )
    binding_rows = list(
        await session.scalars(
            select(ProfileModelBindingRecord).where(
                ProfileModelBindingRecord.profile_id == indexing_profile_id,
                ProfileModelBindingRecord.role == "embedding",
            )
        )
    )
    if len(binding_rows) != 1:
        raise RagIngestionError(
            "embedding_binding_invalid",
            "An indexing profile requires exactly one embedding model binding.",
            retryable=False,
        )
    model_record = await session.get(ModelDefinitionRecord, binding_rows[0].model_id)
    if model_record is None:
        raise RagIngestionError(
            "embedding_model_missing",
            "The immutable embedding model definition does not exist.",
            retryable=False,
        )
    embedding_profile = profile.config.get("embedding")
    if not isinstance(embedding_profile, dict):
        raise RagIngestionError(
            "embedding_profile_invalid",
            "The indexing profile must declare embedding batch_size and similarity.",
            retryable=False,
        )
    if embedding_profile.get("similarity") != "cosine":
        raise RagIngestionError(
            "embedding_profile_invalid",
            "The first dense projection requires cosine similarity.",
            retryable=False,
        )
    try:
        model = _model_to_domain(model_record)
        config = EmbeddingModelConfig.from_definition(
            model,
            profile_config=cast(dict[str, object], embedding_profile),
        )
    except EmbeddingValidationError as exc:
        raise RagIngestionError(
            "embedding_model_invalid", str(exc), retryable=False
        ) from exc
    return _ResolvedEmbedding(
        config,
        EmbeddingDescriptor(
            projection_id=projection_id,
            indexing_profile_id=indexing_profile_id,
            model_definition_id=model.id,
            model_revision=config.revision,
            model_config_sha256=_canonical_hash(model_record.config),
            profile_config_sha256=_canonical_hash(profile.config),
            dimension=config.dimension,
            max_tokens=config.max_tokens,
            normalize=config.normalize,
            output_mode=config.output_mode,
        ),
    )


async def _read_artifact(
    store: LocalObjectStore, reference: ArtifactReference
) -> bytes:
    try:
        content = b"".join([part async for part in store.open(reference.key)])
    except OSError as exc:
        raise RagIngestionError(
            "artifact_readback_failed",
            "The immutable RAG artifact could not be read from its exact key.",
            retryable=True,
        ) from exc
    if hashlib.sha256(content).hexdigest() != reference.sha256:
        raise RagIngestionError(
            "artifact_checksum_mismatch",
            "The immutable RAG artifact no longer matches its recorded digest.",
            retryable=False,
        )
    return content


async def _publish_embedding(
    store: LocalObjectStore, key: str, content: bytes
) -> tuple[ArtifactReference, EmbeddingResult]:
    try:
        stored = await store.put_if_absent(key, _bytes_source(content))
        authoritative = b"".join([part async for part in store.open(key)])
    except OSError as exc:
        raise RagIngestionError(
            "embedding_artifact_publication_failed",
            "The immutable embedding artifact could not be published and read back.",
            retryable=True,
        ) from exc
    digest = hashlib.sha256(authoritative).hexdigest()
    if stored.key != key or stored.size != len(authoritative) or stored.sha256 != digest:
        raise RagIngestionError(
            "embedding_artifact_readback_mismatch",
            "The immutable embedding artifact metadata does not match its bytes.",
            retryable=False,
        )
    try:
        return ArtifactReference(key, digest), deserialize_embedding_result(authoritative)
    except (KeyError, TypeError, ValueError) as exc:
        raise RagIngestionError(
            "embedding_artifact_invalid",
            "The immutable embedding artifact payload is invalid.",
            retryable=False,
        ) from exc


def _default_embedding_factory(
    config: EmbeddingModelConfig, cache_folder: Path
) -> EmbeddingPort:
    return SentenceTransformerEmbedding(
        config,
        cache_folder=cache_folder,
        local_files_only=True,
    )


class ProductionEmbeddingStage:
    def __init__(
        self,
        settings: Settings,
        object_store: LocalObjectStore,
        *,
        embedding_factory: EmbeddingFactory = _default_embedding_factory,
    ) -> None:
        self.settings = settings
        self.object_store = object_store
        self.embedding_factory = embedding_factory

    async def embed(self, *, projection_id: UUID, indexing_profile_id: UUID) -> int:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions() as session:
                ingestion = await session.scalar(
                    select(RagIngestionJobRecord).where(
                        RagIngestionJobRecord.projection_id == projection_id
                    )
                )
                projection = await session.get(RagProjectionRecord, projection_id)
                if (
                    ingestion is None
                    or projection is None
                    or projection.status != ProjectionStatus.EMBEDDING
                    or ingestion.indexing_profile_id != indexing_profile_id
                ):
                    raise RagIngestionError(
                        "embedding_stage_conflict",
                        "Embedding can run only for the selected persisted projection stage.",
                        retryable=False,
                    )
                chunk_reference = _artifact_reference(
                    ingestion.chunk_object_key, ingestion.chunk_sha256
                )
                rows = list(
                    await session.scalars(
                        select(RetrievalChunkRecord)
                        .where(RetrievalChunkRecord.projection_id == projection_id)
                        .order_by(RetrievalChunkRecord.ordinal)
                    )
                )
                resolved = await _resolve_embedding(
                    session,
                    projection_id=projection_id,
                    indexing_profile_id=indexing_profile_id,
                )
            try:
                chunks = deserialize_chunking_result(
                    await _read_artifact(self.object_store, chunk_reference)
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RagIngestionError(
                    "chunk_artifact_invalid",
                    "The authoritative chunk artifact is invalid.",
                    retryable=False,
                ) from exc
            persisted = tuple((row.id, row.ordinal, row.text) for row in rows)
            authoritative = tuple(
                (chunk.id, chunk.ordinal, chunk.text) for chunk in chunks.chunks
            )
            if persisted != authoritative:
                raise RagIngestionError(
                    "chunk_artifact_mismatch",
                    "Persisted chunks must exactly match the authoritative chunk artifact.",
                    retryable=False,
                )
            try:
                result = embed_chunks(
                    chunks,
                    embedding=self.embedding_factory(
                        resolved.config, self.settings.model_cache_root
                    ),
                    descriptor=resolved.descriptor,
                )
            except EmbeddingValidationError as exc:
                raise RagIngestionError(
                    "embedding_output_invalid", str(exc), retryable=False
                ) from exc
            reference, authoritative_result = await _publish_embedding(
                self.object_store,
                f"rag/embeddings/{projection_id}.json",
                serialize_embedding_result(result),
            )
            if authoritative_result.descriptor != resolved.descriptor:
                raise RagIngestionError(
                    "embedding_artifact_descriptor_mismatch",
                    "The authoritative vectors use another model or profile descriptor.",
                    retryable=False,
                )
            validate_indexing_inputs(
                chunks,
                authoritative_result,
                expected_descriptor=resolved.descriptor,
            )
            async with sessions.begin() as session:
                ingestion, _projection = await _lock_active_stage_rows(
                    session, projection_id
                )
                current = await _resolve_embedding(
                    session,
                    projection_id=projection_id,
                    indexing_profile_id=indexing_profile_id,
                )
                if current.descriptor != authoritative_result.descriptor:
                    raise RagIngestionError(
                        "embedding_artifact_descriptor_mismatch",
                        "The selected immutable model/profile descriptor changed.",
                        retryable=False,
                    )
                existing = (ingestion.embedding_object_key, ingestion.embedding_sha256)
                if existing != (None, None) and existing != (reference.key, reference.sha256):
                    raise RagIngestionError(
                        "embedding_artifact_conflict",
                        "Another immutable embedding artifact is already recorded.",
                        retryable=False,
                    )
                ingestion.embedding_object_key = reference.key
                ingestion.embedding_sha256 = reference.sha256
                ingestion.embedding_count = len(authoritative_result.vectors)
                await session.flush()
            return len(authoritative_result.vectors)
        finally:
            await engine.dispose()


@asynccontextmanager
async def _elasticsearch_session(settings: Settings) -> AsyncIterator[SearchIndexPort]:
    client = create_elasticsearch(settings)
    try:
        yield ElasticsearchSearchIndex(client)
    finally:
        await client.close()


class ProductionIndexingStage:
    def __init__(
        self,
        settings: Settings,
        object_store: LocalObjectStore,
        *,
        search_index_session: SearchIndexSession | None = None,
    ) -> None:
        self.settings = settings
        self.object_store = object_store
        self.search_index_session = search_index_session or (
            lambda: _elasticsearch_session(settings)
        )

    async def index(self, *, projection_id: UUID, indexing_profile_id: UUID) -> None:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            build_id = await self._ensure_build(sessions, projection_id, indexing_profile_id)
            async with sessions() as session:
                ingestion = await session.scalar(
                    select(RagIngestionJobRecord).where(
                        RagIngestionJobRecord.projection_id == projection_id
                    )
                )
                if ingestion is None or ingestion.index_build_id != build_id:
                    raise RagIngestionError(
                        "index_build_conflict",
                        "The durable index build identity is missing.",
                        retryable=False,
                    )
                chunk_reference = _artifact_reference(
                    ingestion.chunk_object_key, ingestion.chunk_sha256
                )
                embedding_reference = _artifact_reference(
                    ingestion.embedding_object_key, ingestion.embedding_sha256
                )
                resolved = await _resolve_embedding(
                    session,
                    projection_id=projection_id,
                    indexing_profile_id=indexing_profile_id,
                )
                source = await _load_index_source(session, ingestion.asset_version_id)
                persisted_chunks = list(
                    await session.scalars(
                        select(RetrievalChunkRecord)
                        .where(RetrievalChunkRecord.projection_id == projection_id)
                        .order_by(RetrievalChunkRecord.ordinal)
                    )
                )
            try:
                chunks = deserialize_chunking_result(
                    await _read_artifact(self.object_store, chunk_reference)
                )
                embeddings = deserialize_embedding_result(
                    await _read_artifact(self.object_store, embedding_reference)
                )
                validate_indexing_inputs(
                    chunks, embeddings, expected_descriptor=resolved.descriptor
                )
            except EmbeddingValidationError as exc:
                raise RagIngestionError(
                    "indexing_input_mismatch", str(exc), retryable=False
                ) from exc
            except (KeyError, TypeError, ValueError) as exc:
                raise RagIngestionError(
                    "indexing_artifact_invalid",
                    "The authoritative chunk or embedding artifact is invalid.",
                    retryable=False,
                ) from exc
            authoritative_chunk_count = len(chunks.chunks)
            authoritative_embedding_count = len(embeddings.vectors)
            if not (
                ingestion.chunk_count
                == ingestion.embedding_count
                == authoritative_chunk_count
                == authoritative_embedding_count
                and authoritative_chunk_count > 0
            ):
                raise RagIngestionError(
                    "indexing_input_mismatch",
                    "Persisted and authoritative chunk/vector counts must match and be positive.",
                    retryable=False,
                )
            persisted = tuple(
                (row.id, row.ordinal, row.text, tuple(row.section_path))
                for row in persisted_chunks
            )
            authoritative = tuple(
                (chunk.id, chunk.ordinal, chunk.text, chunk.section_path)
                for chunk in chunks.chunks
            )
            if persisted != authoritative:
                raise RagIngestionError(
                    "indexing_input_mismatch",
                    "Persisted chunks do not match the authoritative chunk artifact.",
                    retryable=False,
                )
            documents = tuple(
                IndexDocument(
                    chunk_id=chunk.id,
                    projection_id=projection_id,
                    asset_version_id=source.asset_version_id,
                    workspace_id=source.workspace_id,
                    folder_id=source.folder_id,
                    allowed_user_ids=source.allowed_user_ids,
                    status="ready",
                    title=source.title,
                    section_path=chunk.section_path,
                    text=chunk.text,
                    evidence_units=chunk.evidence_units,
                    embedding=vector.values,
                    index_build_id=build_id,
                )
                for chunk, vector in zip(chunks.chunks, embeddings.vectors, strict=True)
            )
            descriptor = IndexDescriptor(resolved.config.dimension, "cosine")
            async with self.search_index_session() as search_index:
                prepared = await IndexingService(
                    search_index,
                    index_prefix=self.settings.elasticsearch_index_prefix,
                ).prepare_projection(
                    descriptor=descriptor,
                    profile_id=indexing_profile_id,
                    build_id=build_id,
                    projection_id=projection_id,
                    expected_chunk_count=len(chunks.chunks),
                    documents=documents,
                )
            async with sessions.begin() as session:
                ingestion, _projection = await _lock_active_stage_rows(
                    session, projection_id
                )
                build = await session.scalar(
                    select(RagIndexBuildRecord)
                    .where(RagIndexBuildRecord.id == build_id)
                    .with_for_update()
                )
                if build is None or ingestion is None or ingestion.index_build_id != build.id:
                    raise RagIngestionError(
                        "index_build_conflict",
                        "The immutable prepared index build no longer matches the job.",
                        retryable=False,
                    )
                build.index_name = prepared.index_name
                build.expected_document_count = len(chunks.chunks)
                build.indexed_document_count = prepared.indexed_document_count
                build.vector_dimension = descriptor.vector_dimension
                build.status = "prepared"
                await session.flush()
        finally:
            await engine.dispose()

    async def _ensure_build(
        self,
        sessions: async_sessionmaker[AsyncSession],
        projection_id: UUID,
        indexing_profile_id: UUID,
    ) -> UUID:
        async with sessions.begin() as session:
            ingestion, projection = await _lock_active_stage_rows(
                session, projection_id
            )
            if (
                projection.status != ProjectionStatus.INDEXING
                or ingestion.indexing_profile_id != indexing_profile_id
            ):
                raise RagIngestionError(
                    "indexing_stage_conflict",
                    "Indexing can run only for the selected persisted projection stage.",
                    retryable=False,
                )
            if ingestion.embedding_count is None or ingestion.embedding_count < 1:
                raise RagIngestionError(
                    "embedding_artifact_missing",
                    "Indexing requires a completed durable embedding artifact.",
                    retryable=False,
                )
            build = await session.scalar(
                select(RagIndexBuildRecord).where(
                    RagIndexBuildRecord.projection_id == projection_id
                )
            )
            if build is None:
                build = RagIndexBuildRecord(
                    id=uuid4(),
                    projection_id=projection_id,
                    indexing_profile_id=indexing_profile_id,
                    index_name=None,
                    expected_document_count=None,
                    indexed_document_count=None,
                    vector_dimension=None,
                    status="building",
                    is_active=False,
                )
                session.add(build)
                await session.flush()
            elif build.indexing_profile_id != indexing_profile_id:
                raise RagIngestionError(
                    "index_build_conflict",
                    "An index build cannot change its immutable profile.",
                    retryable=False,
                )
            if ingestion.index_build_id not in {None, build.id}:
                raise RagIngestionError(
                    "index_build_conflict",
                    "An ingestion job cannot change its immutable index build.",
                    retryable=False,
                )
            ingestion.index_build_id = build.id
            await session.flush()
            return build.id


class ProductionReadinessVerifier:
    def __init__(
        self,
        settings: Settings,
        *,
        search_index_session: SearchIndexSession | None = None,
    ) -> None:
        self.settings = settings
        self.search_index_session = search_index_session or (
            lambda: _elasticsearch_session(settings)
        )

    async def verify(
        self, *, projection_id: UUID, indexing_profile_id: UUID
    ) -> ReadinessVerification:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions.begin() as session:
                ingestion = await session.scalar(
                    select(RagIngestionJobRecord)
                    .where(RagIngestionJobRecord.projection_id == projection_id)
                    .with_for_update()
                )
                if ingestion is None or ingestion.index_build_id is None:
                    raise RagIngestionError(
                        "index_build_conflict",
                        "The final activation requires a durable prepared build.",
                        retryable=False,
                    )
                job = await SqlAlchemyJobRepository(session).find_by_id_for_update(
                    ingestion.job_id
                )
                projection = await session.scalar(
                    select(RagProjectionRecord)
                    .where(RagProjectionRecord.id == projection_id)
                    .with_for_update()
                )
                if (
                    projection is None
                    or projection.indexing_profile_id != indexing_profile_id
                    or job is None
                ):
                    raise RagIngestionError(
                        "indexing_stage_conflict",
                        "The prepared projection does not match its indexing profile.",
                        retryable=False,
                    )
                if projection.status not in {
                    ProjectionStatus.INDEXING,
                    ProjectionStatus.READY,
                }:
                    raise RagIngestionError(
                        "indexing_stage_conflict",
                        "The final activation requires an INDEXING or READY projection.",
                        retryable=False,
                    )
                await lock_ingestion_source(
                    session,
                    projection.asset_version_id,
                    require_active=projection.status != ProjectionStatus.READY,
                )
                profile = await session.scalar(
                    select(ProfileRecord)
                    .where(ProfileRecord.id == indexing_profile_id)
                    .with_for_update()
                )
                if profile is None:
                    raise RagIngestionError(
                        "indexing_profile_missing",
                        "The final activation lock profile does not exist.",
                        retryable=False,
                    )
                build = await session.scalar(
                    select(RagIndexBuildRecord)
                    .where(RagIndexBuildRecord.id == ingestion.index_build_id)
                    .with_for_update()
                )
                resolved = await _resolve_embedding(
                    session,
                    projection_id=projection_id,
                    indexing_profile_id=indexing_profile_id,
                )
                if (
                    build is None
                    or build.projection_id != projection_id
                    or build.indexing_profile_id != indexing_profile_id
                    or build.status not in {"prepared", "ready"}
                    or build.index_name is None
                    or build.expected_document_count is None
                    or build.indexed_document_count is None
                    or build.vector_dimension != resolved.config.dimension
                ):
                    raise RagIngestionError(
                        "index_build_incomplete",
                        "The final activation requires a fully prepared immutable build.",
                        retryable=False,
                    )
                verification = ReadinessVerification(
                    parsed_element_count=ingestion.parsed_element_count or 0,
                    chunk_count=ingestion.chunk_count or 0,
                    embedding_count=ingestion.embedding_count or 0,
                    indexed_document_count=build.indexed_document_count,
                    alias_verified=True,
                )
                if (
                    not verification.is_complete
                    or build.expected_document_count != verification.chunk_count
                ):
                    raise RagIngestionError(
                        "readiness_verification_failed",
                        "Persisted stage and prepared index counts do not match.",
                        retryable=False,
                    )
                if projection.status == ProjectionStatus.READY:
                    return verification
                active_rows = (
                    await session.execute(
                        select(
                            RagIndexBuildRecord,
                            RagProjectionRecord,
                            AssetVersionRecord,
                            DocumentRecord,
                        )
                        .join(
                            RagProjectionRecord,
                            RagProjectionRecord.id == RagIndexBuildRecord.projection_id,
                        )
                        .join(
                            AssetVersionRecord,
                            AssetVersionRecord.id == RagProjectionRecord.asset_version_id,
                        )
                        .join(
                            DocumentRecord,
                            DocumentRecord.id == AssetVersionRecord.document_id,
                        )
                        .where(
                            RagIndexBuildRecord.indexing_profile_id
                            == indexing_profile_id,
                            RagProjectionRecord.indexing_profile_id
                            == indexing_profile_id,
                            RagIndexBuildRecord.status == "ready",
                            RagProjectionRecord.status == ProjectionStatus.READY,
                            AssetVersionRecord.status == VersionStatus.READY,
                            DocumentRecord.active_version_id == AssetVersionRecord.id,
                        )
                        .order_by(RagIndexBuildRecord.id)
                    )
                ).all()
                target_builds = {candidate.id: candidate for candidate, *_ in active_rows}
                target_builds[build.id] = build
                descriptor = IndexDescriptor(build.vector_dimension, "cosine")
                intended_targets: list[str] = []
                for candidate in target_builds.values():
                    expected_name = descriptor.concrete_index_name(
                        self.settings.elasticsearch_index_prefix,
                        indexing_profile_id,
                        candidate.id,
                    )
                    if (
                        candidate.indexing_profile_id != indexing_profile_id
                        or candidate.status not in {"prepared", "ready"}
                        or candidate.index_name != expected_name
                        or candidate.vector_dimension != build.vector_dimension
                    ):
                        raise RagIngestionError(
                            "index_build_incomplete",
                            "Every active build must match the exact profile index descriptor.",
                            retryable=False,
                        )
                    intended_targets.append(expected_name)
                prepared = IndexingResult(
                    descriptor=descriptor,
                    profile_id=indexing_profile_id,
                    build_id=build.id,
                    projection_id=projection_id,
                    index_name=build.index_name,
                    alias=descriptor.active_alias(
                        self.settings.elasticsearch_index_prefix, indexing_profile_id
                    ),
                    indexed_document_count=build.indexed_document_count,
                    alias_verified=False,
                )
                try:
                    async with self.search_index_session() as search_index:
                        activated = await IndexingService(
                            search_index,
                            index_prefix=self.settings.elasticsearch_index_prefix,
                        ).activate_prepared(
                            prepared,
                            intended_targets=intended_targets,
                        )
                except (
                    ActiveAliasTargetMismatchError,
                    AliasActivationNotAcknowledgedError,
                    ElasticsearchConnectionError,
                    ConnectionTimeout,
                    ApiError,
                ) as exc:
                    raise _classify_activation_error(exc) from exc
                if not activated.alias_verified:
                    raise RagIngestionError(
                        "index_activation_failed",
                        "The prepared index alias target set was not exactly verified.",
                        retryable=True,
                    )
                target_build_ids = tuple(target_builds)
                await session.execute(
                    update(RagIndexBuildRecord)
                    .where(
                        RagIndexBuildRecord.indexing_profile_id == indexing_profile_id,
                    )
                    .values(is_active=RagIndexBuildRecord.id.in_(target_build_ids))
                )
                build.status = "ready"
                ingestion.indexed_document_count = build.indexed_document_count
                ingestion.index_alias_verified = True
                await SqlAlchemyRagDocumentRepository(session).mark_status(
                    projection_id, ProjectionStatus.READY
                )
                if job.status is JobStatus.RUNNING:
                    job.succeed(stage=ProjectionStatus.READY.value)
                    await SqlAlchemyJobRepository(session).update(job)
                await session.flush()
                return verification
        finally:
            await engine.dispose()


async def _load_index_source(
    session: AsyncSession, asset_version_id: UUID
) -> _IndexSource:
    asset = await session.get(AssetVersionRecord, asset_version_id)
    if asset is None:
        raise RagIngestionError(
            "ingestion_dependency_missing", "The indexed asset does not exist.", retryable=False
        )
    document = await session.get(DocumentRecord, asset.document_id)
    if document is None:
        raise RagIngestionError(
            "ingestion_dependency_missing",
            "The indexed document does not exist.",
            retryable=False,
        )
    workspace = await session.get(WorkspaceRecord, document.workspace_id)
    if workspace is None:
        raise RagIngestionError(
            "ingestion_dependency_missing",
            "The indexed workspace does not exist.",
            retryable=False,
        )
    members = set(
        await session.scalars(
            select(WorkspaceMembershipRecord.user_id).where(
                WorkspaceMembershipRecord.workspace_id == workspace.id
            )
        )
    )
    members.add(workspace.created_by)
    return _IndexSource(
        asset_version_id=asset.id,
        workspace_id=workspace.id,
        folder_id=document.folder_id,
        title=document.name,
        allowed_user_ids=tuple(sorted(members, key=str)),
    )


def _artifact_reference(key: str | None, sha256: str | None) -> ArtifactReference:
    if key is None or sha256 is None:
        raise RagIngestionError(
            "artifact_reference_incomplete",
            "A durable RAG artifact reference is incomplete.",
            retryable=False,
        )
    return ArtifactReference(key, sha256)


async def _bytes_source(content: bytes) -> AsyncIterator[bytes]:
    yield content
