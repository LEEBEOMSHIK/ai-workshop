from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

_STORE_ID = re.compile(r"[a-z][a-z0-9_]{0,79}")


class ArtifactRole(StrEnum):
    PARSED = "parsed"
    CHUNKS = "chunks"
    EMBEDDINGS = "embeddings"


@dataclass(frozen=True, slots=True)
class ArtifactBinding:
    store_id: str
    binding_id: UUID

    def __post_init__(self) -> None:
        if type(self.store_id) is not str or _STORE_ID.fullmatch(self.store_id) is None:
            raise ValueError("store_id must be a machine identifier")
        if not isinstance(self.binding_id, UUID):
            raise TypeError("binding_id must be a UUID")


@dataclass(frozen=True, slots=True, repr=False)
class ArtifactClaim:
    bundle_id: UUID
    slot_id: UUID
    attempt_id: UUID
    job_id: UUID
    projection_id: UUID
    role: ArtifactRole
    binding: ArtifactBinding
    canonical_key: str
    temporary_key: str
    proposed_size: int
    proposed_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedArtifact:
    bundle_id: UUID
    slot_id: UUID
    job_id: UUID
    projection_id: UUID
    role: ArtifactRole
    binding: ArtifactBinding
    canonical_key: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class ArtifactPublication:
    """Trusted internal handoff after canonical validation and temporary cleanup."""

    claim: ArtifactClaim
    size: int
    sha256: str


class ArtifactTrackingError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
