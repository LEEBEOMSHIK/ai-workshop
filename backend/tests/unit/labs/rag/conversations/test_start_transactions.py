"""Repository/UoW and SQL migration boundaries without any live database."""

from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from ai_workshop.labs.rag.conversations.attachment_models import ConversationAttachmentRecord
from ai_workshop.labs.rag.conversations.domain import Conversation, reserve_turn
from ai_workshop.labs.rag.conversations.models import AttachmentDraftRecord, ConversationStartRecord
from ai_workshop.labs.rag.conversations.repository import SqlAlchemyConversationRepository
from ai_workshop.labs.rag.conversations.schemas import ConversationStart
from ai_workshop.labs.rag.domains.repository import SqlAlchemyDomainRepository


class TransactionStore:
    """An application transaction boundary; SQL statements return bounded fixtures."""

    def __init__(self, connection, draft=None, attachments=(), fail_ledger=False):
        self.committed = []
        self.connection, self.draft, self.attachments = connection, draft, list(attachments)
        self.fail_ledger = fail_ledger
        self.active = False

    @asynccontextmanager
    async def begin(self):
        pending = []
        initial = deepcopy((self.draft, self.attachments))
        self.active = True

        async def scalar(statement):
            selected = list(statement.column_descriptions)[0].get("entity")
            if selected is AttachmentDraftRecord:
                return self.draft
            if selected is ConversationAttachmentRecord:
                return self.attachments[0] if self.attachments else None
            return self.connection

        async def scalars(statement):
            selected = list(statement.column_descriptions)[0].get("entity")
            return SimpleNamespace(
                all=lambda: self.attachments if selected is ConversationAttachmentRecord else []
            )

        def add(row):
            pending.append(row)

        async def flush():
            if self.fail_ledger and any(
                isinstance(row, ConversationStartRecord) for row in pending
            ):
                raise RuntimeError("synthetic ledger write failure")

        session = SimpleNamespace(
            get=AsyncMock(return_value=None), scalar=scalar, scalars=scalars, add=add, flush=flush
        )
        try:
            yield session
        except BaseException:
            self.draft, self.attachments = initial
            raise
        else:
            self.committed.extend(pending)
        finally:
            self.active = False


def acceptance(draft=None):
    now = datetime.now(UTC)
    request = ConversationStart(
        request_id=uuid4(),
        query="Synthetic question?",
        connection_version_id=uuid4(),
        workspace_ids=[uuid4()],
        **({"draft_id": draft.id, "draft_revision": draft.revision} if draft else {}),
    )
    item = Conversation(uuid4(), uuid4(), uuid4(), "Synthetic question?", 1, now, now)
    reserve_turn(item, request.turn_request(), "scope", now)
    item.title_origin, item.title_source_turn_id = "auto", item.turns[0].id
    return item, request


@pytest.mark.asyncio
async def test_no_draft_ledger_failure_rolls_back_conversation_and_first_turn(monkeypatch):
    item, request = acceptance()
    store = TransactionStore(request.connection_version_id, fail_ledger=True)
    monkeypatch.setattr(
        SqlAlchemyDomainRepository,
        "workspace_options_for_actor",
        AsyncMock(return_value=[SimpleNamespace(id=id) for id in request.workspace_ids]),
    )
    with pytest.raises(RuntimeError, match="synthetic ledger write failure"):
        await SqlAlchemyConversationRepository(store).start(item, request, "digest")
    assert store.committed == [] and not store.active


@pytest.mark.asyncio
async def test_draft_ledger_failure_rolls_back_bound_state_and_attachment_fk(monkeypatch):
    from datetime import timedelta

    from ai_workshop.labs.rag.conversations import draft_service

    draft = SimpleNamespace(
        id=uuid4(),
        state="open",
        revision=2,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        bound_conversation_id=None,
        updated_at=datetime.now(UTC),
        start_request_id=None,
        start_request_digest=None,
    )
    row = SimpleNamespace(id=uuid4(), draft_id=draft.id, conversation_id=None)
    item, request = acceptance(draft)
    store = TransactionStore(
        request.connection_version_id, draft=draft, attachments=[row], fail_ledger=True
    )
    monkeypatch.setattr(
        SqlAlchemyDomainRepository,
        "workspace_options_for_actor",
        AsyncMock(return_value=[SimpleNamespace(id=id) for id in request.workspace_ids]),
    )
    monkeypatch.setattr(draft_service, "require_bindable_attachments", AsyncMock())
    with pytest.raises(RuntimeError):
        await SqlAlchemyConversationRepository(store).start(item, request, "digest")
    assert store.committed == [] and store.draft.state == "open"
    assert (
        store.attachments[0].draft_id == draft.id and store.attachments[0].conversation_id is None
    )


