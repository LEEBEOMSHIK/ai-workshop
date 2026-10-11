from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.conversations.attachment_lifecycle import (
    reconcile_deleted_attachments,
    reconcile_owner_cleanup,
)
from ai_workshop.labs.rag.conversations.attachment_models import ConversationAttachmentRecord
from ai_workshop.labs.rag.conversations.domain import Conversation, Turn, TurnStatus
from ai_workshop.labs.rag.conversations.models import (
    AttachmentDraftRecord,
    ConversationRecord,
    ConversationStartRecord,
    ConversationTurnRecord,
)
from ai_workshop.labs.rag.conversations.schemas import ConversationStart
from ai_workshop.labs.rag.domains.models import RagDomainRecord
from ai_workshop.labs.rag.executions.models import ExecutionRecord
from ai_workshop.shared.errors import AppError


def missing() -> AppError:
    return AppError("not_found", "The requested conversation was not found.", 404)


class SqlAlchemyConversationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def find_start(
        self, owner_id: UUID, domain_id: UUID, request_id: UUID, digest: str | None
    ) -> Conversation | None:
        async with self.sessions() as session:
            return await self._find_start(session, owner_id, domain_id, request_id, digest)

    async def _find_start(
        self,
        session: AsyncSession,
        owner_id: UUID,
        domain_id: UUID,
        request_id: UUID,
        digest: str | None,
    ) -> Conversation | None:
        ledger = await session.get(ConversationStartRecord, (owner_id, domain_id, request_id))
        if ledger is None:
            return None
        if digest is not None and ledger.request_digest != digest:
            raise AppError("conversation_request_conflict", "The request ID is already used.", 409)
        record = await session.get(ConversationRecord, ledger.conversation_id)
        if record is None or record.deleted_at is not None:
            raise AppError(
                "conversation_start_deleted", "The accepted conversation was deleted.", 410
            )
        return await self._load(session, record)

    async def start(
        self, item: Conversation, request: ConversationStart, digest: str
    ) -> tuple[Conversation, bool]:
        try:
            async with self.sessions.begin() as session:
                replay = await self._find_start(
                    session, item.owner_id, item.domain_id, request.request_id, digest
                )
                if replay is not None:
                    return replay, False
                from ai_workshop.labs.rag.domains.repository import SqlAlchemyDomainRepository

                active_connection = await session.scalar(
                    select(RagDomainRecord.active_connection_version_id).where(
                        RagDomainRecord.id == item.domain_id
                    )
                )
                if active_connection != request.connection_version_id:
                    raise AppError(
                        "domain_connection_changed", "The domain connection changed.", 409
                    )
                options = await SqlAlchemyDomainRepository(session).workspace_options_for_actor(
                    item.owner_id, tuple(request.workspace_ids)
                )
                if {option.id for option in options} != set(request.workspace_ids):
                    raise missing()
                draft = None
                attachments = []
                if request.draft_id is not None:
                    # Start only reads storage authority. It never acquires source
                    # write locks after its RAG parent lock (upload uses source first).
                    draft = await session.scalar(
                        select(AttachmentDraftRecord)
                        .where(
                            AttachmentDraftRecord.id == request.draft_id,
                            AttachmentDraftRecord.owner_id == item.owner_id,
                            AttachmentDraftRecord.domain_id == item.domain_id,
                        )
                        .with_for_update()
                    )
                    if draft is None:
                        raise missing()
                    # A concurrent winner may have committed while this request
                    # waited for the draft lock. Replay/digest/tombstone semantics
                    # take precedence over the now-bound manifest state.
                    replay = await self._find_start(
                        session, item.owner_id, item.domain_id, request.request_id, digest
                    )
                    if replay is not None:
                        return replay, False
                    if draft.state == "bound":
                        raise AppError(
                            "draft_already_bound",
                            f"The draft is already bound: {draft.bound_conversation_id}",
                            409,
                        )
                    if draft.state != "open" or draft.expires_at <= datetime.now(UTC):
                        raise AppError(
                            "draft_unavailable", "The attachment draft is no longer open.", 410
                        )
                    if draft.revision != request.draft_revision:
                        raise AppError(
                            "draft_revision_conflict", "The attachment manifest changed.", 409
                        )
                    attachments = list(
                        (
                            await session.scalars(
                                select(ConversationAttachmentRecord)
                                .where(
                                    ConversationAttachmentRecord.draft_id == draft.id,
                                )
                                .order_by(ConversationAttachmentRecord.id)
                                .with_for_update()
                            )
                        ).all()
                    )
                    from ai_workshop.labs.rag.conversations.draft_service import (
                        require_bindable_attachments,
                    )

                    await require_bindable_attachments(session, item.owner_id, attachments)
                record = ConversationRecord(
                    id=item.id,
                    owner_id=item.owner_id,
                    domain_id=item.domain_id,
                    title=item.title,
                    revision=item.revision,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    title_origin=item.title_origin,
                    title_derivation=item.title_derivation,
                    title_policy_version=item.title_policy_version,
                    title_error_code=item.title_error_code,
                    legacy_state="active",
                )
                session.add(record)
                await session.flush()
                await self._persist(session, record, item)
                await session.flush()
                record.title_source_turn_id = item.title_source_turn_id
                session.add(
                    ConversationStartRecord(
                        owner_id=item.owner_id,
                        domain_id=item.domain_id,
                        request_id=request.request_id,
                        request_digest=digest,
                        conversation_id=item.id,
                        first_turn_id=item.turns[0].id,
                        created_at=item.created_at,
                    )
                )
                if draft is not None:
                    draft.state, draft.bound_conversation_id = "bound", item.id
                    draft.start_request_id, draft.start_request_digest = request.request_id, digest
                    draft.updated_at = item.created_at
                    for attachment in attachments:
                        attachment.conversation_id, attachment.draft_id = item.id, None
                await session.flush()
            return item, True
        except IntegrityError:
            replay = await self.find_start(
                item.owner_id, item.domain_id, request.request_id, digest
            )
            if replay is not None:
                return replay, False
            if request.draft_id is not None:
                async with self.sessions() as session:
                    draft = await session.get(AttachmentDraftRecord, request.draft_id)
                    if (
                        draft
                        and draft.owner_id == item.owner_id
                        and draft.domain_id == item.domain_id
                        and draft.state == "bound"
                    ):
                        raise AppError(
                            "draft_already_bound",
                            f"The draft is already bound: {draft.bound_conversation_id}",
                            409,
                        ) from None
            raise

    async def domain_id(self, slug: str) -> UUID:
        async with self.sessions() as session:
            value = await session.scalar(
                select(RagDomainRecord.id).where(RagDomainRecord.slug == slug)
            )
            if value is None:
                raise missing()
            return value

    async def list(self, owner_id: UUID, domain_id: UUID) -> list[Conversation]:
        async with self.sessions.begin() as session:
            await reconcile_owner_cleanup(session, owner_id, domain_id)
            records = (
                await session.scalars(
                    select(ConversationRecord)
                    .where(
                        ConversationRecord.owner_id == owner_id,
                        ConversationRecord.domain_id == domain_id,
                        ConversationRecord.deleted_at.is_(None),
                        select(ConversationTurnRecord.id)
                        .where(ConversationTurnRecord.conversation_id == ConversationRecord.id)
                        .exists(),
                    )
                    .order_by(ConversationRecord.updated_at.desc(), ConversationRecord.id)
                )
            ).all()
            return [await self._load(session, record) for record in records]

    async def record_termination(
        self,
        owner_id: UUID,
        domain_id: UUID,
        id: UUID,
        turn_id: UUID,
    ) -> None:
        """Only acknowledge termination on an owned tombstone; never restore payloads."""
        async with self.sessions.begin() as session:
            record = await session.scalar(
                select(ConversationRecord)
                .where(
                    ConversationRecord.id == id,
                    ConversationRecord.owner_id == owner_id,
                    ConversationRecord.domain_id == domain_id,
                    ConversationRecord.deleted_at.is_not(None),
                )
                .with_for_update()
            )
            if record is None:
                return
            turn = await session.scalar(
                select(ConversationTurnRecord).where(
                    ConversationTurnRecord.conversation_id == id,
                    ConversationTurnRecord.id == turn_id,
                )
            )
            if turn is not None:
                turn.execution_terminated = True
                await session.flush()
                await reconcile_deleted_attachments(session, record)

    @asynccontextmanager
    async def locked(
        self, owner_id: UUID, domain_id: UUID, id: UUID
    ) -> AsyncIterator[Conversation]:
        async with self.sessions.begin() as session:
            record = await session.scalar(
                select(ConversationRecord)
                .where(
                    ConversationRecord.id == id,
                    ConversationRecord.owner_id == owner_id,
                    ConversationRecord.domain_id == domain_id,
                    ConversationRecord.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if record is None:
                raise missing()
            item = await self._load(session, record)
            yield item
            await self._persist(session, record, item)

    async def _load(self, session: AsyncSession, record: ConversationRecord) -> Conversation:
        rows = (
            await session.scalars(
                select(ConversationTurnRecord)
                .where(
                    ConversationTurnRecord.conversation_id == record.id,
                )
                .order_by(ConversationTurnRecord.sequence)
            )
        ).all()
        executions = {
            e.turn_id: e
            for e in (
                await session.scalars(
                    select(ExecutionRecord).where(ExecutionRecord.turn_id.in_([r.id for r in rows]))
                )
            ).all()
        }
        item = self._conversation(record)
        if record.legacy_state != "active":
            item.attachment_draft_id = await session.scalar(
                select(AttachmentDraftRecord.id).where(
                    AttachmentDraftRecord.legacy_conversation_id == record.id
                )
            )
        item.turns = [
            Turn(
                row.id,
                row.request_id,
                row.sequence,
                cast(TurnStatus, row.status),
                row.query,
                row.request,
                row.request_digest,
                row.scope_identity,
                row.segment,
                row.created_at,
                row.updated_at,
                row.response,
                row.error_code,
                [UUID(value) for value in row.dependencies],
                row.execution_terminated,
                executions[row.id].id if row.id in executions else None,
                executions[row.id].complete if row.id in executions else None,
            )
            for row in rows
        ]
        return item

    async def _persist(
        self, session: AsyncSession, record: ConversationRecord, item: Conversation
    ) -> None:
        rows = (
            await session.scalars(
                select(ConversationTurnRecord).where(
                    ConversationTurnRecord.conversation_id == record.id
                )
            )
        ).all()
        record.title, record.revision = item.title, item.revision
        record.updated_at, record.deleted_at = item.updated_at, item.deleted_at
        record.title_origin, record.title_derivation = item.title_origin, item.title_derivation
        record.title_policy_version, record.title_error_code = (
            item.title_policy_version,
            item.title_error_code,
        )
        record.legacy_state = item.legacy_state
        by_id = {row.id: row for row in rows}
        for turn in item.turns:
            target = by_id.get(turn.id)
            if target is None:
                target = ConversationTurnRecord(id=turn.id, conversation_id=record.id)
                session.add(target)
            target.request_id, target.sequence = turn.request_id, turn.sequence
            target.status, target.query = turn.status, turn.query
            target.request, target.request_digest = turn.request, turn.request_digest
            target.scope_identity, target.segment = turn.scope_identity, turn.segment
            target.created_at, target.updated_at = turn.created_at, turn.updated_at
            target.response, target.error_code = turn.response, turn.error_code
            target.dependencies = [str(value) for value in turn.dependencies]
            target.execution_terminated = turn.execution_terminated
        if item.deleted_at is not None:
            await session.flush()
            await reconcile_deleted_attachments(session, record)

    @staticmethod
    def _conversation(record: ConversationRecord) -> Conversation:
        return Conversation(
            record.id,
            record.owner_id,
            record.domain_id,
            record.title,
            record.revision,
            record.created_at,
            record.updated_at,
            record.deleted_at,
            title_origin=cast(Literal["auto", "manual", "legacy"], record.title_origin),
            title_source_turn_id=record.title_source_turn_id,
            title_derivation=cast(
                Literal["extracted", "preserved", "fallback"] | None, record.title_derivation
            ),
            title_policy_version=record.title_policy_version,
            title_error_code=record.title_error_code,
            legacy_state=record.legacy_state,
        )
