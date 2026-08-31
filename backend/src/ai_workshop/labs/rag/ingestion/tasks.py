from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.labs.rag.chunking import ChunkingConfig
from ai_workshop.labs.rag.chunking.contracts import ChunkingResult
from ai_workshop.labs.rag.documents.domain import (
    ParsedDocument,
    ProjectionStatus,
)
from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.labs.rag.documents.repository import SqlAlchemyRagDocumentRepository
from ai_workshop.labs.rag.ingestion.domain import (
    ArtifactReference,
    IngestionExecution,
    RagIngestionError,
    ReadinessVerification,
)
from ai_workshop.labs.rag.ingestion.locking import lock_ingestion_source
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.ingestion.service import RagIngestionWorkflow
from ai_workshop.labs.rag.ingestion.stages import (
    EmbeddingRuntimeProvider,
    ProductionChunkingStage,
    ProductionEmbeddingStage,
    ProductionIndexingStage,
    ProductionReadinessVerifier,
)
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.labs.rag.parsing.markdown import MarkdownParser
from ai_workshop.labs.rag.parsing.pdf import PdfParser
from ai_workshop.labs.rag.parsing.plain_text import PlainTextParser
from ai_workshop.labs.rag.parsing.registry import ParserRegistry
from ai_workshop.labs.rag.parsing.service import ParsingService
from ai_workshop.platform.assets.domain import AssetVersion, VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.jobs.domain import Job, JobStatus
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository
from ai_workshop.shared.db import create_engine, create_session_factory


@dataclass(frozen=True, slots=True)
class _IngestionRows:
    ingestion: RagIngestionJobRecord
    projection: RagProjectionRecord
    asset: AssetVersionRecord
    document: DocumentRecord
    profile: ProfileRecord
    job: Job


