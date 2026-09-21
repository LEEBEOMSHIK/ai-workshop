"""Visible, fail-closed attachment cleanup inventory. This module never deletes assets.

Jobs and provenance inventories do not certify writer termination. Their presence
therefore retains a source until the existing ownership/cleanup system resolves it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONPATH
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.conversations.attachment_models import ConversationAttachmentRecord
from ai_workshop.labs.rag.conversations.models import ConversationRecord, ConversationTurnRecord
from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity, SourceIdentity
from ai_workshop.platform.assets.provenance_repository import ProvenanceRepository
from ai_workshop.platform.jobs.models import JobRecord, JobSourceRecord


@dataclass(frozen=True)
class AttachmentCleanupDecision:
    state: Literal["cleanup_waiting", "cleanup_candidate"]
    blockers: tuple[str, ...]


def assess_attachment_cleanup(
    *,
    upload_terminated: bool,
    turns_terminated: bool,
    jobs_present: bool,
    resources: tuple[ResourceIdentity, ...],
    shared_reference: bool,
    inventory_complete: bool,
) -> AttachmentCleanupDecision:
    blockers = []
    if not inventory_complete:
        blockers.append("inventory_incomplete")
    if upload_terminated is not True:
        blockers.append("upload_termination_unconfirmed")
    if turns_terminated is not True:
        blockers.append("turn_termination_unconfirmed")
    if jobs_present:
        # Neither COMPLETED nor FAILED establishes that a worker stopped writing.
        blockers.append("ingestion_termination_unconfirmed")
    if resources:
        blockers.append("source_resources_remaining")
    if shared_reference:
        blockers.append("shared_reference_remaining")
    return AttachmentCleanupDecision(
        "cleanup_waiting" if blockers else "cleanup_candidate",
        tuple(blockers),
    )


async def reconcile_deleted_attachments(
    session: AsyncSession,
    conversation: ConversationRecord,
) -> None:
    """Caller holds conversation row lock. Lock order is conversation -> attachments."""
    if conversation.deleted_at is None:
        return
    rows = (
        await session.scalars(
            select(ConversationAttachmentRecord)
            .where(
                ConversationAttachmentRecord.conversation_id == conversation.id,
                ConversationAttachmentRecord.owner_id == conversation.owner_id,
            )
            .order_by(ConversationAttachmentRecord.id)
            .with_for_update()
        )
    ).all()
    if not rows:
        return
    unconfirmed_turn = await session.scalar(
        select(ConversationTurnRecord.id)
        .where(
            ConversationTurnRecord.conversation_id == conversation.id,
            ConversationTurnRecord.execution_terminated.is_(False),
        )
        .limit(1)
    )
    now = datetime.now(UTC)
    for row in rows:
        row.cleanup_requested_at = row.cleanup_requested_at or conversation.deleted_at
        document_id = row.document_id or row.planned_document_id
        version_id = row.asset_version_id or row.planned_version_id
        complete = (document_id is None) == (version_id is None)
        resources: tuple[ResourceIdentity, ...] = ()
        shared, jobs = False, False
        if document_id is not None and version_id is not None:
            # A relation listing is not an exhaustive participant inventory. In
            # particular, absent relations cannot prove that legacy writers or
            # resources are absent. Retain exact sources until the existing
            # provenance cleanup workflow supplies its complete bound inventory.
            complete = False
            source = SourceIdentity(row.workspace_id, document_id, version_id)
            relations = await ProvenanceRepository(session).list_for_source(source)
            resources = tuple(relation.resource for relation in relations)
            jobs = (
                await session.scalar(
                    select(JobRecord.id)
                    .where(
                        or_(
                            JobRecord.asset_version_id == version_id,
                            JobRecord.id.in_(
                                select(JobSourceRecord.job_id).where(
                                    JobSourceRecord.workspace_id == row.workspace_id,
                                    JobSourceRecord.document_id == document_id,
                                )
                            ),
                        )
                    )
                    .limit(1)
                )
                is not None
            )
            # Shared references are queried inside SQL: no other user's text is loaded.
            json_path = f'$.**.document_id ? (@ == "{document_id}")'
            referenced_turn = await session.scalar(
                select(ConversationTurnRecord.id)
                .join(
                    ConversationRecord,
                    ConversationRecord.id == ConversationTurnRecord.conversation_id,
                )
                .where(
                    ConversationRecord.id != conversation.id,
                    ConversationRecord.deleted_at.is_(None),
                    or_(
                        ConversationTurnRecord.request["document_ids"].contains([str(document_id)]),
                        func.jsonb_path_exists(
                            ConversationTurnRecord.response, cast(json_path, JSONPATH)
                        ),
                    ),
                )
                .limit(1)
            )
            referenced_attachment = await session.scalar(
                select(ConversationAttachmentRecord.id)
                .where(
                    ConversationAttachmentRecord.id != row.id,
                    or_(
                        ConversationAttachmentRecord.document_id == document_id,
                        ConversationAttachmentRecord.planned_document_id == document_id,
                    ),
                )
                .limit(1)
            )
            shared = referenced_turn is not None or referenced_attachment is not None
        elif row.intake_id is not None:
            # An intake with no exact identity needs its existing reconciliation path.
            complete = False
        decision = assess_attachment_cleanup(
            upload_terminated=row.upload_terminated_at is not None,
            turns_terminated=unconfirmed_turn is None,
            jobs_present=jobs,
            resources=resources,
            shared_reference=shared,
            inventory_complete=complete,
        )
        row.cleanup_state = decision.state
        row.cleanup_blockers = list(decision.blockers)
        row.cleanup_checked_at = now


async def reconcile_owner_cleanup(
    session: AsyncSession,
    owner_id: UUID,
    domain_id: UUID,
) -> None:
    conversations = (
        await session.scalars(
            select(ConversationRecord)
            .where(
                ConversationRecord.owner_id == owner_id,
                ConversationRecord.domain_id == domain_id,
                ConversationRecord.deleted_at.is_not(None),
            )
            .order_by(ConversationRecord.id)
            .with_for_update()
        )
    ).all()
    for conversation in conversations:
        await reconcile_deleted_attachments(session, conversation)


async def list_deleted_cleanup(
    sessions: async_sessionmaker[AsyncSession],
    owner_id: UUID,
    domain_id: UUID,
) -> list[dict[str, object]]:
    """Owner-scoped retryable inventory, containing only opaque IDs and fixed codes."""
    async with sessions.begin() as session:
        await reconcile_owner_cleanup(session, owner_id, domain_id)
        rows = (
            await session.scalars(
                select(ConversationAttachmentRecord)
                .join(
                    ConversationRecord,
                    ConversationRecord.id == ConversationAttachmentRecord.conversation_id,
                )
                .where(
                    ConversationRecord.owner_id == owner_id,
                    ConversationRecord.domain_id == domain_id,
                    ConversationRecord.deleted_at.is_not(None),
                    ConversationAttachmentRecord.owner_id == owner_id,
                )
                .order_by(ConversationAttachmentRecord.created_at, ConversationAttachmentRecord.id)
            )
        ).all()
        return [
            {
                "id": row.id,
                "conversation_id": row.conversation_id,
                "cleanup_state": row.cleanup_state,
                "blockers": row.cleanup_blockers,
                "requested_at": row.cleanup_requested_at,
                "checked_at": row.cleanup_checked_at,
            }
            for row in rows
        ]
