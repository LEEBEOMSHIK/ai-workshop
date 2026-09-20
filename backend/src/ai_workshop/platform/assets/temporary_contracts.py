"""Immutable document temporary workspace ownership contracts."""

import re
from dataclasses import dataclass
from uuid import UUID

from ai_workshop.platform.assets.provenance_contracts import SourceIdentity

TEMPORARY_STATES = {"open": 1, "closed": 2, "cleaning": 3, "cleaned": 4}
_CODES = frozenset(
    {
        "ownership_unconfirmed",
        "unsafe_path",
        "invalid_marker",
        "file_conflict",
        "ownership_failed",
        "invalid_claim",
        "state_conflict",
        "source_unavailable",
        "source_mismatch",
        "job_mismatch",
        "generation_mismatch",
        "writes_blocked",
        "binding_mismatch",
        "identity_mismatch",
        "observation_failed",
        "storage_unavailable",
        "invalid_state",
        "writer_unconfirmed",
        "cleanup_unconfirmed",
        "unsupported_platform",
        "workspace_exists",
        "workspace_missing",
        "unsafe_entry",
        "unknown_entry",
        "invalid_name",
        "allocation_failed",
        "cleanup_failed",
        "closed_workspace",
        "marker_mismatch",
        "store_unavailable",
        "untrusted_entry",
        "claim_reused",
    }
)


class TemporaryOwnershipError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code if code in _CODES else "ownership_failed"
        super().__init__(self.code)


@dataclass(frozen=True)
class TemporaryBinding:
    store_id: str
    binding_id: UUID

    def __post_init__(self) -> None:
        if (
            not isinstance(self.store_id, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,79}", self.store_id) is None
            or not isinstance(self.binding_id, UUID)
        ):
            raise TemporaryOwnershipError("invalid_claim")


@dataclass(frozen=True)
class TemporaryContext:
    source: SourceIdentity
    job_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceIdentity) or (
            self.job_id is not None and not isinstance(self.job_id, UUID)
        ):
            raise TemporaryOwnershipError("invalid_claim")


@dataclass(frozen=True)
class TemporaryClaim:
    id: UUID
    context: TemporaryContext
    purpose: str
    binding: TemporaryBinding
    generation: int
    coverage: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, UUID)
            or not isinstance(self.context, TemporaryContext)
            or not isinstance(self.binding, TemporaryBinding)
            or self.purpose not in {"parsing", "pdf_preview"}
            or type(self.generation) is not int
            or self.generation < 1
            or self.coverage not in {"bounded", "runtime_unverified"}
        ):
            raise TemporaryOwnershipError("invalid_claim")


def next_temporary_state(expected_state: str) -> tuple[str, int]:
    transitions = {"open": ("closed", 2), "closed": ("cleaning", 3), "cleaning": ("cleaned", 4)}
    if expected_state not in transitions:
        raise TemporaryOwnershipError("state_conflict")
    return transitions[expected_state]
