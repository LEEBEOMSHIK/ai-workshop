import hashlib
from collections.abc import AsyncIterator
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.chunking.contracts import ChunkingConfig, ChunkingResult
from ai_workshop.labs.rag.documents.domain import (
    EvidenceUnit,
    ParsedDocument,
    ProjectionStatus,
    RetrievalChunk,
    SourceLocation,
    StructuralElement,
)
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
from ai_workshop.labs.rag.ingestion.service import (
    IngestionCommandRepository,
    RagIngestionLifecycle,
    RagIngestionService,
    RagIngestionWorkflow,
)
from ai_workshop.platform.assets.domain import AssetVersion, VersionStatus
from ai_workshop.platform.assets.storage import StoredObject


class MemoryCommandRepository(IngestionCommandRepository):
    def __init__(self) -> None:
        self.jobs: dict[str, UUID] = {}
        self.commands: dict[UUID, EnsureIndexedCommand] = {}

    async def ensure(self, command: EnsureIndexedCommand, *, idempotency_key: str) -> UUID:
        if idempotency_key in self.jobs:
            return self.jobs[idempotency_key]
        job_id = uuid4()
        self.jobs[idempotency_key] = job_id
        self.commands[job_id] = command
        return job_id


@pytest.mark.asyncio
async def test_ensure_indexed_is_idempotent_for_asset_and_indexing_profile() -> None:
    repository = MemoryCommandRepository()
    service = RagIngestionService(repository)
    command = EnsureIndexedCommand(uuid4(), uuid4(), uuid4())

    first = await service.ensure_indexed(command)
    duplicate_from_another_requester = await service.ensure_indexed(
        replace(command, requested_by=uuid4())
    )

    assert duplicate_from_another_requester == first
    assert list(repository.jobs) == [
        f"{command.asset_version_id}:{command.indexing_profile_id}:rag_ingestion"
    ]
    assert repository.commands[first] == command


def parsed_fixture(asset_version_id: UUID) -> ParsedDocument:
    element_id = UUID("30000000-0000-0000-0000-000000000001")
    return ParsedDocument(
        asset_version_id=asset_version_id,
        parser_name="synthetic-parser",
        parser_version="1.2.3",
        elements=(
            StructuralElement(
                id=element_id,
                ordinal=0,
                kind="paragraph",
                text="Synthetic public fixture evidence.",
                section_path=("Policy", "Scope"),
                location=SourceLocation(
                    element_id=element_id,
                    page=3,
                    char_start=11,
                    char_end=45,
                    bbox=(10.5, 20.25, 210.75, 42.0),
                ),
                parser_name="synthetic-parser",
                parser_version="1.2.3",
                confidence=0.98,
            ),
        ),
    )


def chunks_fixture(projection_id: UUID, document: ParsedDocument) -> ChunkingResult:
    chunk_id = UUID("30000000-0000-0000-0000-000000000002")
    evidence = EvidenceUnit(
        id=UUID("30000000-0000-0000-0000-000000000003"),
        chunk_id=chunk_id,
        ordinal=0,
        text=document.elements[0].text,
        location=document.elements[0].location,
        projection_id=projection_id,
    )
    chunk = RetrievalChunk(
        id=chunk_id,
        projection_id=projection_id,
        ordinal=0,
        text="Policy > Scope\n\nSynthetic public fixture evidence.",
        section_path=("Policy", "Scope"),
        evidence_units=(evidence,),
    )
    return ChunkingResult(chunks=(chunk,), evidence_units=(evidence,))


