"""Owner-scoped attachment drafts. Cancellation never deletes originals."""

from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ai_workshop.labs.rag.conversations.attachment_models import ConversationAttachmentRecord
from ai_workshop.labs.rag.conversations.attachment_service import (
    AttachmentOptionsResponse,
    ConversationAttachmentService,
    eligible_attachment_workspace,
)
from ai_workshop.labs.rag.conversations.models import (
    AttachmentDraftRecord,
    ConversationRecord,
    ConversationTurnRecord,
)
from ai_workshop.labs.rag.domains.repository import (
    SqlAlchemyDomainConfigurationProvider,
    SqlAlchemyDomainRepository,
)
from ai_workshop.labs.rag.domains.service import DomainLibraryContext, DomainService
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import workspace_write_allowed
from ai_workshop.shared.errors import AppError


class DraftManifest(Protocol):
    state: str
    revision: int
    expires_at: datetime
    updated_at: datetime


def require_open(draft: DraftManifest, revision: int | None, now: datetime) -> None:
    if draft.state != "open" or draft.expires_at <= now:
        raise AppError("draft_unavailable", "The attachment draft is no longer open.", 410)
    if revision is not None and draft.revision != revision:
        raise AppError("draft_revision_conflict", "The attachment manifest changed.", 409)


def touch_manifest(draft: DraftManifest, now: datetime, ttl_minutes: int) -> None:
    draft.revision += 1
    draft.updated_at, draft.expires_at = now, now + timedelta(minutes=ttl_minutes)


def upload_busy(row: ConversationAttachmentRecord) -> bool:
    # Manifest exclusion is not proof that the upload transport has stopped.
    return row.upload_terminated_at is None


async def require_bindable_attachments(
    session: AsyncSession, actor_id: UUID, rows: list[ConversationAttachmentRecord]
) -> None:
    if any(upload_busy(row) for row in rows):
        raise AppError("draft_upload_busy", "Wait for attachment uploads to finish.", 409)
    for row in rows:
        if row.excluded_at is not None:
            continue
        workspace = await session.scalar(
            select(WorkspaceRecord).where(
                WorkspaceRecord.id == row.workspace_id,
                workspace_write_allowed(actor_id),
            )
        )
        if workspace is None or not eligible_attachment_workspace(workspace, actor_id):
            raise AppError(
                "attachment_workspace_forbidden", "The attachment storage permission changed.", 403
            )


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class DraftResponse(BaseModel):
    id: UUID
    state: str
    revision: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    bound_conversation_id: UUID | None
    legacy_conversation_id: UUID | None

    @classmethod
    def from_record(cls, row: AttachmentDraftRecord) -> "DraftResponse":
        return cls(**{name: getattr(row, name) for name in cls.model_fields})


