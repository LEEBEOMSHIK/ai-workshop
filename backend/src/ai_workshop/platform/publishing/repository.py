from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, cast

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.platform.publishing.domain import (
    PublicationAction,
    PublicationCommand,
    PublicationDraft,
)
from ai_workshop.platform.publishing.models import (
    PublishingCommandRow,
    PublishingRevisionRow,
    PublishingStudyRow,
)
from ai_workshop.platform.publishing.package import (
    StudyContent,
    StudySnapshot,
    canonical_bytes,
    decode_snapshot,
    snapshot_digest,
)
from ai_workshop.platform.publishing.public_store import PublicationReceipt
from ai_workshop.shared.errors import AppError


@dataclass(frozen=True, slots=True)
class PendingPublicationCommand:
    action: PublicationAction
    expected_revision: int
    expected_digest: str
    request_id: str


@dataclass(frozen=True, slots=True)
class PublishingStudy:
    draft: PublicationDraft = field(repr=False)
    desired_action: PublicationAction | None = None
    applied_sequence: int = 0
    applied_action: PublicationAction | None = None
    applied_revision: int | None = None
    last_request_id: str | None = None
    delivery_error_code: str | None = None
    pending_command: PendingPublicationCommand | None = None

    @property
    def snapshot(self) -> StudySnapshot:
        return self.draft.snapshot

    @property
    def sequence(self) -> int:
        return self.draft.sequence

    @property
    def digest(self) -> str:
        return snapshot_digest(self.draft.snapshot)

    @property
    def delivery_pending(self) -> bool:
        return self.draft.sequence > self.applied_sequence


@dataclass(frozen=True, slots=True)
class PreparedPublication:
    state: PublishingStudy
    command: PublicationCommand = field(repr=False)
    should_deliver: bool


class PublishingRepository(Protocol):
    async def create(self, content: StudyContent) -> PublishingStudy: ...

    async def get(self, slug: str) -> PublishingStudy | None: ...

    async def list(self, *, offset: int, limit: int) -> tuple[PublishingStudy, ...]: ...

    async def update(
        self,
        slug: str,
        *,
        expected_revision: int,
        content: StudyContent,
    ) -> PublishingStudy: ...

    async def prepare_initial_publication(
        self,
        content: StudyContent,
        *,
        expected_digest: str,
        request_id: str,
    ) -> PreparedPublication: ...

    async def prepare_command(
        self,
        slug: str,
        *,
        action: PublicationAction,
        expected_revision: int,
        expected_digest: str,
        request_id: str,
    ) -> PreparedPublication: ...

    async def acknowledge(self, receipt: PublicationReceipt) -> PublishingStudy: ...

    async def record_delivery_failure(
        self,
        request_id: str,
        *,
        error_code: str,
    ) -> PublishingStudy: ...


def _not_found() -> AppError:
    return AppError("not_found", "The requested resource was not found.", 404)


def _request_conflict() -> AppError:
    return AppError(
        "publishing_request_conflict",
        "The publishing request conflicts with an earlier request.",
        409,
    )


def _store_unavailable() -> AppError:
    return AppError(
        "publishing_private_store_unavailable",
        "The publishing store is unavailable.",
        503,
    )