def test_artifact_serialization_round_trips_all_immutable_provenance() -> None:
    asset_version_id = UUID("30000000-0000-0000-0000-000000000004")
    projection_id = UUID("30000000-0000-0000-0000-000000000005")
    document = parsed_fixture(asset_version_id)
    chunks = chunks_fixture(projection_id, document)

    parsed_copy = deserialize_parsed_document(serialize_parsed_document(document))
    chunks_copy = deserialize_chunking_result(serialize_chunking_result(chunks))

    assert parsed_copy == document
    assert chunks_copy == chunks
    assert chunks_copy.chunks[0].evidence_units[0] is chunks_copy.evidence_units[0]


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, source: AsyncIterator[bytes]) -> StoredObject:
        content = b"".join([part async for part in source])
        self.objects[key] = content
        return StoredObject(key, len(content), hashlib.sha256(content).hexdigest())

    async def put_if_absent(
        self, key: str, source: AsyncIterator[bytes]
    ) -> StoredObject:
        content = b"".join([part async for part in source])
        self.objects.setdefault(key, content)
        authoritative = self.objects[key]
        return StoredObject(
            key, len(authoritative), hashlib.sha256(authoritative).hexdigest()
        )

    async def open(self, key: str) -> AsyncIterator[bytes]:
        yield self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class FixedParser:
    def __init__(self, document: ParsedDocument) -> None:
        self.document = document

    async def materialize_and_parse(
        self, asset_version: AssetVersion, filename: str
    ) -> ParsedDocument:
        assert asset_version.id == self.document.asset_version_id
        assert filename == "synthetic.txt"
        return self.document


class ForbiddenParser:
    async def materialize_and_parse(
        self, asset_version: AssetVersion, filename: str
    ) -> ParsedDocument:
        raise AssertionError("A resumed chunking execution must not parse again.")


class CorruptReadBackStore(MemoryObjectStore):
    async def put(self, key: str, source: AsyncIterator[bytes]) -> StoredObject:
        candidate = b"".join([part async for part in source])
        self.objects[key] = b"corrupted-after-publication"
        return StoredObject(key, len(candidate), hashlib.sha256(candidate).hexdigest())

    async def put_if_absent(
        self, key: str, source: AsyncIterator[bytes]
    ) -> StoredObject:
        return await self.put(key, source)


class MissingReadBackStore(MemoryObjectStore):
    async def open(self, key: str) -> AsyncIterator[bytes]:
        raise OSError("synthetic exact-key read failure")
        yield b""  # pragma: no cover


class FixedChunker:
    def __init__(self, document: ParsedDocument, result: ChunkingResult) -> None:
        self.document = document
        self.result = result

    def chunk(
        self,
        document: ParsedDocument,
        *,
        projection_id: UUID,
        config: ChunkingConfig,
    ) -> ChunkingResult:
        assert document == self.document
        assert projection_id == self.result.chunks[0].projection_id
        assert config == ChunkingConfig(380, 60, 440)
        return self.result


class ForbiddenChunker:
    def chunk(
        self,
        document: ParsedDocument,
        *,
        projection_id: UUID,
        config: ChunkingConfig,
    ) -> ChunkingResult:
        raise AssertionError("An empty parsed document must not reach chunking.")


class EmptyChunker:
    def __init__(self, document: ParsedDocument, projection_id: UUID) -> None:
        self.document = document
        self.projection_id = projection_id

    def chunk(
        self,
        document: ParsedDocument,
        *,
        projection_id: UUID,
        config: ChunkingConfig,
    ) -> ChunkingResult:
        assert document == self.document
        assert projection_id == self.projection_id
        assert config == ChunkingConfig(380, 60, 440)
        return ChunkingResult(chunks=(), evidence_units=())


class ExplicitFakeStages:
    async def embed(self, *, projection_id: UUID, indexing_profile_id: UUID) -> int:
        return 1

    async def index(self, *, projection_id: UUID, indexing_profile_id: UUID) -> None:
        return None

    async def verify(
        self, *, projection_id: UUID, indexing_profile_id: UUID
    ) -> ReadinessVerification:
        return ReadinessVerification(
            parsed_element_count=1,
            chunk_count=1,
            embedding_count=1,
            indexed_document_count=1,
            alias_verified=True,
        )