def test_additive_migration_emits_constraints_and_downgrade_fence_first():
    path = Path(__file__).resolve().parents[5] / "alembic/versions/0060_first_question.py"
    spec = spec_from_file_location("migration0060", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        module.upgrade()
    upgrade = output.getvalue()
    assert "pk_rag_conversation_starts PRIMARY KEY(owner_id,domain_id,request_id)" in upgrade
    assert (
        "ck_rag_attachment_parent CHECK((conversation_id IS NULL)<>(draft_id IS NULL))" in upgrade
    )
    assert "DELETE FROM" not in upgrade and "DROP TABLE" not in upgrade
    output.seek(0)
    output.truncate()
    with Operations.context(context):
        module.downgrade()
    downgrade = output.getvalue()
    assert downgrade.index("first-question data exists") < downgrade.index("DROP INDEX")
    assert "EXISTS(SELECT 1 FROM rag_conversation_starts)" in downgrade
    assert "EXISTS(SELECT 1 FROM rag_attachment_drafts)" in downgrade


@pytest.mark.asyncio
async def test_platform_intake_and_rag_reservation_share_rollback_boundary(monkeypatch):
    from ai_workshop.platform.assets import intake_repository
    from ai_workshop.platform.assets.temporary_contracts import TemporaryBinding

    store = TransactionStore(uuid4())
    monkeypatch.setattr(intake_repository, "require_workspace_write", AsyncMock())

    class DeniedParticipant(intake_repository.UploadIntakeJournal):
        async def reserved(self, session, claim):
            assert store.active
            raise RuntimeError("synthetic RAG reservation denied")

    with pytest.raises(RuntimeError, match="synthetic RAG reservation denied"):
        await DeniedParticipant(store).reserve(
            user_id=uuid4(),
            workspace_id=uuid4(),
            document_id=None,
            binding=TemporaryBinding("synthetic", uuid4()),
        )
    assert store.committed == [] and not store.active


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["replay", "conflict", "deleted", "different-key"])
async def test_draft_lock_wait_rechecks_winner_ledger_before_bound_rejection(monkeypatch, outcome):
    from ai_workshop.shared.errors import AppError

    draft = SimpleNamespace(id=uuid4(), revision=2, state="bound", bound_conversation_id=uuid4())
    item, request = acceptance(draft)
    store = TransactionStore(request.connection_version_id, draft=draft)
    repository = SqlAlchemyConversationRepository(store)
    winner = deepcopy(item)
    winner.id = draft.bound_conversation_id
    second = {
        "replay": winner,
        "conflict": AppError("conversation_request_conflict", "Synthetic conflict", 409),
        "deleted": AppError("conversation_start_deleted", "Synthetic tombstone", 410),
        "different-key": None,
    }[outcome]
    repository._find_start = AsyncMock(side_effect=[None, second])
    monkeypatch.setattr(
        SqlAlchemyDomainRepository,
        "workspace_options_for_actor",
        AsyncMock(return_value=[SimpleNamespace(id=id) for id in request.workspace_ids]),
    )
    if outcome == "replay":
        accepted, created = await repository.start(item, request, "original-digest")
        assert accepted.id == winner.id and not created
    else:
        with pytest.raises(AppError) as error:
            await repository.start(item, request, "original-digest")
        assert (
            error.value.code
            == {
                "conflict": "conversation_request_conflict",
                "deleted": "conversation_start_deleted",
                "different-key": "draft_already_bound",
            }[outcome]
        )
    assert repository._find_start.await_count == 2
    assert repository._find_start.call_args.args[1:] == (
        item.owner_id,
        item.domain_id,
        request.request_id,
        "original-digest",
    )
    assert store.committed == []


@pytest.mark.asyncio
async def test_delayed_upload_excluded_manifest_waits_for_writer_join_before_start(monkeypatch):
    import asyncio
    from datetime import timedelta

    from ai_workshop.labs.rag.conversations.draft_service import AttachmentDraftService
    from ai_workshop.shared.errors import AppError

    now = datetime.now(UTC)
    draft = SimpleNamespace(
        id=uuid4(),
        state="open",
        revision=1,
        expires_at=now + timedelta(hours=1),
        bound_conversation_id=None,
        updated_at=now,
        created_at=now,
        legacy_conversation_id=None,
        start_request_id=None,
        start_request_digest=None,
    )
    row = SimpleNamespace(
        id=uuid4(),
        draft_id=draft.id,
        conversation_id=None,
        state="uploading",
        upload_terminated_at=None,
        excluded_at=None,
        owner_id=uuid4(),
    )
    item, request = acceptance(draft)
    row.owner_id = item.owner_id
    store = TransactionStore(request.connection_version_id, draft=draft, attachments=[row])
    service = AttachmentDraftService(store, SimpleNamespace(rag_attachment_draft_ttl_minutes=1440))
    service.context = AsyncMock(return_value=SimpleNamespace())
    service._draft = AsyncMock(return_value=draft)
    release = asyncio.Event()

    async def writer():
        await release.wait()
        row.state = "failed"
        row.upload_terminated_at = datetime.now(UTC)

    task = asyncio.create_task(writer())
    try:
        excluded = await service.exclude("demo", item.owner_id, draft.id, row.id, 1)
        request = request.model_copy(update={"draft_revision": excluded.revision})
        monkeypatch.setattr(
            SqlAlchemyDomainRepository,
            "workspace_options_for_actor",
            AsyncMock(return_value=[SimpleNamespace(id=id) for id in request.workspace_ids]),
        )
        with pytest.raises(AppError) as error:
            await SqlAlchemyConversationRepository(store).start(item, request, "digest")
        assert error.value.code == "draft_upload_busy" and store.committed == []
        assert row.conversation_id is None and draft.state == "open"
        # The controlled writer acknowledgement models the transport finally/join
        # boundary; the separate transport test exercises its real service method.
        release.set()
        await task
        # TransactionStore rollback restores copies. Retain the current manifest,
        # then publish the joined writer's acknowledgement onto that fixture row.
        store.attachments[0].state = row.state
        store.attachments[0].upload_terminated_at = row.upload_terminated_at
        accepted, created = await SqlAlchemyConversationRepository(store).start(
            item, request, "digest"
        )
        assert created and accepted.id == item.id and store.draft.state == "bound"
        assert store.attachments[0].conversation_id == item.id
    finally:
        release.set()
        await task
