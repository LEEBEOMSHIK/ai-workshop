"""Immutable public launch capability, set once by the protected startup barrier."""

from dataclasses import dataclass
from uuid import UUID

from ai_workshop.infrastructure.search.access_credentials import ServiceRole


@dataclass(frozen=True, slots=True)
class VerifiedLaunchCapability:
    launch_id: UUID
    service: str
    module: str
    pid: int
    creation_time: str
    role: ServiceRole | None
    epoch_id: UUID
    ordinal: int
    key_id: str | None
    admission_sha256: str
    bound_ids: tuple[UUID, ...]


_current: VerifiedLaunchCapability | None = None


def register_verified_launch(capability: VerifiedLaunchCapability) -> None:
    global _current
    if _current is not None:
        raise ValueError("credential_launch_denied")
    _current = capability


def current_verified_launch() -> VerifiedLaunchCapability | None:
    return _current