class ForbiddenStages:
    async def embed(self, *, projection_id: UUID, indexing_profile_id: UUID) -> int:
        raise AssertionError("An empty ingestion result must not reach embedding.")

    async def index(self, *, projection_id: UUID, indexing_profile_id: UUID) -> None:
        raise AssertionError("An empty ingestion result must not reach indexing.")

    async def verify(
        self, *, projection_id: UUID, indexing_profile_id: UUID
    ) -> ReadinessVerification:
        raise AssertionError("An empty ingestion result must not reach verification.")


class MemoryLifecycle(RagIngestionLifecycle):
    def __init__(self, execution: IngestionExecution) -> None:
        self.execution = execution
        self.statuses = [execution.status]
        self.artifacts: list[ArtifactReference] = []
        self.verification: ReadinessVerification | None = None

    async def begin(self, job_id: UUID) -> IngestionExecution:
        self.execution = replace(self.execution, status=ProjectionStatus.PARSING)
        self.statuses.append(self.execution.status)
        return self.execution

    async def complete_parsing(
        self,
        job_id: UUID,
        document: ParsedDocument,
        artifact: ArtifactReference,
    ) -> IngestionExecution:
        self.artifacts.append(artifact)
        self.execution = replace(
            self.execution,
            status=ProjectionStatus.CHUNKING,
            parsed_artifact=artifact,
        )
        self.statuses.append(self.execution.status)
        return self.execution

    async def complete_chunking(
        self,
        job_id: UUID,
        result: ChunkingResult,
        artifact: ArtifactReference,
    ) -> IngestionExecution:
        self.artifacts.append(artifact)
        self.execution = replace(
            self.execution,
            status=ProjectionStatus.EMBEDDING,
            chunk_artifact=artifact,
        )
        self.statuses.append(self.execution.status)
        return self.execution

    async def complete_embedding(self, job_id: UUID, *, embedding_count: int) -> IngestionExecution:
        assert embedding_count == 1
        self.execution = replace(self.execution, status=ProjectionStatus.INDEXING)
        self.statuses.append(self.execution.status)
        return self.execution

    async def complete_indexing(
        self, job_id: UUID, verification: ReadinessVerification
    ) -> IngestionExecution:
        self.verification = verification
        self.execution = replace(self.execution, status=ProjectionStatus.READY)
        self.statuses.append(self.execution.status)
        return self.execution

    async def fail(self, job_id: UUID, *, error_code: str, error_message: str) -> None:
        self.execution = replace(self.execution, status=ProjectionStatus.FAILED)
        self.statuses.append(self.execution.status)


class ResumedLifecycle(MemoryLifecycle):
    async def begin(self, job_id: UUID) -> IngestionExecution:
        return self.execution


@pytest.mark.asyncio
async def test_workflow_persists_artifacts_before_advancing_through_exact_lifecycle() -> None:
    job_id = uuid4()
    asset_version_id = uuid4()
    indexing_profile_id = uuid4()
    projection_id = uuid4()
    document = parsed_fixture(asset_version_id)
    chunks = chunks_fixture(projection_id, document)
    lifecycle = MemoryLifecycle(
        IngestionExecution(
            job_id=job_id,
            projection_id=projection_id,
            asset_version=AssetVersion(
                id=asset_version_id,
                document_id=uuid4(),
                number=1,
                object_key="synthetic/source.txt",
                sha256="a" * 64,
                media_type="text/plain",
                size=34,
                status=VersionStatus.STORED,
            ),
            filename="synthetic.txt",
            indexing_profile_id=indexing_profile_id,
            requested_by=uuid4(),
            chunking_config=ChunkingConfig(380, 60, 440),
            status=ProjectionStatus.PENDING,
        )
    )
    store = MemoryObjectStore()
    stages = ExplicitFakeStages()
    workflow = RagIngestionWorkflow(
        lifecycle,
        store,
        FixedParser(document),
        FixedChunker(document, chunks),
        stages,
        stages,
        stages,
    )

    returned_projection_id = await workflow.run(job_id)

    assert returned_projection_id == projection_id
    assert lifecycle.statuses == [
        ProjectionStatus.PENDING,
        ProjectionStatus.PARSING,
        ProjectionStatus.CHUNKING,
        ProjectionStatus.EMBEDDING,
        ProjectionStatus.INDEXING,
        ProjectionStatus.READY,
    ]
    assert [artifact.key for artifact in lifecycle.artifacts] == [
        f"rag/parsed/{projection_id}.json",
        f"rag/chunks/{projection_id}.json",
    ]
    assert all(
        artifact.sha256 == hashlib.sha256(store.objects[artifact.key]).hexdigest()
        for artifact in lifecycle.artifacts
    )
    assert deserialize_parsed_document(store.objects[lifecycle.artifacts[0].key]) == document
    assert deserialize_chunking_result(store.objects[lifecycle.artifacts[1].key]) == chunks
    assert lifecycle.verification == ReadinessVerification(1, 1, 1, 1, True)


