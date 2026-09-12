from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from ai_workshop.platform.publishing.domain import PublicationAction, PublicationCommand
from ai_workshop.platform.publishing.package import StudySnapshot, canonical_bytes, decode_snapshot
from ai_workshop.shared.errors import AppError

_PUBLIC_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _is_valid_command(command: object) -> bool:
    if type(command) is not PublicationCommand:
        return False
    try:
        PublicationCommand(
            slug=command.slug,
            sequence=command.sequence,
            request_id=command.request_id,
            action=command.action,
            snapshot=command.snapshot,
            digest=command.digest,
        )
    except AppError:
        return False
    return True


def _invalid_projection() -> AppError:
    return AppError(
        "publishing_projection_invalid",
        "The public study projection state is invalid.",
        422,
    )


def _not_found() -> AppError:
    return AppError("not_found", "The requested resource was not found.", 404)


@dataclass(frozen=True, slots=True)
class PublicStudyProjection:
    slug: str
    sequence: int = 0
    last_command: PublicationCommand | None = None
    snapshot: StudySnapshot | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self._has_valid_state():
            raise _invalid_projection()

    def apply(self, command: PublicationCommand) -> PublicStudyProjection:
        if not self._has_valid_state() or not _is_valid_command(command):
            raise AppError("publishing_command_conflict", "The publication command conflicts.", 409)
        if command.slug != self.slug or command.sequence < self.sequence:
            raise AppError("publishing_command_conflict", "The publication command conflicts.", 409)
        if command.sequence == self.sequence:
            if command == self.last_command:
                return self
            raise AppError("publishing_command_conflict", "The publication command conflicts.", 409)
        if (
            self.last_command is not None
            and command.request_id == self.last_command.request_id
            and command != self.last_command
        ):
            raise AppError("publishing_command_conflict", "The publication command conflicts.", 409)
        return replace(
            self,
            sequence=command.sequence,
            last_command=command,
            snapshot=(command.snapshot if command.action is PublicationAction.PUBLISH else None),
        )

    def read(self) -> StudySnapshot:
        if (
            not self._has_valid_state()
            or self.snapshot is None
            or self.last_command is None
            or self.last_command.digest is None
        ):
            raise _not_found()
        try:
            return decode_snapshot(
                canonical_bytes(self.snapshot),
                expected_digest=self.last_command.digest,
            )
        except AppError:
            raise _not_found() from None

    def _has_valid_state(self) -> bool:
        if (
            not isinstance(self.slug, str)
            or _PUBLIC_SLUG.fullmatch(self.slug) is None
            or type(self.sequence) is not int
            or self.sequence < 0
        ):
            return False
        if self.sequence == 0:
            return self.last_command is None and self.snapshot is None
        last_command = self.last_command
        if (
            not isinstance(last_command, PublicationCommand)
            or not _is_valid_command(last_command)
            or last_command.slug != self.slug
            or last_command.sequence != self.sequence
        ):
            return False
        if last_command.action is PublicationAction.PUBLISH:
            return self.snapshot is not None and self.snapshot == last_command.snapshot
        return self.snapshot is None
