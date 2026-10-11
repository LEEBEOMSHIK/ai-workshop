"""Opt-in original DB tests: shared outer rollback, no DB/account/store creation.

Requires migration0060 already applied by the main operator. This harness rejects
outer COMMIT and uses one SQL connection: it proves sequential transactional
behavior, not committed concurrent-winner/replay races or real worker transport.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import async_sessionmaker

from ai_workshop.config import Settings
from ai_workshop.labs.rag.conversations.access import ConversationAccess
from ai_workshop.labs.rag.conversations.attachment_models import ConversationAttachmentRecord
from ai_workshop.labs.rag.conversations.draft_service import AttachmentDraftService
from ai_workshop.labs.rag.conversations.models import (
    AttachmentDraftRecord,
    ConversationRecord,
    ConversationStartRecord,
    ConversationTurnRecord,
)
from ai_workshop.labs.rag.conversations.repository import SqlAlchemyConversationRepository
from ai_workshop.labs.rag.conversations.schemas import ConversationStart
from ai_workshop.labs.rag.conversations.service import ConversationService
from ai_workshop.labs.rag.domains.models import RagDomainRecord
from ai_workshop.labs.rag.domains.repository import (
    SqlAlchemyDomainConfigurationProvider,
    SqlAlchemyDomainRepository,
)
from ai_workshop.labs.rag.domains.service import DomainService
from ai_workshop.labs.rag.executions.repository import SqlAlchemyExecutionRecorder
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.shared.db import create_engine
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.conversations.test_service import response

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_ORIGINAL_FIRST_QUESTION") != "1",
        reason="Explicit original first-question rollback verification is required.",
    ),
]


class SyntheticExecutor:
    def __init__(self):
        self.executions = 0

    async def preflight(self, **values):
        # Scope authority is real DomainService/SQL; this fixture does not test
        # the concrete pipeline's generation acceptance policy or model runtime.
        return None

    async def execute(self, **values):
        self.executions += 1
        return response()


@pytest.fixture
async def original() -> AsyncIterator[SimpleNamespace]:
    root = Path(__file__).resolve().parents[6]
    settings = Settings(_env_file=root / ".env")
    engine = create_engine(settings)

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(_connection: Connection) -> None:
        raise AssertionError("Original first-question verification must never COMMIT.")

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                assert (
                    await connection.scalar(text("SELECT version_num FROM alembic_version"))
                    == "0060_first_question"
                ), "Apply migration0060 separately before this opt-in verification."
                sessions = async_sessionmaker(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )
                async with sessions() as session:
                    actor = await session.scalar(
                        select(UserRecord.id)
                        .where(UserRecord.role == "owner", UserRecord.is_active.is_(True))
                        .limit(1)
                    )
                    assert actor is not None, "An existing active owner is required."
                    domain = await session.scalar(
                        select(RagDomainRecord)
                        .where(RagDomainRecord.active_connection_version_id.is_not(None))
                        .limit(1)
                    )
                    assert domain is not None, "An existing active RAG domain is required."
                    domains = DomainService(
                        SqlAlchemyDomainRepository(session),
                        SqlAlchemyDomainConfigurationProvider(session, settings, actor_id=actor),
                    )
                    view = await domains.detail_for_actor(domain.slug, actor)
                    assert view.ready and view.allowed_workspace_ids, (
                        "The existing domain must be ready."
                    )
                    executor = SyntheticExecutor()

                    async def final_authority(slug: str, actor_id) -> None:
                        async with sessions() as authority_session:
                            await DomainService(
                                SqlAlchemyDomainRepository(authority_session),
                                SqlAlchemyDomainConfigurationProvider(
                                    authority_session, settings, actor_id=actor_id
                                ),
                            ).detail_for_actor(slug, actor_id)

                    service = ConversationService(
                        SqlAlchemyConversationRepository(sessions),
                        ConversationAccess(sessions),
                        domains,
                        executor,
                        recorder=SqlAlchemyExecutionRecorder(sessions),
                        final_authority=final_authority,
                    )
                    drafts = AttachmentDraftService(sessions, settings)
                    yield SimpleNamespace(
                        sessions=sessions,
                        service=service,
                        drafts=drafts,
                        actor=actor,
                        slug=domain.slug,
                        domain=domain.id,
                        connection=domain.active_connection_version_id,
                        workspaces=list(view.allowed_workspace_ids),
                        executor=executor,
                        final_authority=final_authority,
                    )
                    await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            finally:
                await transaction.rollback()
                assert not connection.in_transaction()
    finally:
        await engine.dispose()


def first_request(case, **changes):
    return ConversationStart(
        request_id=uuid4(),
        query="Synthetic scope policy question?",
        connection_version_id=case.connection,
        workspace_ids=case.workspaces,
        **changes,
    )


@pytest.mark.parametrize("revoke_owner", [False, True])
async def test_original_final_authority_uses_fresh_savepoint_after_audit_commit(
    original, revoke_owner
):
    case = original
    request = first_request(case)
    executions = 0
    async with case.sessions.begin() as request_session:
        domains = DomainService(
            SqlAlchemyDomainRepository(request_session),
            SqlAlchemyDomainConfigurationProvider(
                request_session, case.drafts.settings, actor_id=case.actor
            ),
        )

        async def execute(**values):
            nonlocal executions
            executions += 1
            if revoke_owner:
                # This temporary authority change is inside the guarded outer
                # rollback transaction. No committed owner/account mutation.
                actor = await request_session.get(UserRecord, case.actor)
                actor.is_active = False
            await request_session.commit()  # Same boundary as real generation audit.
            assert not request_session.in_transaction()
            with pytest.raises(InvalidRequestError):
                await domains.detail_for_actor(case.slug, case.actor)
            return response()

        service = ConversationService(
            SqlAlchemyConversationRepository(case.sessions),
            ConversationAccess(case.sessions),
            domains,
            SimpleNamespace(preflight=SyntheticExecutor().preflight, execute=execute),
            recorder=SqlAlchemyExecutionRecorder(case.sessions),
            final_authority=case.final_authority,
        )
        if revoke_owner:
            with pytest.raises(AppError) as denied:
                await service.start(case.slug, case.actor, request)
            assert denied.value.status_code == 404
        else:
            accepted = await service.start(case.slug, case.actor, request)
            assert accepted.turns[-1].status == "completed" and not accepted.turns[-1].redacted
    assert executions == 1
    async with case.sessions() as session:
        ledger = await session.get(
            ConversationStartRecord, (case.actor, case.domain, request.request_id)
        )
        turn = await session.get(ConversationTurnRecord, ledger.first_turn_id)
        assert turn.status == "completed" and turn.response is not None
    assert case.sessions.kw["bind"].in_transaction(), "Only the outer rollback must remain."
    if not revoke_owner:
        replay = await case.service.start(case.slug, case.actor, request)
        assert replay.id == accepted.id and executions == 1 and case.executor.executions == 0


async def test_original_atomic_no_draft_replay_title_acl_and_deleted_fence(original):
    case = original
    request = first_request(case)
    first = await case.service.start(case.slug, case.actor, request)
    replay = await case.service.start(case.slug, case.actor, request)
    assert first.id == replay.id and case.executor.executions == 1
    assert len(first.turns) == 1 and first.title_origin == "auto"
    assert (
        await case.service.start_status(case.slug, case.actor, request.request_id)
    ).id == first.id
    with pytest.raises(AppError) as conflict:
        await case.service.start(
            case.slug,
            case.actor,
            request.model_copy(update={"query": "Changed synthetic question?"}),
        )
    assert conflict.value.status_code == 409
    # Only the newly created synthetic turn is changed. An unavailable selected
    # source exercises real SQL visibility for detail/list/replay/manual titles.
    async with case.sessions.begin() as session:
        turn = await session.get(ConversationTurnRecord, first.turns[0].id)
        original_request = dict(turn.request)
        turn.request = {**original_request, "document_ids": [str(uuid4())]}
    renamed = await case.service.rename(
        case.slug, case.actor, first.id, "Synthetic manual title", first.revision
    )
    assert renamed.turns[0].redacted and renamed.title == "접근할 수 없는 대화"
    hidden = await case.service.start(case.slug, case.actor, request)
    assert hidden.title == renamed.title and hidden.turns[0].query == ""
    listed = next(
        item
        for item in await case.service.list_for_actor(case.slug, case.actor)
        if item.id == first.id
    )
    assert listed.title == renamed.title
    async with case.sessions.begin() as session:
        turn = await session.get(ConversationTurnRecord, first.turns[0].id)
        turn.request = original_request
    await case.service.delete(case.slug, case.actor, first.id, renamed.revision)
    with pytest.raises(AppError) as gone:
        await case.service.start(case.slug, case.actor, request)
    assert gone.value.status_code == 410 and case.executor.executions == 1


async def test_original_draft_busy_failure_binding_and_replay(original):
    case = original
    created = await case.drafts.create_draft(case.slug, case.actor, uuid4())
    async with case.drafts.sessions() as session:
        context = await case.drafts.context(session, case.slug, case.actor)
        spaces = await case.drafts._spaces(session, context, case.actor)
        assert spaces, "An existing owner private attachment workspace is required."
    attachment_id = await case.drafts.reserve_draft(
        case.slug, created.id, case.actor, spaces[0].id, created.revision
    )
    current = await case.drafts.detail_draft(case.slug, case.actor, created.id)
    current = await case.drafts.exclude(
        case.slug, case.actor, created.id, attachment_id, current.revision
    )
    request = first_request(case, draft_id=created.id, draft_revision=current.revision)
    with pytest.raises(AppError) as busy:
        await case.service.start(case.slug, case.actor, request)
    assert busy.value.code == "draft_upload_busy"
    async with case.sessions() as session:
        assert (
            await session.get(
                ConversationStartRecord, (case.actor, case.domain, request.request_id)
            )
            is None
        )
    await case.drafts.fail(attachment_id)
    await case.drafts.confirm_upload_termination(attachment_id)
    first = await case.service.start(case.slug, case.actor, request)
    replay = await case.service.start(case.slug, case.actor, request)
    assert first.id == replay.id and case.executor.executions == 1
    bound = await case.drafts.detail_draft(case.slug, case.actor, created.id)
    assert bound.state == "bound" and bound.bound_conversation_id == first.id
    async with case.sessions() as session:
        row = await session.get(ConversationAttachmentRecord, attachment_id)
        assert row.conversation_id == first.id and row.draft_id is None
        assert row.excluded_at is not None and row.upload_terminated_at is not None


async def test_original_cancel_expire_and_legacy_writer_fence(original):
    case = original
    created = await case.drafts.create_draft(case.slug, case.actor, uuid4())
    abandoned = await case.drafts.abandon(case.slug, case.actor, created.id, created.revision)
    assert (
        await case.drafts.abandon(case.slug, case.actor, created.id, created.revision)
    ) == abandoned
    expiring = await case.drafts.create_draft(case.slug, case.actor, uuid4())
    async with case.sessions.begin() as session:
        row = await session.get(AttachmentDraftRecord, expiring.id)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert (await case.drafts.detail_draft(case.slug, case.actor, expiring.id)).state == "expired"
    legacy_id = uuid4()
    async with case.sessions.begin() as session:
        now = datetime.now(UTC)
        session.add(
            ConversationRecord(
                id=legacy_id,
                owner_id=case.actor,
                domain_id=case.domain,
                title="Synthetic old draft",
                revision=1,
                created_at=now,
                updated_at=now,
                legacy_state="draft_pending",
                title_origin="legacy",
            )
        )
    assert legacy_id not in {
        item.id for item in await case.service.list_for_actor(case.slug, case.actor)
    }
    with pytest.raises(AppError) as blocked:
        await case.service.rename(case.slug, case.actor, legacy_id, "Blocked synthetic title", 1)
    assert blocked.value.code == "legacy_draft_required"
    restored = await case.drafts.restore_legacy(case.slug, case.actor, legacy_id)
    assert restored.legacy_conversation_id == legacy_id
    assert (await case.drafts.restore_legacy(case.slug, case.actor, legacy_id)).id == restored.id