class SqlAlchemyRagIngestionLifecycle:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def begin(self, job_id: UUID) -> IngestionExecution:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions.begin() as session:
                rows = await self._load(session, job_id, lock=True)
                self._require_active_source(rows)
                documents = SqlAlchemyRagDocumentRepository(session)
                jobs = SqlAlchemyJobRepository(session)
                if rows.projection.status == ProjectionStatus.PENDING:
                    if rows.job.status is not JobStatus.QUEUED:
                        raise RagIngestionError(
                            "ingestion_state_inconsistent",
                            "A pending projection requires a queued job.",
                            retryable=False,
                        )
                    rows.job.start(stage=ProjectionStatus.PARSING.value)
                    await jobs.update(rows.job)
                    await documents.mark_status(rows.projection.id, ProjectionStatus.PARSING)
                    rows.projection.status = ProjectionStatus.PARSING
                elif rows.projection.status is ProjectionStatus.READY:
                    if rows.job.status is JobStatus.RUNNING:
                        rows.job.succeed(stage=ProjectionStatus.READY.value)
                        await jobs.update(rows.job)
                    elif rows.job.status is JobStatus.QUEUED:
                        rows.job.start(stage=ProjectionStatus.READY.value)
                        rows.job.succeed(stage=ProjectionStatus.READY.value)
                        await jobs.update(rows.job)
                elif rows.projection.status is ProjectionStatus.FAILED:
                    if rows.job.status is not JobStatus.FAILED:
                        raise RagIngestionError(
                            "ingestion_state_inconsistent",
                            "A failed projection requires a failed job.",
                            retryable=False,
                        )
                elif rows.job.status is JobStatus.QUEUED:
                    rows.job.start(stage=ProjectionStatus(rows.projection.status).value)
                    await jobs.update(rows.job)
                elif rows.job.status is not JobStatus.RUNNING:
                    raise RagIngestionError(
                        "ingestion_state_inconsistent",
                        "An active projection requires a running job.",
                        retryable=False,
                    )
                return self._execution(rows)
        finally:
            await engine.dispose()

    async def complete_parsing(
        self,
        job_id: UUID,
        document: ParsedDocument,
        artifact: ArtifactReference,
    ) -> IngestionExecution:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions.begin() as session:
                rows = await self._load(session, job_id, lock=True)
                self._require_active_source(rows)
                if rows.projection.status is not ProjectionStatus.PARSING:
                    return self._require_completed_stage(rows, ProjectionStatus.CHUNKING)
                await SqlAlchemyRagDocumentRepository(session).save_parsed_document(
                    rows.projection.id, document
                )
                rows.ingestion.parsed_object_key = artifact.key
                rows.ingestion.parsed_sha256 = artifact.sha256
                rows.ingestion.parsed_element_count = len(document.elements)
                await self._advance(session, rows, ProjectionStatus.CHUNKING)
                return self._execution(rows)
        finally:
            await engine.dispose()

    async def complete_chunking(
        self,
        job_id: UUID,
        result: ChunkingResult,
        artifact: ArtifactReference,
    ) -> IngestionExecution:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions.begin() as session:
                rows = await self._load(session, job_id, lock=True)
                self._require_active_source(rows)
                if rows.projection.status is not ProjectionStatus.CHUNKING:
                    return self._require_completed_stage(rows, ProjectionStatus.EMBEDDING)
                await SqlAlchemyRagDocumentRepository(session).replace_chunks(
                    rows.projection.id, result.chunks
                )
                rows.ingestion.chunk_object_key = artifact.key
                rows.ingestion.chunk_sha256 = artifact.sha256
                rows.ingestion.chunk_count = len(result.chunks)
                await self._advance(session, rows, ProjectionStatus.EMBEDDING)
                return self._execution(rows)
        finally:
            await engine.dispose()

    async def complete_embedding(
        self, job_id: UUID, *, embedding_count: int
    ) -> IngestionExecution:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions.begin() as session:
                rows = await self._load(session, job_id, lock=True)
                self._require_active_source(rows)
                if rows.projection.status is not ProjectionStatus.EMBEDDING:
                    return self._require_completed_stage(rows, ProjectionStatus.INDEXING)
                if (
                    rows.ingestion.embedding_object_key is None
                    or rows.ingestion.embedding_sha256 is None
                    or rows.ingestion.embedding_count != embedding_count
                ):
                    raise RagIngestionError(
                        "embedding_artifact_missing",
                        "Embedding completion requires durable artifact metadata and count.",
                        retryable=False,
                    )
                rows.ingestion.embedding_count = embedding_count
                await self._advance(session, rows, ProjectionStatus.INDEXING)
                return self._execution(rows)
        finally:
            await engine.dispose()

    async def complete_indexing(
        self,
        job_id: UUID,
        verification: ReadinessVerification,
    ) -> IngestionExecution:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions.begin() as session:
                rows = await self._load(session, job_id, lock=True)
                self._require_active_source(rows)
                if rows.projection.status is not ProjectionStatus.INDEXING:
                    return self._require_completed_stage(rows, ProjectionStatus.READY)
                if (
                    not verification.is_complete
                    or verification.parsed_element_count
                    != rows.ingestion.parsed_element_count
                    or verification.chunk_count != rows.ingestion.chunk_count
                    or verification.embedding_count != rows.ingestion.embedding_count
                ):
                    raise RagIngestionError(
                        "readiness_verification_failed",
                        "Persisted RAG stage counts do not match readiness verification.",
                        retryable=False,
                    )
                rows.ingestion.indexed_document_count = verification.indexed_document_count
                rows.ingestion.index_alias_verified = verification.alias_verified
                await SqlAlchemyRagDocumentRepository(session).mark_status(
                    rows.projection.id, ProjectionStatus.READY
                )
                rows.projection.status = ProjectionStatus.READY
                rows.job.succeed(stage=ProjectionStatus.READY.value)
                await SqlAlchemyJobRepository(session).update(rows.job)
                return self._execution(rows)
        finally:
            await engine.dispose()

    async def fail(self, job_id: UUID, *, error_code: str, error_message: str) -> None:
        engine = create_engine(self.settings)
        sessions = create_session_factory(engine)
        try:
            async with sessions.begin() as session:
                rows = await self._load(session, job_id, lock=True)
                if (
                    rows.projection.status is ProjectionStatus.FAILED
                    and rows.job.status is JobStatus.FAILED
                ):
                    return
                if rows.projection.status in {
                    ProjectionStatus.READY,
                    ProjectionStatus.PARTIAL_READY,
                }:
                    raise RagIngestionError(
                        "projection_terminal",
                        "A completed RAG projection cannot be failed.",
                        retryable=False,
                    )
                if rows.job.status is JobStatus.QUEUED:
                    rows.job.start(stage=rows.projection.status)
                if rows.job.status is not JobStatus.RUNNING:
                    raise RagIngestionError(
                        "ingestion_state_inconsistent",
                        "Only a running RAG job can fail.",
                        retryable=False,
                    )
                await SqlAlchemyRagDocumentRepository(session).mark_status(
                    rows.projection.id, ProjectionStatus.FAILED
                )
                rows.job.fail(
                    error_code=error_code[:100],
                    error_message=error_message[:500],
                )
                await SqlAlchemyJobRepository(session).update(rows.job)
        finally:
            await engine.dispose()

    async def _advance(
        self,
        session: AsyncSession,
        rows: _IngestionRows,
        status: ProjectionStatus,
    ) -> None:
        await SqlAlchemyRagDocumentRepository(session).mark_status(rows.projection.id, status)
        rows.projection.status = status
        rows.job.advance(stage=status.value)
        await SqlAlchemyJobRepository(session).update(rows.job)

    async def _load(
        self,
        session: AsyncSession,
        job_id: UUID,
        *,
        lock: bool,
    ) -> _IngestionRows:
        statement = select(RagIngestionJobRecord).where(
            RagIngestionJobRecord.job_id == job_id
        )
        if lock:
            statement = statement.with_for_update()
        ingestion = await session.scalar(statement)
        if ingestion is None:
            raise RagIngestionError(
                "ingestion_job_not_found",
                "The RAG ingestion job does not exist.",
                retryable=False,
            )
        jobs = SqlAlchemyJobRepository(session)
        job = (
            await jobs.find_by_id_for_update(job_id)
            if lock
            else await jobs.find_by_id(job_id)
        )
        projection_statement = select(RagProjectionRecord).where(
            RagProjectionRecord.id == ingestion.projection_id
        )
        if lock:
            projection_statement = projection_statement.with_for_update()
        projection = await session.scalar(projection_statement)
        if projection is None or job is None:
            raise RagIngestionError(
                "ingestion_dependency_missing",
                "A durable RAG ingestion dependency is missing.",
                retryable=False,
            )
        projection.status = ProjectionStatus(projection.status)
        terminal = projection.status in {
            ProjectionStatus.READY,
            ProjectionStatus.PARTIAL_READY,
            ProjectionStatus.FAILED,
        }
        asset: AssetVersionRecord | None
        document: DocumentRecord | None
        if lock:
            source = await lock_ingestion_source(
                session,
                ingestion.asset_version_id,
                require_active=not terminal,
            )
            asset = source.asset
            document = source.document
        else:
            asset = await session.get(AssetVersionRecord, ingestion.asset_version_id)
            document = (
                await session.get(DocumentRecord, asset.document_id)
                if asset is not None
                else None
            )
        profile_statement = select(ProfileRecord).where(
            ProfileRecord.id == ingestion.indexing_profile_id
        )
        if lock:
            profile_statement = profile_statement.with_for_update()
        profile = await session.scalar(profile_statement)
        if asset is None or document is None or profile is None:
            raise RagIngestionError(
                "ingestion_dependency_missing",
                "A durable RAG ingestion dependency is missing.",
                retryable=False,
            )
        if (
            job.asset_version_id != ingestion.asset_version_id
            or job.user_id != ingestion.requested_by
            or profile.kind != "indexing"
        ):
            raise RagIngestionError(
                "ingestion_command_mismatch",
                "The durable RAG ingestion command does not match its job.",
                retryable=False,
            )
        return _IngestionRows(ingestion, projection, asset, document, profile, job)

    @staticmethod
    def _require_active_source(rows: _IngestionRows) -> None:
        if ProjectionStatus(rows.projection.status) in {
            ProjectionStatus.READY,
            ProjectionStatus.PARTIAL_READY,
            ProjectionStatus.FAILED,
        }:
            return
        if (
            VersionStatus(rows.asset.status) is not VersionStatus.READY
            or rows.document.active_version_id != rows.asset.id
        ):
            raise RagIngestionError(
                "index_source_inactive",
                "RAG ingestion requires the document's exact active READY version.",
                retryable=False,
            )

    def _execution(self, rows: _IngestionRows) -> IngestionExecution:
        return IngestionExecution(
            job_id=rows.ingestion.job_id,
            projection_id=rows.ingestion.projection_id,
            asset_version=AssetVersion(
                id=rows.asset.id,
                document_id=rows.asset.document_id,
                number=rows.asset.number,
                object_key=rows.asset.object_key,
                sha256=rows.asset.sha256,
                media_type=rows.asset.media_type,
                size=rows.asset.size,
                status=VersionStatus(rows.asset.status),
            ),
            filename=rows.document.name,
            indexing_profile_id=rows.ingestion.indexing_profile_id,
            requested_by=rows.ingestion.requested_by,
            chunking_config=_chunking_config(rows.profile.config),
            status=ProjectionStatus(rows.projection.status),
            parsed_artifact=_artifact(
                rows.ingestion.parsed_object_key, rows.ingestion.parsed_sha256
            ),
            chunk_artifact=_artifact(
                rows.ingestion.chunk_object_key, rows.ingestion.chunk_sha256
            ),
            embedding_artifact=_artifact(
                rows.ingestion.embedding_object_key, rows.ingestion.embedding_sha256
            ),
        )

    def _require_completed_stage(
        self,
        rows: _IngestionRows,
        expected: ProjectionStatus,
    ) -> IngestionExecution:
        order = {
            ProjectionStatus.PENDING: 0,
            ProjectionStatus.PARSING: 1,
            ProjectionStatus.CHUNKING: 2,
            ProjectionStatus.EMBEDDING: 3,
            ProjectionStatus.INDEXING: 4,
            ProjectionStatus.READY: 5,
        }
        current = ProjectionStatus(rows.projection.status)
        if current in order and order[current] >= order[expected]:
            return self._execution(rows)
        raise RagIngestionError(
            "ingestion_stage_conflict",
            f"RAG ingestion cannot complete {expected.value} from {current.value}.",
            retryable=False,
        )