def ingestion_execution_fixture(
    *, job_id: UUID, asset_version_id: UUID, projection_id: UUID
) -> IngestionExecution:
    return IngestionExecution(
        job_id=job_id,
        projection_id=projection_id,
        asset_version=AssetVersion(
            id=asset_version_id,
            document_id=uuid4(),
            number=1,
            object_key="synthetic/source.txt",
            sha256="a" * 64,
            media_type="text/plain",
            size=34,
            status=VersionStatus.STORED,
        ),
        filename="synthetic.txt",
        indexing_profile_id=uuid4(),
        requested_by=uuid4(),
        chunking_config=ChunkingConfig(380, 60, 440),
        status=ProjectionStatus.PENDING,
    )


@pytest.mark.asyncio
async def test_corrupted_exact_key_readback_never_advances_parsing_status() -> None:
    job_id = uuid4()
    asset_version_id = uuid4()
    projection_id = uuid4()
    document = parsed_fixture(asset_version_id)
    lifecycle = MemoryLifecycle(
        ingestion_execution_fixture(
            job_id=job_id,
            asset_version_id=asset_version_id,
            projection_id=projection_id,
        )
    )
    stages = ExplicitFakeStages()
    workflow = RagIngestionWorkflow(
        lifecycle,
        CorruptReadBackStore(),
        FixedParser(document),
        FixedChunker(document, chunks_fixture(projection_id, document)),
        stages,
        stages,
        stages,
    )

    with pytest.raises(RagIngestionError) as raised:
        await workflow.run(job_id)

    assert raised.value.code == "artifact_readback_mismatch"
    assert lifecycle.statuses == [ProjectionStatus.PENDING, ProjectionStatus.PARSING]
    assert lifecycle.artifacts == []


@pytest.mark.asyncio
async def test_unreadable_exact_key_never_advances_parsing_status() -> None:
    job_id = uuid4()
    asset_version_id = uuid4()
    projection_id = uuid4()
    document = parsed_fixture(asset_version_id)
    lifecycle = MemoryLifecycle(
        ingestion_execution_fixture(
            job_id=job_id,
            asset_version_id=asset_version_id,
            projection_id=projection_id,
        )
    )
    stages = ExplicitFakeStages()
    workflow = RagIngestionWorkflow(
        lifecycle,
        MissingReadBackStore(),
        FixedParser(document),
        FixedChunker(document, chunks_fixture(projection_id, document)),
        stages,
        stages,
        stages,
    )

    with pytest.raises(RagIngestionError) as raised:
        await workflow.run(job_id)

    assert raised.value.code == "artifact_readback_failed"
    assert raised.value.retryable is True
    assert lifecycle.statuses == [ProjectionStatus.PENDING, ProjectionStatus.PARSING]
    assert lifecycle.artifacts == []


