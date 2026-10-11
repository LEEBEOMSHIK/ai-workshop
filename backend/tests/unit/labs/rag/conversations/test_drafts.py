import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.shared.errors import AppError


def draft_policy():
    assert importlib.util.find_spec("ai_workshop.labs.rag.conversations.draft_service"), (
        "Draft lifecycle is missing"
    )
    return importlib.import_module("ai_workshop.labs.rag.conversations.draft_service")


def test_draft_manifest_changes_require_open_unexpired_exact_revision():
    policy = draft_policy()
    now = datetime.now(UTC)
    draft = SimpleNamespace(state="open", revision=3, expires_at=now + timedelta(hours=1))
    policy.require_open(draft, 3, now)
    for state, revision, expiry, code in (
        ("open", 2, now + timedelta(hours=1), "draft_revision_conflict"),
        ("open", 3, now, "draft_unavailable"),
        ("abandoned", 3, now + timedelta(hours=1), "draft_unavailable"),
        ("expired", 3, now + timedelta(hours=1), "draft_unavailable"),
    ):
        draft.state, draft.expires_at = state, expiry
        with pytest.raises(AppError) as error:
            policy.require_open(draft, revision, now)
        assert error.value.code == code


def test_failed_ended_upload_is_not_permanently_busy_but_unknown_transport_blocks():
    policy = draft_policy()
    row = SimpleNamespace(state="failed", excluded_at=None, upload_terminated_at=datetime.now(UTC))
    assert not policy.upload_busy(row)
    row.upload_terminated_at = None
    assert policy.upload_busy(row)
    row.excluded_at = datetime.now(UTC)
    assert policy.upload_busy(row)
    row.upload_terminated_at = datetime.now(UTC)
    assert not policy.upload_busy(row)


def test_manifest_change_extends_ttl_and_poll_does_not():
    policy = draft_policy()
    now = datetime.now(UTC)
    draft = SimpleNamespace(revision=1, updated_at=now, expires_at=now + timedelta(minutes=5))
    policy.touch_manifest(draft, now + timedelta(minutes=1), 1440)
    assert draft.revision == 2
    assert draft.expires_at == now + timedelta(minutes=1441)


@pytest.mark.asyncio
async def test_draft_termination_acknowledges_failed_transport_without_conversation_parent():
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from ai_workshop.labs.rag.conversations.attachment_models import ConversationAttachmentRecord
    from ai_workshop.labs.rag.conversations.attachment_service import ConversationAttachmentService
    from ai_workshop.labs.rag.conversations.models import AttachmentDraftRecord

    attachment = SimpleNamespace(
        id=uuid4(),
        conversation_id=None,
        draft_id=uuid4(),
        intake_id=None,
        state="failed",
        upload_terminated_at=None,
    )
    draft = SimpleNamespace(state="open")

    async def get(model, id, **kw):
        return (
            attachment
            if model is ConversationAttachmentRecord
            else draft
            if model is AttachmentDraftRecord
            else None
        )

    session = SimpleNamespace(
        scalar=AsyncMock(return_value=(None, attachment.draft_id, None)),
        execute=AsyncMock(
            return_value=SimpleNamespace(one_or_none=lambda: (None, attachment.draft_id, None))
        ),
        get=AsyncMock(side_effect=get),
        flush=AsyncMock(),
    )

    @asynccontextmanager
    async def begin():
        yield session

    service = ConversationAttachmentService(SimpleNamespace(begin=begin), SimpleNamespace())
    await service.confirm_upload_termination(attachment.id)
    assert attachment.upload_terminated_at is not None


def test_worker_reconciles_draft_expiry_at_configured_interval():
    from ai_workshop.config import Settings
    from ai_workshop.worker import create_celery

    settings = Settings(
        _env_file=None,
        secret_key="synthetic-worker-first-question-secret",
        environment="test",
        rag_attachment_draft_reconcile_interval_seconds=17,
    )
    app = create_celery(settings)
    task = "ai_workshop.rag.reconcile_attachment_drafts"
    assert task in app.tasks
    schedules = [entry for entry in app.conf.beat_schedule.values() if entry["task"] == task]
    assert len(schedules) == 1 and schedules[0]["schedule"] == 17


@pytest.mark.asyncio
async def test_intake_reservation_rechecks_private_storage_in_same_transaction():
    from unittest.mock import AsyncMock, Mock

    from ai_workshop.labs.rag.conversations.attachment_service import ConversationUploadJournal

    actor, draft, attachment, workspace = (uuid4() for _ in range(4))
    row = SimpleNamespace(
        state="uploading",
        owner_id=actor,
        workspace_id=workspace,
        excluded_at=None,
        conversation_id=None,
        draft_id=draft,
        intake_id=None,
    )
    service = SimpleNamespace(
        sessions=Mock(),
        authorize=AsyncMock(return_value=SimpleNamespace()),
        _spaces=AsyncMock(return_value=[]),
    )
    journal = ConversationUploadJournal(
        service,
        slug="demo",
        conversation_id=draft,
        actor_id=actor,
        attachment_id=attachment,
        draft_id=draft,
    )
    session = SimpleNamespace(get=AsyncMock(return_value=row))
    claim = SimpleNamespace(
        id=uuid4(),
        source=SimpleNamespace(
            workspace_id=workspace, document_id=uuid4(), asset_version_id=uuid4()
        ),
    )
    with pytest.raises(AppError) as denied:
        await journal.reserved(session, claim)
    assert denied.value.status_code == 403 and row.intake_id is None
