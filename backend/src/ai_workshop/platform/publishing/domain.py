from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum

from pydantic import ValidationError

from ai_workshop.platform.publishing.package import StudyContent, StudySnapshot, snapshot_digest
from ai_workshop.shared.errors import AppError

_PUBLIC_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _is_valid_snapshot(value: object) -> bool:
    if type(value) is not StudySnapshot:
        return False
    try:
        validated = StudySnapshot.model_validate(value.model_dump(mode="python"))
    except (ValidationError, TypeError, ValueError):
        return False
    return validated == value


def _invalid_command() -> AppError:
    return AppError(
        "publishing_command_invalid",
        "The publication command is invalid.",
        422,
    )


def _invalid_draft() -> AppError:
    return AppError(
        "publishing_draft_invalid",
        "The publication draft state is invalid.",
        422,
    )


class PublicationAction(StrEnum):
    PUBLISH = "publish"
    WITHDRAW = "withdraw"


@dataclass(frozen=True, slots=True)
class PublicationCommand:
    slug: str
    sequence: int
    request_id: str
    action: PublicationAction
    snapshot: StudySnapshot | None = field(repr=False)
    digest: str | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.slug, str)
            or _PUBLIC_SLUG.fullmatch(self.slug) is None
            or type(self.sequence) is not int
            or self.sequence < 1
            or not isinstance(self.request_id, str)
            or not self.request_id.strip()
            or not isinstance(self.action, PublicationAction)
        ):
            raise _invalid_command()

        if self.action is PublicationAction.PUBLISH:
            snapshot = self.snapshot
            if (
                not isinstance(snapshot, StudySnapshot)
                or not _is_valid_snapshot(snapshot)
                or not isinstance(self.digest, str)
                or self.slug != snapshot.content.slug
                or self.digest != snapshot_digest(snapshot)
            ):
                raise _invalid_command()
        elif self.snapshot is not None or self.digest is not None:
            raise _invalid_command()


@dataclass(frozen=True, slots=True)
class PublicationDraft:
    snapshot: StudySnapshot = field(repr=False)
    approved_digest: str | None = None
    sequence: int = 0

    def __post_init__(self) -> None:
        if (
            not _is_valid_snapshot(self.snapshot)
            or type(self.sequence) is not int
            or self.sequence < 0
            or (
                self.approved_digest is not None
                and (
                    not isinstance(self.approved_digest, str)
                    or self.approved_digest != snapshot_digest(self.snapshot)
                )
            )
        ):
            raise _invalid_draft()

    def revise(self, content: StudyContent, *, expected_revision: int) -> PublicationDraft:
        if type(expected_revision) is not int or expected_revision != self.snapshot.revision:
            raise AppError("publishing_revision_conflict", "The draft has changed.", 409)
        if content.slug != self.snapshot.content.slug:
            raise AppError("publishing_slug_conflict", "The public slug cannot be changed.", 409)
        return replace(
            self,
            snapshot=StudySnapshot(revision=self.snapshot.revision + 1, content=content),
            approved_digest=None,
        )

    def approve(self, *, expected_revision: int, expected_digest: str) -> PublicationDraft:
        if type(expected_revision) is not int or expected_revision != self.snapshot.revision:
            raise AppError("publishing_revision_conflict", "The draft has changed.", 409)
        if expected_digest != snapshot_digest(self.snapshot):
            raise AppError("publishing_digest_conflict", "The public package has changed.", 409)
        return replace(self, approved_digest=expected_digest)

    def publish(self, *, request_id: str) -> tuple[PublicationDraft, PublicationCommand]:
        digest = snapshot_digest(self.snapshot)
        if self.approved_digest != digest:
            raise AppError(
                "publishing_approval_required",
                "The current draft is not approved.",
                409,
            )
        sequence = self.sequence + 1
        command = PublicationCommand(
            slug=self.snapshot.content.slug,
            sequence=sequence,
            request_id=request_id,
            action=PublicationAction.PUBLISH,
            snapshot=self.snapshot,
            digest=digest,
        )
        return replace(self, sequence=sequence), command

    def withdraw(self, *, request_id: str) -> tuple[PublicationDraft, PublicationCommand]:
        sequence = self.sequence + 1
        command = PublicationCommand(
            slug=self.snapshot.content.slug,
            sequence=sequence,
            request_id=request_id,
            action=PublicationAction.WITHDRAW,
            snapshot=None,
            digest=None,
        )
        return replace(self, approved_digest=None, sequence=sequence), command