@pytest.mark.asyncio
async def test_empty_parse_fails_before_artifact_publication_or_later_stages() -> None:
    job_id = uuid4()
    asset_version_id = uuid4()
    projection_id = uuid4()
    empty_document = ParsedDocument(
        asset_version_id=asset_version_id,
        parser_name="synthetic-parser",
        parser_version="1.2.3",
        elements=(),
    )
    lifecycle = MemoryLifecycle(
        ingestion_execution_fixture(
            job_id=job_id,
            asset_version_id=asset_version_id,
            projection_id=projection_id,
        )
    )
    store = MemoryObjectStore()
    stages = ForbiddenStages()
    workflow = RagIngestionWorkflow(
        lifecycle,
        store,
        FixedParser(empty_document),
        ForbiddenChunker(),
        stages,
        stages,
        stages,
    )

    with pytest.raises(RagIngestionError) as raised:
        await workflow.run(job_id)

    assert raised.value.code == "parsed_document_empty"
    assert raised.value.retryable is False
    assert store.objects == {}
    assert lifecycle.statuses == [ProjectionStatus.PENDING, ProjectionStatus.PARSING]
    assert lifecycle.artifacts == []


@pytest.mark.asyncio
async def test_resumed_empty_parsed_artifact_fails_before_chunking_or_later_stages() -> None:
    job_id = uuid4()
    asset_version_id = uuid4()
    projection_id = uuid4()
    empty_document = ParsedDocument(
        asset_version_id=asset_version_id,
        parser_name="synthetic-parser",
        parser_version="1.2.3",
        elements=(),
    )
    content = serialize_parsed_document(empty_document)
    parsed_artifact = ArtifactReference(
        key=f"rag/parsed/{projection_id}.json",
        sha256=hashlib.sha256(content).hexdigest(),
    )
    lifecycle = ResumedLifecycle(
        replace(
            ingestion_execution_fixture(
                job_id=job_id,
                asset_version_id=asset_version_id,
                projection_id=projection_id,
            ),
            status=ProjectionStatus.CHUNKING,
            parsed_artifact=parsed_artifact,
        )
    )
    store = MemoryObjectStore()
    store.objects[parsed_artifact.key] = content
    stages = ForbiddenStages()
    workflow = RagIngestionWorkflow(
        lifecycle,
        store,
        ForbiddenParser(),
        ForbiddenChunker(),
        stages,
        stages,
        stages,
    )

    with pytest.raises(RagIngestionError) as raised:
        await workflow.run(job_id)

    assert raised.value.code == "parsed_document_empty"
    assert raised.value.retryable is False
    assert lifecycle.statuses == [ProjectionStatus.CHUNKING]
    assert lifecycle.artifacts == []


@pytest.mark.asyncio
async def test_empty_chunking_result_fails_before_publication_or_embedding() -> None:
    job_id = uuid4()
    asset_version_id = uuid4()
    projection_id = uuid4()
    document = parsed_fixture(asset_version_id)
    lifecycle = MemoryLifecycle(
        ingestion_execution_fixture(
            job_id=job_id,
            asset_version_id=asset_version_id,
            projection_id=projection_id,
        )
    )
    store = MemoryObjectStore()
    stages = ForbiddenStages()
    workflow = RagIngestionWorkflow(
        lifecycle,
        store,
        FixedParser(document),
        EmptyChunker(document, projection_id),
        stages,
        stages,
        stages,
    )

    with pytest.raises(RagIngestionError) as raised:
        await workflow.run(job_id)

    assert raised.value.code == "chunking_result_empty"
    assert raised.value.retryable is False
    assert list(store.objects) == [f"rag/parsed/{projection_id}.json"]
    assert lifecycle.statuses == [
        ProjectionStatus.PENDING,
        ProjectionStatus.PARSING,
        ProjectionStatus.CHUNKING,
    ]
    assert [artifact.key for artifact in lifecycle.artifacts] == [
        f"rag/parsed/{projection_id}.json"
    ]


def test_readiness_requires_real_count_and_alias_verification() -> None:
    assert ReadinessVerification(1, 2, 2, 2, True).is_complete is True
    assert ReadinessVerification(1, 2, 1, 2, True).is_complete is False
    assert ReadinessVerification(1, 2, 2, 2, False).is_complete is False
