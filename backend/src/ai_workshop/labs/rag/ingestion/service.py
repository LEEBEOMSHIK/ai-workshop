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
    deserialize_chunking_result,
    deserialize_parsed_document,
    serialize_chunking_result,
    serialize_parsed_document,
)
from ai_workshop.platform.assets.domain import AssetVersion
from ai_workshop.platform.assets.storage import StoredObject


class ImmutableArtifactStore(Protocol):
    async def put_if_absent(
        self, key: str, source: AsyncIterator[bytes]
    ) -> StoredObject: ...

    def open(self, key: str) -> AsyncIterator[bytes]: ...


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
    async def chunk(
        self,
        document: ParsedDocument,
        *,
        projection_id: UUID,
        indexing_profile_id: UUID,
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
        object_store: ImmutableArtifactStore,
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
                self._require_nonempty_document(document)
                content = serialize_parsed_document(document)
                artifact, authoritative_content = await self._publish_artifact(
                    f"rag/parsed/{execution.projection_id}.json", content
                )
                document = self._deserialize_parsed(
                    authoritative_content,
                    asset_version_id=execution.asset_version.id,
                )
                self._require_nonempty_document(document)
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
                document = self._deserialize_parsed(
                    await self._read_artifact(execution.parsed_artifact),
                    asset_version_id=execution.asset_version.id,
                )
                self._require_nonempty_document(document)
                result = await self.chunker.chunk(
                    document,
                    projection_id=execution.projection_id,
                    indexing_profile_id=execution.indexing_profile_id,
                    config=execution.chunking_config,
                )
                self._require_nonempty_chunks(result)
                content = serialize_chunking_result(result)
                artifact, authoritative_content = await self._publish_artifact(
                    f"rag/chunks/{execution.projection_id}.json", content
                )
                result = self._deserialize_chunks(
                    authoritative_content,
                    projection_id=execution.projection_id,
                )
                self._require_nonempty_chunks(result)
                execution = await self.lifecycle.complete_chunking(job_id, result, artifact)
                continue
            if execution.status is ProjectionStatus.EMBEDDING:
                await self._require_nonempty_chunk_artifact(execution)
                count = await self.embeddings.embed(
                    projection_id=execution.projection_id,
                    indexing_profile_id=execution.indexing_profile_id,
                )
                execution = await self.lifecycle.complete_embedding(
                    job_id, embedding_count=count
                )
                continue
            if execution.status is ProjectionStatus.INDEXING:
                await self._require_nonempty_chunk_artifact(execution)
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

    async def _publish_artifact(
        self, key: str, content: bytes
    ) -> tuple[ArtifactReference, bytes]:
        try:
            stored = await self.object_store.put_if_absent(key, _bytes_source(content))
        except OSError as exc:
            raise RagIngestionError(
                "artifact_publication_failed",
                "The immutable RAG artifact could not be published.",
                retryable=True,
            ) from exc
        exact_content = await self._read_exact_key(key)
        exact_sha256 = hashlib.sha256(exact_content).hexdigest()
        if (
            stored.key != key
            or stored.size != len(exact_content)
            or stored.sha256 != exact_sha256
        ):
            raise RagIngestionError(
                "artifact_readback_mismatch",
                "The immutable RAG artifact metadata does not match its exact-key bytes.",
                retryable=False,
            )
        return ArtifactReference(key, exact_sha256), exact_content

    async def _read_artifact(self, artifact: ArtifactReference) -> bytes:
        content = await self._read_exact_key(artifact.key)
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            raise RagIngestionError(
                "artifact_checksum_mismatch",
                "The stored RAG artifact does not match its recorded digest.",
                retryable=False,
            )
        return content

    async def _require_nonempty_chunk_artifact(
        self, execution: IngestionExecution
    ) -> None:
        if execution.chunk_artifact is None:
            raise RagIngestionError(
                "artifact_reference_incomplete",
                "A durable RAG artifact reference is incomplete.",
                retryable=False,
            )
        result = self._deserialize_chunks(
            await self._read_artifact(execution.chunk_artifact),
            projection_id=execution.projection_id,
        )
        self._require_nonempty_chunks(result)

    async def _read_exact_key(self, key: str) -> bytes:
        try:
            return b"".join([part async for part in self.object_store.open(key)])
        except OSError as exc:
            raise RagIngestionError(
                "artifact_readback_failed",
                "The immutable RAG artifact could not be read from its exact key.",
                retryable=True,
            ) from exc

    @staticmethod
    def _deserialize_parsed(
        content: bytes, *, asset_version_id: UUID
    ) -> ParsedDocument:
        try:
            document = deserialize_parsed_document(content)
        except (KeyError, TypeError, ValueError) as exc:
            raise RagIngestionError(
                "artifact_payload_invalid",
                "The immutable parsed artifact payload is invalid.",
                retryable=False,
            ) from exc
        if document.asset_version_id != asset_version_id:
            raise RagIngestionError(
                "artifact_payload_mismatch",
                "The immutable parsed artifact belongs to another asset version.",
                retryable=False,
            )
        return document

    @staticmethod
    def _deserialize_chunks(
        content: bytes, *, projection_id: UUID
    ) -> ChunkingResult:
        try:
            result = deserialize_chunking_result(content)
        except (KeyError, TypeError, ValueError) as exc:
            raise RagIngestionError(
                "artifact_payload_invalid",
                "The immutable chunk artifact payload is invalid.",
                retryable=False,
            ) from exc
        if any(chunk.projection_id != projection_id for chunk in result.chunks) or any(
            unit.projection_id != projection_id for unit in result.evidence_units
        ):
            raise RagIngestionError(
                "artifact_payload_mismatch",
                "The immutable chunk artifact belongs to another projection.",
                retryable=False,
            )
        return result

    @staticmethod
    def _require_nonempty_document(document: ParsedDocument) -> None:
        if not document.elements:
            raise RagIngestionError(
                "parsed_document_empty",
                "The parsed document contains no structural elements.",
                retryable=False,
            )

    @staticmethod
    def _require_nonempty_chunks(result: ChunkingResult) -> None:
        if not result.chunks:
            raise RagIngestionError(
                "chunking_result_empty",
                "The chunking result contains no retrieval chunks.",
                retryable=False,
            )


async def _bytes_source(content: bytes) -> AsyncIterator[bytes]:
    yield content
