"""Immutable acknowledged snapshots of ownership reserved before HTTP body reads."""

from dataclasses import dataclass
from uuid import UUID

from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.temporary_contracts import TemporaryBinding

INTAKE_STATES = {"open": 1, "closed": 2, "cleaning": 3, "cleaned": 4}


@dataclass(frozen=True)
class UploadIntakeClaim:
    id: UUID
    source: SourceIdentity
    user_id: UUID
    new_document: bool
    binding: TemporaryBinding
    generation: int | None = None
    revision: int = 1
    state: str = "open"
    original_attempt_id: UUID | None = None
    attached: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.id) is not UUID
            or type(self.user_id) is not UUID
            or type(self.source) is not SourceIdentity
            or type(self.binding) is not TemporaryBinding
            or type(self.new_document) is not bool
            or type(self.attached) is not bool
            or (self.original_attempt_id is not None and type(self.original_attempt_id) is not UUID)
        ):
            raise TypeError("invalid intake identity")
        if (self.new_document and self.generation is not None) or (
            not self.new_document and (type(self.generation) is not int or self.generation < 1)
        ):
            raise ValueError("invalid intake generation")
        if self.attached and self.original_attempt_id is None:
            raise ValueError("invalid intake attachment")
        if type(self.state) is not str or self.state not in INTAKE_STATES:
            raise ValueError("invalid intake state")
        expected = (
            INTAKE_STATES[self.state]
            + int(self.original_attempt_id is not None)
            + int(self.attached)
        )
        if type(self.revision) is not int or self.revision != expected:
            raise ValueError("invalid intake revision")
