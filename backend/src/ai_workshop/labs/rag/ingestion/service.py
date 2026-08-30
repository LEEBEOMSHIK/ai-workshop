import hashlib
from collections.abc import AsyncIterator
from typing import Protocol
from uuid import UUID

from ai_workshop.labs.rag.chunking.contracts import ChunkingConfig, ChunkingResult
from ai_workshop.labs.rag.documents.domain import ParsedDocument, ProjectionStatus
from ai_workshop.labs.rag.ingestion.domain import (
    ArtifactReference,
    EnsureIndexedCommand,
    IngestionExecution,
    RagIngestionError,
    ReadinessVerification,
)
from ai_workshop.labs.rag.ingestion.serialization import (
    deserialize_parsed_document,
    serialize_chunking_result,
    serialize_parsed_document,
)
from ai_workshop.platform.assets.domain import AssetVersion
from ai_workshop.platform.assets.storage import ObjectStore


class IngestionCommandRepository(Protocol):
    async def ensure(self, command: EnsureIndexedCommand, *, idempotency_key: str) -> UUID: ...


class RagIngestionLifecycle(Protocol):
    async def begin(self, job_id: UUID) -> IngestionExecution: ...

    async def complete_parsing(
        self,
        job_id: UUID,
        document: ParsedDocument,
        artifact: ArtifactReference,
    ) -> IngestionExecution: ...

    async def complete_chunking(
        self,
        job_id: UUID,
        result: ChunkingResult,
        artifact: ArtifactReference,
    ) -> IngestionExecution: ...

    async def complete_embedding(
        self, job_id: UUID, *, embedding_count: int
    ) -> IngestionExecution: ...

    async def complete_indexing(
        self,
        job_id: UUID,
        verification: ReadinessVerification,
    ) -> IngestionExecution: ...

    async def fail(self, job_id: UUID, *, error_code: str, error_message: str) -> None: ...


class ParsingPort(Protocol):
    async def materialize_and_parse(
        self, asset_version: AssetVersion, filename: str
    ) -> ParsedDocument: ...


class ChunkingPort(Protocol):
    def chunk(
        self,
        document: ParsedDocument,
        *,
        projection_id: UUID,
        config: ChunkingConfig,
    ) -> ChunkingResult: ...


class EmbeddingStagePort(Protocol):
    async def embed(self, *, projection_id: UUID, indexing_profile_id: UUID) -> int: ...


class IndexingStagePort(Protocol):
    async def index(self, *, projection_id: UUID, indexing_profile_id: UUID) -> None: ...


class ReadinessVerifierPort(Protocol):
    async def verify(
        self, *, projection_id: UUID, indexing_profile_id: UUID
    ) -> ReadinessVerification: ...


class RagIngestionService:
    def __init__(self, repository: IngestionCommandRepository) -> None:
        self.repository = repository

    async def ensure_indexed(self, command: EnsureIndexedCommand) -> UUID:
        idempotency_key = (
            f"{command.asset_version_id}:{command.indexing_profile_id}:rag_ingestion"
        )
        return await self.repository.ensure(command, idempotency_key=idempotency_key)


class RagIngestionWorkflow:
    def __init__(
        self,
        lifecycle: RagIngestionLifecycle,
        object_store: ObjectStore,
        parser: ParsingPort,
        chunker: ChunkingPort,
        embeddings: EmbeddingStagePort,
        indexing: IndexingStagePort,
        verifier: ReadinessVerifierPort,
    ) -> None:
        self.lifecycle = lifecycle
        self.object_store = object_store
        self.parser = parser
        self.chunker = chunker
        self.embeddings = embeddings
        self.indexing = indexing
        self.verifier = verifier

    async def run(self, job_id: UUID) -> UUID:
        execution = await self.lifecycle.begin(job_id)
        while execution.status is not ProjectionStatus.READY:
            if execution.status is ProjectionStatus.PARSING:
                document = await self.parser.materialize_and_parse(
                    execution.asset_version, execution.filename
                )
                content = serialize_parsed_document(document)
                artifact = await self._store_artifact(
                    f"rag/parsed/{execution.projection_id}.json", content
                )
                execution = await self.lifecycle.complete_parsing(
                    job_id, document, artifact
                )
                continue
            if execution.status is ProjectionStatus.CHUNKING:
                if execution.parsed_artifact is None:
                    raise RagIngestionError(
                        "parsed_artifact_missing",
                        "The parsed artifact reference is missing.",
                        retryable=False,
                    )
                document = deserialize_parsed_document(
                    await self._read_artifact(execution.parsed_artifact)
                )
                result = self.chunker.chunk(
                    document,
                    projection_id=execution.projection_id,
                    config=execution.chunking_config,
                )
                content = serialize_chunking_result(result)
                artifact = await self._store_artifact(
                    f"rag/chunks/{execution.projection_id}.json", content
                )
                execution = await self.lifecycle.complete_chunking(job_id, result, artifact)
                continue
            if execution.status is ProjectionStatus.EMBEDDING:
                count = await self.embeddings.embed(
                    projection_id=execution.projection_id,
                    indexing_profile_id=execution.indexing_profile_id,
                )
                execution = await self.lifecycle.complete_embedding(
                    job_id, embedding_count=count
                )
                continue
            if execution.status is ProjectionStatus.INDEXING:
                await self.indexing.index(
                    projection_id=execution.projection_id,
                    indexing_profile_id=execution.indexing_profile_id,
                )
                verification = await self.verifier.verify(
                    projection_id=execution.projection_id,
                    indexing_profile_id=execution.indexing_profile_id,
                )
                if not verification.is_complete:
                    raise RagIngestionError(
                        "readiness_verification_failed",
                        "RAG projection count or alias verification did not complete.",
                        retryable=False,
                    )
                execution = await self.lifecycle.complete_indexing(
                    job_id, verification
                )
                continue
            raise RagIngestionError(
                "projection_terminal",
                f"RAG projection cannot continue from {execution.status.value}.",
                retryable=False,
            )
        return execution.projection_id

    async def fail(self, job_id: UUID, *, error_code: str, error_message: str) -> None:
        await self.lifecycle.fail(
            job_id,
            error_code=error_code,
            error_message=error_message,
        )

    async def _store_artifact(self, key: str, content: bytes) -> ArtifactReference:
        sha256 = hashlib.sha256(content).hexdigest()
        stored = await self.object_store.put(key, _bytes_source(content))
        if stored.key != key or stored.sha256 != sha256:
            raise RagIngestionError(
                "artifact_write_mismatch",
                "The object store did not preserve the RAG artifact digest.",
                retryable=True,
            )
        return ArtifactReference(key, sha256)

    async def _read_artifact(self, artifact: ArtifactReference) -> bytes:
        content = b"".join([part async for part in self.object_store.open(artifact.key)])
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise RagIngestionError(
                "artifact_checksum_mismatch",
                "The stored RAG artifact does not match its recorded digest.",
                retryable=False,
            )
        return content


async def _bytes_source(content: bytes) -> AsyncIterator[bytes]:
    yield content
