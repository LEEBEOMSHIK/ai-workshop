"""Private immutable identity and safe error contracts for tracked indices."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

INDEX_ERROR_CODES = frozenset(
    {
        "rag_index_binding_mismatch",
        "rag_index_identity_conflict",
        "rag_index_input_conflict",
        "rag_index_attempt_busy",
        "rag_index_writer_unconfirmed",
        "rag_index_inventory_changed",
        "rag_index_inventory_incomplete",
        "rag_index_observation_failed",
    }
)
INDEX_RESULT_CODES = frozenset(
    {
        "prepared",
        "rag_index_binding_mismatch",
        "rag_index_identity_conflict",
        "rag_index_input_conflict",
        "rag_index_observation_failed",
    }
)


class IndexTrackingError(RuntimeError):
    def __init__(self, code: str) -> None:
        if code not in INDEX_ERROR_CODES:
            raise ValueError("Invalid index tracking code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class IndexBinding:
    store_id: str
    cluster_uuid: str

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[a-z][a-z0-9_]{0,79}", self.store_id) is None
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.cluster_uuid) is None
        ):
            raise ValueError("Invalid index binding")


@dataclass(frozen=True, slots=True)
class IndexResource:
    build_id: UUID
    projection_id: UUID
    job_id: UUID
    workspace_id: UUID
    document_id: UUID
    asset_version_id: UUID
    document_processing_profile_id: UUID
    indexing_profile_id: UUID
    revision: int
    binding: IndexBinding
    index_name: str
    alias: str
    mapping_version: int
    vector_dimension: int
    similarity: str
    index_uuid: str | None
    input_fingerprint: str | None
    chunk_ids_sha256: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.revision) is not int
            or self.revision < 1
            or self.mapping_version < 1
            or self.vector_dimension < 1
            or self.similarity != "cosine"
        ):
            raise ValueError("Invalid index descriptor or revision")
        if any(
            re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,254}", value) is None
            for value in (self.index_name, self.alias)
        ):
            raise ValueError("Invalid concrete index name")
        if (
            self.index_uuid is not None
            and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.index_uuid) is None
        ):
            raise ValueError("Invalid index identity")
        if (
            self.input_fingerprint is not None
            and re.fullmatch(r"[0-9a-f]{64}", self.input_fingerprint) is None
        ):
            raise ValueError("Invalid index input fingerprint")
        if (
            self.chunk_ids_sha256 is not None
            and re.fullmatch(r"[0-9a-f]{64}", self.chunk_ids_sha256) is None
        ):
            raise ValueError("Invalid index chunk fingerprint")


@dataclass(frozen=True, slots=True)
class IndexClaim:
    resource: IndexResource
    attempt_id: UUID


def index_chunk_ids_fingerprint(ids: Sequence[UUID]) -> str:
    """SHA-256 of sorted canonical UUID strings encoded as compact JSON UTF-8."""
    values = [str(value) for value in ids]
    if len(set(values)) != len(values):
        raise IndexTrackingError("rag_index_input_conflict")
    return sha256(json.dumps(sorted(values), separators=(",", ":")).encode("utf-8")).hexdigest()