def _fingerprint(
    *,
    slug: str,
    action: PublicationAction,
    expected_revision: int,
    expected_digest: str,
    request_id: str,
) -> str:
    payload = json.dumps(
        {
            "action": action.value,
            "expected_digest": expected_digest,
            "expected_revision": expected_revision,
            "request_id": request_id,
            "slug": slug,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _snapshot_from_revision(row: PublishingRevisionRow) -> StudySnapshot:
    try:
        snapshot = decode_snapshot(row.canonical_bytes, expected_digest=row.digest)
        if snapshot.model_dump(mode="json") != row.snapshot:
            raise ValueError("snapshot representations differ")
        if snapshot.content.slug != row.slug or snapshot.revision != row.revision:
            raise ValueError("snapshot identity differs")
    except (AppError, TypeError, ValueError):
        raise _store_unavailable() from None
    return snapshot


def _new_study_rows(
    content: StudyContent,
    *,
    now: datetime,
) -> tuple[PublishingStudyRow, PublishingRevisionRow]:
    snapshot = StudySnapshot(revision=1, content=content)
    study = PublishingStudyRow(
        slug=content.slug,
        current_revision=1,
        sequence=0,
        approved_digest=None,
        applied_sequence=0,
        applied_action=None,
        applied_revision=None,
        created_at=now,
        updated_at=now,
    )
    revision = PublishingRevisionRow(
        slug=content.slug,
        revision=1,
        snapshot=snapshot.model_dump(mode="json"),
        canonical_bytes=canonical_bytes(snapshot),
        digest=snapshot_digest(snapshot),
        created_at=now,
    )
    return study, revision


def _command_from_row(row: PublishingCommandRow) -> PublicationCommand:
    try:
        action = PublicationAction(row.action)
        snapshot = None
        digest = None
        if action is PublicationAction.PUBLISH:
            if row.export_payload is None:
                raise ValueError("publish payload missing")
            snapshot = decode_snapshot(row.export_payload, expected_digest=row.expected_digest)
            digest = row.expected_digest
        return PublicationCommand(
            slug=row.slug,
            sequence=row.sequence,
            request_id=row.request_id,
            action=action,
            snapshot=snapshot,
            digest=digest,
        )
    except (AppError, TypeError, ValueError):
        raise _store_unavailable() from None


def _state_from_rows(
    study: PublishingStudyRow,
    revision: PublishingRevisionRow,
    command: PublishingCommandRow | None,
) -> PublishingStudy:
    snapshot = _snapshot_from_revision(revision)
    try:
        desired_action = PublicationAction(command.action) if command is not None else None
        applied_action = (
            PublicationAction(study.applied_action)
            if study.applied_action is not None
            else None
        )
        draft = PublicationDraft(
            snapshot=snapshot,
            approved_digest=study.approved_digest,
            sequence=study.sequence,
        )
        pending_command = None
        if study.sequence > study.applied_sequence:
            if command is None or command.applied_at is not None:
                raise ValueError("pending command is missing")
            pending_command = PendingPublicationCommand(
                action=PublicationAction(command.action),
                expected_revision=command.expected_revision,
                expected_digest=command.expected_digest,
                request_id=command.request_id,
            )
    except (AppError, TypeError, ValueError):
        raise _store_unavailable() from None
    return PublishingStudy(
        draft=draft,
        desired_action=desired_action,
        applied_sequence=study.applied_sequence,
        applied_action=applied_action,
        applied_revision=study.applied_revision,
        last_request_id=command.request_id if command is not None else None,
        delivery_error_code=command.delivery_error_code if command is not None else None,
        pending_command=pending_command,
    )


def _study_statement() -> Select[
    tuple[PublishingStudyRow, PublishingRevisionRow, PublishingCommandRow | None]
]:
    statement = (
        select(PublishingStudyRow, PublishingRevisionRow, PublishingCommandRow)
        .join(
            PublishingRevisionRow,
            (PublishingRevisionRow.slug == PublishingStudyRow.slug)
            & (PublishingRevisionRow.revision == PublishingStudyRow.current_revision),
        )
        .outerjoin(
            PublishingCommandRow,
            (PublishingCommandRow.slug == PublishingStudyRow.slug)
            & (PublishingCommandRow.sequence == PublishingStudyRow.sequence),
        )
    )
    return cast(
        Select[
            tuple[
                PublishingStudyRow,
                PublishingRevisionRow,
                PublishingCommandRow | None,
            ]
        ],
        statement,
    )


async def _locked_study_rows(
    session: AsyncSession,
    slug: str,
) -> tuple[PublishingStudyRow, PublishingRevisionRow, PublishingCommandRow | None] | None:
    study = await session.scalar(
        select(PublishingStudyRow)
        .where(PublishingStudyRow.slug == slug)
        .with_for_update()
    )
    if study is None:
        return None
    revision = await session.get(
        PublishingRevisionRow,
        (study.slug, study.current_revision),
    )
    command = None
    if study.sequence > 0:
        command = await session.scalar(
            select(PublishingCommandRow).where(
                PublishingCommandRow.slug == study.slug,
                PublishingCommandRow.sequence == study.sequence,
            )
        )
    if revision is None or (study.sequence > 0 and command is None):
        raise _store_unavailable()
    return study, revision, command


class SqlAlchemyPublishingRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create(self, content: StudyContent) -> PublishingStudy:
        now = datetime.now(UTC)
        study, revision = _new_study_rows(content, now=now)
        try:
            async with self.sessions.begin() as session:
                session.add(study)
                await session.flush()
                session.add(revision)
                await session.flush()
        except IntegrityError:
            raise AppError(
                "publishing_slug_conflict",
                "The public slug already exists.",
                409,
            ) from None
        except SQLAlchemyError:
            raise _store_unavailable() from None
        return _state_from_rows(study, revision, None)

    async def get(self, slug: str) -> PublishingStudy | None:
        try:
            async with self.sessions() as session:
                row = (
                    await session.execute(
                        _study_statement().where(PublishingStudyRow.slug == slug)
                    )
                ).one_or_none()
        except SQLAlchemyError:
            raise _store_unavailable() from None
        return _state_from_rows(*row) if row is not None else None

    async def list(self, *, offset: int, limit: int) -> tuple[PublishingStudy, ...]:
        try:
            async with self.sessions() as session:
                rows = (
                    await session.execute(
                        _study_statement()
                        .order_by(PublishingStudyRow.slug)
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
        except SQLAlchemyError:
            raise _store_unavailable() from None
        return tuple(_state_from_rows(*row) for row in rows)

    async def update(
        self,
        slug: str,
        *,
        expected_revision: int,
        content: StudyContent,
    ) -> PublishingStudy:
        try:
            async with self.sessions.begin() as session:
                row = await _locked_study_rows(session, slug)
                if row is None:
                    raise _not_found()
                study, revision, command = row
                current = _state_from_rows(study, revision, command)
                revised = current.draft.revise(content, expected_revision=expected_revision)
                now = datetime.now(UTC)
                next_revision = PublishingRevisionRow(
                    slug=slug,
                    revision=revised.snapshot.revision,
                    snapshot=revised.snapshot.model_dump(mode="json"),
                    canonical_bytes=canonical_bytes(revised.snapshot),
                    digest=snapshot_digest(revised.snapshot),
                    created_at=now,
                )
                session.add(next_revision)
                study.current_revision = revised.snapshot.revision
                study.approved_digest = None
                study.updated_at = now
                await session.flush()
                return _state_from_rows(study, next_revision, command)
        except AppError:
            raise
        except IntegrityError:
            raise AppError(
                "publishing_revision_conflict",
                "The draft has changed.",
                409,
            ) from None
        except SQLAlchemyError:
            raise _store_unavailable() from None

    async def prepare_command(
        self,
        slug: str,
        *,
        action: PublicationAction,
        expected_revision: int,
        expected_digest: str,
        request_id: str,
    ) -> PreparedPublication:
        try:
            fingerprint = _fingerprint(
                slug=slug,
                action=action,
                expected_revision=expected_revision,
                expected_digest=expected_digest,
                request_id=request_id,
            )
        except (UnicodeError, TypeError, ValueError):
            raise _request_conflict() from None
        try:
            async with self.sessions.begin() as session:
                row = await _locked_study_rows(session, slug)
                if row is None:
                    raise _not_found()
                study, revision, current_command = row
                return await self._prepare_command_locked(
                    session,
                    study,
                    revision,
                    current_command,
                    action=action,
                    expected_revision=expected_revision,
                    expected_digest=expected_digest,
                    request_id=request_id,
                    fingerprint=fingerprint,
                )
        except AppError:
            raise
        except IntegrityError:
            return await self._resolve_request_race(request_id, fingerprint)
        except SQLAlchemyError:
            raise _store_unavailable() from None

    async def prepare_initial_publication(
        self,
        content: StudyContent,
        *,
        expected_digest: str,
        request_id: str,
    ) -> PreparedPublication:
        try:
            snapshot = StudySnapshot(revision=1, content=content)
            if snapshot_digest(snapshot) != expected_digest:
                raise _request_conflict()
            fingerprint = _fingerprint(
                slug=content.slug,
                action=PublicationAction.PUBLISH,
                expected_revision=1,
                expected_digest=expected_digest,
                request_id=request_id,
            )
        except (UnicodeError, TypeError, ValueError):
            raise _request_conflict() from None
        try:
            async with self.sessions.begin() as session:
                row = await _locked_study_rows(session, content.slug)
                if row is None:
                    study, revision = _new_study_rows(content, now=datetime.now(UTC))
                    session.add(study)
                    await session.flush()
                    session.add(revision)
                    await session.flush()
                    current_command = None
                else:
                    study, revision, current_command = row
                return await self._prepare_initial_locked(
                    session,
                    study,
                    revision,
                    current_command,
                    expected_digest=expected_digest,
                    request_id=request_id,
                    fingerprint=fingerprint,
                )
        except AppError:
            raise
        except IntegrityError:
            return await self._resolve_initial_race(
                content.slug,
                expected_digest=expected_digest,
                request_id=request_id,
                fingerprint=fingerprint,
            )
        except SQLAlchemyError:
            raise _store_unavailable() from None

    async def _prepare_initial_locked(
        self,
        session: AsyncSession,
        study: PublishingStudyRow,
        revision: PublishingRevisionRow,
        current_command: PublishingCommandRow | None,
        *,
        expected_digest: str,
        request_id: str,
        fingerprint: str,
    ) -> PreparedPublication:
        is_fresh = (
            study.current_revision == 1
            and revision.digest == expected_digest
            and study.sequence == 0
            and study.applied_sequence == 0
            and study.applied_action is None
            and current_command is None
        )
        is_exact_replay = (
            study.current_revision == 1
            and revision.digest == expected_digest
            and study.sequence == 1
            and current_command is not None
            and current_command.request_id == request_id
        )
        if not (is_fresh or is_exact_replay):
            raise _request_conflict()
        return await self._prepare_command_locked(
            session,
            study,
            revision,
            current_command,
            action=PublicationAction.PUBLISH,
            expected_revision=1,
            expected_digest=expected_digest,
            request_id=request_id,
            fingerprint=fingerprint,
        )

    async def _prepare_command_locked(
        self,
        session: AsyncSession,
        study: PublishingStudyRow,
        revision: PublishingRevisionRow,
        current_command: PublishingCommandRow | None,
        *,
        action: PublicationAction,
        expected_revision: int,
        expected_digest: str,
        request_id: str,
        fingerprint: str,
    ) -> PreparedPublication:
        existing = await session.get(PublishingCommandRow, request_id)
        if existing is not None:
            return self._prepared_existing(
                study,
                revision,
                current_command,
                existing,
                fingerprint,
            )

        current = _state_from_rows(study, revision, current_command)
        if current.digest != expected_digest:
            raise AppError(
                "publishing_digest_conflict",
                "The public package has changed.",
                409,
            )
        if action is PublicationAction.PUBLISH:
            approved = current.draft.approve(
                expected_revision=expected_revision,
                expected_digest=expected_digest,
            )
            draft, publication = approved.publish(request_id=request_id)
        else:
            if expected_revision != current.snapshot.revision:
                raise AppError(
                    "publishing_revision_conflict",
                    "The draft has changed.",
                    409,
                )
            draft, publication = current.draft.withdraw(request_id=request_id)
        now = datetime.now(UTC)
        new_command = PublishingCommandRow(
            request_id=request_id,
            slug=study.slug,
            sequence=publication.sequence,
            action=action.value,
            expected_revision=expected_revision,
            expected_digest=expected_digest,
            request_fingerprint=fingerprint,
            export_payload=(
                canonical_bytes(publication.snapshot)
                if publication.snapshot is not None
                else None
            ),
            receipt_slug=None,
            receipt_sequence=None,
            receipt_request_id=None,
            receipt_action=None,
            delivery_error_code=None,
            applied_at=None,
            created_at=now,
            updated_at=now,
        )
        session.add(new_command)
        study.sequence = draft.sequence
        study.approved_digest = draft.approved_digest
        study.updated_at = now
        await session.flush()
        return PreparedPublication(
            state=_state_from_rows(study, revision, new_command),
            command=publication,
            should_deliver=True,
        )

    async def _resolve_initial_race(
        self,
        slug: str,
        *,
        expected_digest: str,
        request_id: str,
        fingerprint: str,
    ) -> PreparedPublication:
        try:
            async with self.sessions.begin() as session:
                row = await _locked_study_rows(session, slug)
                if row is None:
                    raise _store_unavailable()
                return await self._prepare_initial_locked(
                    session,
                    *row,
                    expected_digest=expected_digest,
                    request_id=request_id,
                    fingerprint=fingerprint,
                )
        except AppError:
            raise
        except SQLAlchemyError:
            raise _store_unavailable() from None

    def _prepared_existing(
        self,
        study: PublishingStudyRow,
        revision: PublishingRevisionRow,
        current_command: PublishingCommandRow | None,
        existing: PublishingCommandRow,
        fingerprint: str,
    ) -> PreparedPublication:
        if existing.request_fingerprint != fingerprint:
            raise _request_conflict()
        state = _state_from_rows(study, revision, current_command)
        return PreparedPublication(
            state=state,
            command=_command_from_row(existing),
            should_deliver=(
                existing.sequence == study.sequence and existing.applied_at is None
            ),
        )

    async def _resolve_request_race(
        self,
        request_id: str,
        fingerprint: str,
    ) -> PreparedPublication:
        try:
            async with self.sessions() as session:
                existing = await session.get(PublishingCommandRow, request_id)
                if existing is None:
                    raise _store_unavailable()
                row = (
                    await session.execute(
                        _study_statement().where(PublishingStudyRow.slug == existing.slug)
                    )
                ).one()
                study, revision, current_command = row
                return self._prepared_existing(
                    study,
                    revision,
                    current_command,
                    existing,
                    fingerprint,
                )
        except AppError:
            raise
        except SQLAlchemyError:
            raise _store_unavailable() from None

    async def acknowledge(self, receipt: PublicationReceipt) -> PublishingStudy:
        try:
            async with self.sessions.begin() as session:
                command = await session.get(
                    PublishingCommandRow,
                    receipt.request_id,
                    with_for_update=True,
                )
                if command is None or (
                    receipt.slug,
                    receipt.sequence,
                    receipt.request_id,
                    receipt.action.value,
                ) != (command.slug, command.sequence, command.request_id, command.action):
                    raise AppError(
                        "publishing_receipt_conflict",
                        "The publication receipt conflicts.",
                        409,
                    )
                row = await _locked_study_rows(session, command.slug)
                if row is None:
                    raise _store_unavailable()
                study, revision, current_command = row
                now = datetime.now(UTC)
                if command.applied_at is None:
                    command.receipt_slug = receipt.slug
                    command.receipt_sequence = receipt.sequence
                    command.receipt_request_id = receipt.request_id
                    command.receipt_action = receipt.action.value
                    command.applied_at = now
                command.delivery_error_code = None
                command.updated_at = now
                if receipt.sequence > study.applied_sequence:
                    study.applied_sequence = receipt.sequence
                    study.applied_action = receipt.action.value
                    study.applied_revision = (
                        command.expected_revision
                        if receipt.action is PublicationAction.PUBLISH
                        else None
                    )
                    study.updated_at = now
                await session.flush()
                return _state_from_rows(study, revision, current_command)
        except AppError:
            raise
        except SQLAlchemyError:
            raise _store_unavailable() from None

    async def record_delivery_failure(
        self,
        request_id: str,
        *,
        error_code: str,
    ) -> PublishingStudy:
        safe_code = error_code[:100] if error_code else "publishing_delivery_failed"
        try:
            async with self.sessions.begin() as session:
                command = await session.get(
                    PublishingCommandRow,
                    request_id,
                    with_for_update=True,
                )
                if command is None:
                    raise _request_conflict()
                if command.applied_at is None:
                    command.delivery_error_code = safe_code
                    command.updated_at = datetime.now(UTC)
                row = await _locked_study_rows(session, command.slug)
                if row is None:
                    raise _store_unavailable()
                await session.flush()
                return _state_from_rows(*row)
        except AppError:
            raise
        except SQLAlchemyError:
            raise _store_unavailable() from None
