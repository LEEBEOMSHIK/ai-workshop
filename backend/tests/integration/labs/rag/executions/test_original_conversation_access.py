"""Current SQL authority against existing answers, with every change rolled back.

No HTTP/browser revoke, provider call, new user or durable permission change.
"""

import os
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

import ai_workshop.main  # noqa: F401 -- register existing SQLAlchemy mappings
from ai_workshop.labs.rag.conversations.access import ConversationAccess, source_identities
from ai_workshop.labs.rag.conversations.models import ConversationRecord, ConversationTurnRecord
from ai_workshop.labs.rag.conversations.repository import SqlAlchemyConversationRepository
from ai_workshop.labs.rag.domains.models import RagDomainRecord
from ai_workshop.labs.rag.generation.codex_approval_models import EvidenceApprovalStateRecord
from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
from ai_workshop.platform.assets.models import DocumentRecord
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.domain import MembershipRole, WorkspaceKind
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.shared.db import create_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_ORIGINAL_CONVERSATION_ACCESS") != "1",
        reason="Explicit original conversation-access rollback verification is required.",
    ),
]


async def authority_hashes(connection: AsyncConnection) -> tuple[object, ...]:
    # Constant identifiers only. Neither account nor approval row values leave SQL.
    result: list[object] = []
    for table in ("workspace_memberships", "rag_evidence_approval_states"):
        result.append(
            await connection.scalar(
                text(
                    "SELECT md5(coalesce(string_agg(md5(row_to_json(t)::text), '' "
                    "ORDER BY md5(row_to_json(t)::text)), '')) FROM " + table + " t"
                )
            )
        )
    return tuple(result)


@pytest.mark.parametrize("revocation", ["workspace_read", "external_evidence"])
async def test_existing_answer_rechecks_current_authority(
    monkeypatch: pytest.MonkeyPatch, revocation: str
) -> None:
    for key in list(os.environ):
        if key.upper().startswith("AI_WORKSHOP_"):
            monkeypatch.delenv(key)
    settings = load_original_settings(Path(__file__).resolve().parents[6])
    engine = create_engine(settings)
    engine.sync_engine.hide_parameters = True

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(_connection: Connection) -> None:
        raise AssertionError("Original access verification must never COMMIT.")

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            before = await authority_hashes(connection)
            try:
                assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "0063_rag_numeric_proof"
                ), "Require existing schema0063; do not migrate in this test."
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                )
                async with sessions() as session:
                    record = await session.scalar(
                        select(ConversationRecord)
                        .join(RagDomainRecord, RagDomainRecord.id == ConversationRecord.domain_id)
                        .join(UserRecord, UserRecord.id == ConversationRecord.owner_id)
                        .where(
                            RagDomainRecord.slug == "asset-management",
                            ConversationRecord.deleted_at.is_(None),
                            UserRecord.role == "owner",
                            UserRecord.is_active.is_(True),
                            select(ConversationTurnRecord.id)
                            .where(
                                ConversationTurnRecord.conversation_id == ConversationRecord.id,
                                ConversationTurnRecord.status == "completed",
                                ConversationTurnRecord.response.is_not(None),
                            )
                            .exists(),
                        )
                        .order_by(ConversationRecord.updated_at.desc(), ConversationRecord.id)
                    )
                    assert record is not None, "An existing owner answer is required."
                    conversation = await SqlAlchemyConversationRepository(sessions)._load(
                        session, record
                    )
                turn = next(
                    turn
                    for turn in reversed(conversation.turns)
                    if turn.status == "completed" and source_identities(turn.response)
                )
                assert turn.response is not None
                generation = turn.response.get("generation")
                assert isinstance(generation, dict) and generation.get("status") == "answered", (
                    "An existing answered turn with real source identities is required."
                )
                access = ConversationAccess(sessions)
                actor = conversation.owner_id
                assert await access.visible(actor, turn), "Internal positive control failed."
                assert await access.visible(actor, turn, external=True), (
                    "External positive control failed; do not grant approval in this test."
                )
                document_id, revision_id, _ = sorted(source_identities(turn.response))[0]
                if revocation == "workspace_read":
                    async with sessions() as session:
                        workspace_id = await session.scalar(
                            select(WorkspaceRecord.id)
                            .join(DocumentRecord, DocumentRecord.workspace_id == WorkspaceRecord.id)
                            .where(
                                DocumentRecord.id == document_id,
                                WorkspaceRecord.kind == WorkspaceKind.COMPANY,
                            )
                        )
                    assert isinstance(workspace_id, UUID), "A company-space source is required."
                    changed = await connection.execute(
                        update(WorkspaceMembershipRecord)
                        .where(
                            WorkspaceMembershipRecord.workspace_id == workspace_id,
                            WorkspaceMembershipRecord.user_id == actor,
                        )
                        .values(
                            role=MembershipRole.MEMBER,
                            can_read=False,
                            can_write=False,
                            can_delete=False,
                        )
                    )
                    assert changed.rowcount == 1
                    assert not await access.visible(actor, turn)
                    assert not await access.visible(actor, turn, external=True)
                else:
                    changed = await connection.execute(
                        update(EvidenceApprovalStateRecord)
                        .where(
                            EvidenceApprovalStateRecord.revision_id == revision_id,
                            EvidenceApprovalStateRecord.provider == "development_codex_exec",
                        )
                        .values(status="revoked")
                    )
                    assert changed.rowcount == 1
                    assert await access.visible(actor, turn), (
                        "External revocation must preserve internal source visibility."
                    )
                    assert not await access.visible(actor, turn, external=True)
            finally:
                await transaction.rollback()
            assert await authority_hashes(connection) == before, "Authority rollback differs."
            assert await access.visible(actor, turn)
            assert await access.visible(actor, turn, external=True)
            await connection.rollback()
    finally:
        await engine.dispose()