class AttachmentDraftService(ConversationAttachmentService):
    async def context(
        self, session: AsyncSession, slug: str, actor_id: UUID
    ) -> DomainLibraryContext:
        return await DomainService(
            SqlAlchemyDomainRepository(session),
            SqlAlchemyDomainConfigurationProvider(session, self.settings, actor_id=actor_id),
        ).resolve_library(slug=slug, actor_id=actor_id)

    async def _draft(
        self,
        session: AsyncSession,
        context: DomainLibraryContext,
        id: UUID,
        actor_id: UUID,
        *,
        lock: bool,
    ) -> AttachmentDraftRecord:
        query = select(AttachmentDraftRecord).where(
            AttachmentDraftRecord.id == id,
            AttachmentDraftRecord.owner_id == actor_id,
            AttachmentDraftRecord.domain_id == context.domain.id,
        )
        if lock:
            query = query.with_for_update()
        row = await session.scalar(query.execution_options(populate_existing=True))
        if row is None:
            raise AppError("not_found", "The attachment draft was not found.", 404)
        return row

    async def authorize(
        self,
        session: AsyncSession,
        slug: str,
        conversation_id: UUID,
        actor_id: UUID,
        *,
        lock: bool = False,
    ) -> DomainLibraryContext:
        context = await self.context(session, slug, actor_id)
        row = await self._draft(session, context, conversation_id, actor_id, lock=lock)
        if lock:
            require_open(row, None, datetime.now(UTC))
        return context

    def parent_predicate(self, id: UUID) -> ColumnElement[bool]:
        return ConversationAttachmentRecord.draft_id == id

    async def create_draft(self, slug: str, actor_id: UUID, request_id: UUID) -> DraftResponse:
        async def find(session: AsyncSession, domain_id: UUID) -> AttachmentDraftRecord | None:
            return cast(
                AttachmentDraftRecord | None,
                await session.scalar(
                    select(AttachmentDraftRecord).where(
                        AttachmentDraftRecord.owner_id == actor_id,
                        AttachmentDraftRecord.domain_id == domain_id,
                        AttachmentDraftRecord.create_request_id == request_id,
                    )
                ),
            )

        try:
            async with self.sessions.begin() as session:
                context = await self.context(session, slug, actor_id)
                row = await find(session, context.domain.id)
                if row is None:
                    now = datetime.now(UTC)
                    row = AttachmentDraftRecord(
                        id=uuid4(),
                        owner_id=actor_id,
                        domain_id=context.domain.id,
                        state="open",
                        revision=1,
                        create_request_id=request_id,
                        created_at=now,
                        updated_at=now,
                        expires_at=now
                        + timedelta(minutes=self.settings.rag_attachment_draft_ttl_minutes),
                    )
                    session.add(row)
                    await session.flush()
                return DraftResponse.from_record(row)
        except IntegrityError:
            async with self.sessions() as session:
                context = await self.context(session, slug, actor_id)
                row = await find(session, context.domain.id)
                if row is None:
                    raise
                return DraftResponse.from_record(row)

    async def detail_draft(self, slug: str, actor_id: UUID, id: UUID) -> DraftResponse:
        async with self.sessions.begin() as session:
            context = await self.context(session, slug, actor_id)
            row = await self._draft(session, context, id, actor_id, lock=True)
            await self._expire(session, row)
            return DraftResponse.from_record(row)

    async def abandon(self, slug: str, actor_id: UUID, id: UUID, revision: int) -> DraftResponse:
        async with self.sessions.begin() as session:
            context = await self.context(session, slug, actor_id)
            row = await self._draft(session, context, id, actor_id, lock=True)
            if row.state == "abandoned":
                return DraftResponse.from_record(row)
            require_open(row, revision, datetime.now(UTC))
            row.state = "abandoned"
            touch_manifest(row, datetime.now(UTC), self.settings.rag_attachment_draft_ttl_minutes)
            await self._cleanup(session, row)
            return DraftResponse.from_record(row)

    async def exclude(
        self, slug: str, actor_id: UUID, id: UUID, attachment_id: UUID, revision: int
    ) -> DraftResponse:
        async with self.sessions.begin() as session:
            context = await self.context(session, slug, actor_id)
            draft = await self._draft(session, context, id, actor_id, lock=True)
            require_open(draft, None, datetime.now(UTC))
            row = await session.scalar(
                select(ConversationAttachmentRecord)
                .where(
                    ConversationAttachmentRecord.id == attachment_id,
                    ConversationAttachmentRecord.draft_id == id,
                    ConversationAttachmentRecord.owner_id == actor_id,
                )
                .with_for_update()
            )
            if row is None:
                raise AppError("not_found", "The attachment was not found.", 404)
            if row.excluded_at is None:
                require_open(draft, revision, datetime.now(UTC))
                row.excluded_at = datetime.now(UTC)
                touch_manifest(
                    draft, row.excluded_at, self.settings.rag_attachment_draft_ttl_minutes
                )
            return DraftResponse.from_record(draft)

    async def reserve_draft(
        self, slug: str, id: UUID, actor_id: UUID, workspace_id: UUID, revision: int
    ) -> UUID:
        # Platform reservation owns the actual source lock. This initial manifest
        # reservation only reads write permission, then locks parent -> attachment.
        async with self.sessions.begin() as session:
            context = await self.context(session, slug, actor_id)
            allowed = {row.id for row in await self._spaces(session, context, actor_id)}
            if workspace_id not in allowed:
                raise AppError(
                    "attachment_workspace_forbidden", "Select an allowed private space.", 403
                )
            draft = await self._draft(session, context, id, actor_id, lock=True)
            require_open(draft, revision, datetime.now(UTC))
            now = datetime.now(UTC)
            row = ConversationAttachmentRecord(
                id=uuid4(),
                draft_id=id,
                owner_id=actor_id,
                workspace_id=workspace_id,
                state="uploading",
                created_at=now,
            )
            session.add(row)
            touch_manifest(draft, now, self.settings.rag_attachment_draft_ttl_minutes)
            return row.id

    async def domain_options(self, slug: str, actor_id: UUID) -> AttachmentOptionsResponse:
        from ai_workshop.labs.rag.conversations.attachment_service import (
            AttachmentOptionsResponse,
            AttachmentWorkspaceResponse,
        )

        async with self.sessions() as session:
            context = await self.context(session, slug, actor_id)
            rows = await self._spaces(session, context, actor_id)
            return AttachmentOptionsResponse(
                workspaces=[
                    AttachmentWorkspaceResponse(id=row.id, name=row.name, kind=row.kind)
                    for row in rows
                ],
                reason_code=None if rows else "no_private_attachment_workspace",
            )

    async def _expire(self, session: AsyncSession, row: AttachmentDraftRecord) -> None:
        if row.state == "open" and row.expires_at <= datetime.now(UTC):
            row.state, row.updated_at = "expired", datetime.now(UTC)
        if row.state in {"abandoned", "expired"}:
            await self._cleanup(session, row)

    @staticmethod
    async def _cleanup(session: AsyncSession, row: AttachmentDraftRecord) -> None:
        from ai_workshop.labs.rag.conversations.attachment_lifecycle import (
            reconcile_draft_attachments,
        )

        await reconcile_draft_attachments(session, row)

    async def reconcile(self) -> None:
        async with self.sessions.begin() as session:
            rows = (
                await session.scalars(
                    select(AttachmentDraftRecord)
                    .where(AttachmentDraftRecord.state.in_(("open", "expired", "abandoned")))
                    .order_by(AttachmentDraftRecord.id)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                await self._expire(session, row)

    async def restore_legacy(
        self, slug: str, actor_id: UUID, conversation_id: UUID
    ) -> DraftResponse:
        # First commit a one-way write fence under conversation -> attachment locks.
        async with self.sessions.begin() as session:
            context = await self.context(session, slug, actor_id)
            conversation = await session.scalar(
                select(ConversationRecord)
                .where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.owner_id == actor_id,
                    ConversationRecord.domain_id == context.domain.id,
                    ConversationRecord.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if conversation is None:
                raise AppError("not_found", "The previous draft was not found.", 404)
            if await session.scalar(
                select(ConversationTurnRecord.id)
                .where(ConversationTurnRecord.conversation_id == conversation_id)
                .limit(1)
            ):
                raise AppError(
                    "legacy_conversation_has_questions",
                    "This conversation already has questions.",
                    409,
                )
            conversation.legacy_state = "draft_pending"
            await session.scalars(
                select(ConversationAttachmentRecord)
                .where(ConversationAttachmentRecord.conversation_id == conversation_id)
                .order_by(ConversationAttachmentRecord.id)
                .with_for_update()
            )
            domain_id = context.domain.id
        try:
            async with self.sessions.begin() as session:
                # No conversation lock here: the persisted fence rejects old writers.
                context = await self.context(session, slug, actor_id)
                existing = await session.scalar(
                    select(AttachmentDraftRecord)
                    .where(
                        AttachmentDraftRecord.legacy_conversation_id == conversation_id,
                        AttachmentDraftRecord.owner_id == actor_id,
                        AttachmentDraftRecord.domain_id == domain_id,
                    )
                    .with_for_update()
                )
                if existing is not None:
                    return DraftResponse.from_record(existing)
                now = datetime.now(UTC)
                draft = AttachmentDraftRecord(
                    id=uuid4(),
                    owner_id=actor_id,
                    domain_id=domain_id,
                    create_request_id=uuid4(),
                    state="open",
                    revision=1,
                    created_at=now,
                    updated_at=now,
                    expires_at=now
                    + timedelta(minutes=self.settings.rag_attachment_draft_ttl_minutes),
                    legacy_conversation_id=conversation_id,
                )
                session.add(draft)
                await session.flush()
                rows = list(
                    (
                        await session.scalars(
                            select(ConversationAttachmentRecord)
                            .where(ConversationAttachmentRecord.conversation_id == conversation_id)
                            .order_by(ConversationAttachmentRecord.id)
                            .with_for_update()
                        )
                    ).all()
                )
                if any(row.upload_terminated_at is None for row in rows):
                    raise AppError(
                        "legacy_upload_busy", "Wait for previous attachment writers to finish.", 409
                    )
                for row in rows:
                    row.conversation_id, row.draft_id = None, draft.id
                return DraftResponse.from_record(draft)
        except IntegrityError:
            async with self.sessions() as session:
                context = await self.context(session, slug, actor_id)
                existing = await session.scalar(
                    select(AttachmentDraftRecord).where(
                        AttachmentDraftRecord.legacy_conversation_id == conversation_id,
                        AttachmentDraftRecord.owner_id == actor_id,
                        AttachmentDraftRecord.domain_id == context.domain.id,
                    )
                )
                if existing is None:
                    raise
                return DraftResponse.from_record(existing)
