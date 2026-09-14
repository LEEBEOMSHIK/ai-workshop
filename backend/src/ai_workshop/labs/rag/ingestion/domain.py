from dataclasses import dataclass
from uuid import UUID

from ai_workshop.labs.rag.chunking.contracts import ChunkingConfig
from ai_workshop.labs.rag.documents.domain import ProjectionStatus
from ai_workshop.labs.rag.ingestion.artifact_contracts import ArtifactPublication, VerifiedArtifact
from ai_workshop.labs.rag.models.document_processing import (
    LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
    DocumentProcessingSpec,
)
from ai_workshop.platform.assets.domain import AssetVersion


@dataclass(frozen=True, slots=True)
class EnsureIndexedCommand:
    asset_version_id: UUID
    indexing_profile_id: UUID
    requested_by: UUID
    document_processing_profile_id: UUID = LEGACY_DOCUMENT_PROCESSING_PROFILE_ID


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    key: str
    sha256: str
    tracking: ArtifactPublication | VerifiedArtifact | None = None

    def __post_init__(self) -> None:
        if not self.key or len(self.sha256) != 64:
            raise ValueError("Artifact references require an object key and SHA-256 digest.")


@dataclass(frozen=True, slots=True)
class ReadinessVerification:
    parsed_element_count: int
    chunk_count: int
    embedding_count: int
    indexed_document_count: int
    alias_verified: bool

    @property
    def is_complete(self) -> bool:
        return (
            self.parsed_element_count > 0
            and self.chunk_count > 0
            and self.embedding_count == self.chunk_count
            and self.indexed_document_count == self.chunk_count
            and self.alias_verified
        )


@dataclass(frozen=True, slots=True)
class IngestionExecution:
    job_id: UUID
    projection_id: UUID
    asset_version: AssetVersion
    filename: str
    indexing_profile_id: UUID
    requested_by: UUID
    chunking_config: ChunkingConfig
    status: ProjectionStatus
    parsed_artifact: ArtifactReference | None = None
    chunk_artifact: ArtifactReference | None = None
    embedding_artifact: ArtifactReference | None = None
    document_processing_profile_id: UUID = LEGACY_DOCUMENT_PROCESSING_PROFILE_ID
    document_processing_spec: DocumentProcessingSpec | None = None


class RagIngestionError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class RagIngestionBusy(RagIngestionError):
    """This delivery does not own the open attempt; it cannot fail the shared job."""

    def __init__(self) -> None:
        super().__init__("artifact_attempt_busy", "artifact_attempt_busy", retryable=False)
