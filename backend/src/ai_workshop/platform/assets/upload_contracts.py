"""Immutable, private ownership contracts for original upload bytes."""

import re
from dataclasses import dataclass
from uuid import UUID

from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.storage import StoredObject

ALLOWED_ORIGINAL_SUFFIXES = frozenset(
    {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".html", ".htm"}
)
UPLOAD_ERROR_CODES = frozenset(
    {
        "invalid_claim",
        "invalid_state",
        "identity_mismatch",
        "generation_mismatch",
        "source_unavailable",
        "binding_mismatch",
        "store_unavailable",
        "invalid_marker",
        "unsafe_path",
        "file_conflict",
        "content_mismatch",
        "writer_unconfirmed",
        "ownership_unconfirmed",
        "reservation_conflict",
        "attachment_mismatch",
    }
)


class UploadOwnershipError(ValueError):
    def __init__(self, code: str) -> None:
        if code not in UPLOAD_ERROR_CODES:
            raise ValueError("unsupported upload ownership error code")
        self.code = code
        super().__init__(code)


def _uuid(value: object) -> None:
    if type(value) is not UUID:
        raise TypeError("UUID required")


@dataclass(frozen=True)
class OriginalStoreBinding:
    store_id: str
    binding_id: UUID

    def __post_init__(self) -> None:
        if (
            type(self.store_id) is not str
            or re.fullmatch(r"[a-z][a-z0-9_]{0,79}", self.store_id) is None
        ):
            raise ValueError("invalid store identifier")
        _uuid(self.binding_id)


@dataclass(frozen=True)
class UploadClaim:
    attempt_id: UUID
    source: SourceIdentity
    user_id: UUID
    folder_id: UUID | None
    new_document: bool
    binding: OriginalStoreBinding
    suffix: str
    generation: int | None = None

    def __post_init__(self) -> None:
        _uuid(self.attempt_id)
        _uuid(self.user_id)
        if self.folder_id is not None:
            _uuid(self.folder_id)
        if (
            type(self.source) is not SourceIdentity
            or type(self.binding) is not OriginalStoreBinding
        ):
            raise TypeError("invalid claim identity")
        if type(self.new_document) is not bool:
            raise TypeError("boolean required")
        if type(self.suffix) is not str or self.suffix not in ALLOWED_ORIGINAL_SUFFIXES:
            raise ValueError("invalid original suffix")
        if self.generation is not None and (
            type(self.generation) is not int or self.generation < 1
        ):
            raise ValueError("invalid generation")
        if self.new_document and self.generation is not None:
            raise ValueError("new source cannot have a generation")

    @property
    def canonical_key(self) -> str:
        prefix = f"{self.source.workspace_id}/{self.source.document_id}"
        return f"{prefix}/{self.attempt_id.hex}{self.suffix}"

    @property
    def temporary_key(self) -> str:
        prefix = f"{self.source.workspace_id}/{self.source.document_id}"
        return f"{prefix}/.{self.attempt_id.hex}.upload.tmp"


def validate_stored(claim: UploadClaim, stored: StoredObject) -> None:
    if type(stored) is not StoredObject or stored.key != claim.canonical_key:
        raise UploadOwnershipError("identity_mismatch")
    if type(stored.size) is not int or stored.size < 0 or type(stored.sha256) is not str:
        raise UploadOwnershipError("content_mismatch")
    if re.fullmatch(r"[0-9a-f]{64}", stored.sha256) is None:
        raise UploadOwnershipError("content_mismatch")


@dataclass(frozen=True)
class UploadAttempt:
    claim: UploadClaim
    state: str
    revision: int
    size: int | None
    sha256: str | None

    def __post_init__(self) -> None:
        if type(self.claim) is not UploadClaim or type(self.revision) is not int:
            raise TypeError("invalid attempt")
        expected = {
            "open": {1},
            "published": {2},
            "attached": {3},
            "discarding": {3},
            "abandoned": {2, 4},
        }
        if type(self.state) is not str or self.revision not in expected.get(self.state, set()):
            raise ValueError("invalid state revision")
        has_content = self.state in {"published", "attached", "discarding"} or (
            self.state == "abandoned" and self.revision == 4
        )
        if has_content:
            if self.size is None or self.sha256 is None:
                raise ValueError("published content required")
            validate_stored(
                self.claim, StoredObject(self.claim.canonical_key, self.size, self.sha256)
            )
        elif self.size is not None or self.sha256 is not None:
            raise ValueError("unpublished content forbidden")


@dataclass(frozen=True)
class OriginalFileObservation:
    canonical: StoredObject | None
    temporary_exists: bool

    def __post_init__(self) -> None:
        if self.canonical is not None and type(self.canonical) is not StoredObject:
            raise TypeError("invalid canonical observation")
        if type(self.temporary_exists) is not bool:
            raise TypeError("boolean required")