def _artifact(key: str | None, sha256: str | None) -> ArtifactReference | None:
    if key is None and sha256 is None:
        return None
    if key is None or sha256 is None:
        raise RagIngestionError(
            "artifact_reference_incomplete",
            "A durable RAG artifact reference is incomplete.",
            retryable=False,
        )
    return ArtifactReference(key, sha256)


def _chunking_config(profile_config: dict[str, Any]) -> ChunkingConfig:
    raw = profile_config.get("chunker")
    if not isinstance(raw, dict) or raw.get("name") != "structure-aware":
        raise RagIngestionError(
            "unsupported_chunker_configuration",
            "The indexing profile does not select the structure-aware chunker.",
            retryable=False,
        )
    target = int(raw.get("target_tokens", 380))
    overlap = int(raw.get("overlap_tokens", 60))
    ceiling = int(raw.get("hard_ceiling_tokens", target + overlap))
    return ChunkingConfig(target, overlap, ceiling)


def create_rag_ingestion_workflow(settings: Settings) -> RagIngestionWorkflow:
    object_store = LocalObjectStore(settings.object_store_root)
    runtime_provider = EmbeddingRuntimeProvider()
    return RagIngestionWorkflow(
        SqlAlchemyRagIngestionLifecycle(settings),
        object_store,
        ParsingService(
            object_store,
            ParserRegistry((PlainTextParser(), MarkdownParser(), PdfParser())),
        ),
        ProductionChunkingStage(settings, runtime_provider),
        ProductionEmbeddingStage(
            settings, object_store, runtime_provider=runtime_provider
        ),
        ProductionIndexingStage(settings, object_store),
        ProductionReadinessVerifier(settings),
    )
