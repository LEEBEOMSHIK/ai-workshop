from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.conversations.attachment_service import (
    eligible_attachment_workspace,
    require_upload_binding,
)
from ai_workshop.shared.errors import AppError


@pytest.mark.asyncio
async def test_attachment_denial_happens_before_any_request_bytes_are_read():
    from fastapi import BackgroundTasks, Response

    from ai_workshop.labs.rag.conversations.attachment_api import upload_attachment

    service = SimpleNamespace(reserve=AsyncMock(side_effect=AppError("not_found", "Missing", 404)))
    request = SimpleNamespace(
        stream=Mock(side_effect=AssertionError("body read before authorization"))
    )
    with pytest.raises(AppError):
        await upload_attachment(
            "demo",
            uuid4(),
            uuid4(),
            request,
            Response(),
            BackgroundTasks(),
            SimpleNamespace(id=uuid4()),
            service,
            SimpleNamespace(),
            SimpleNamespace(),
        )
    request.stream.assert_not_called()


@pytest.mark.asyncio
async def test_deleted_session_blocks_final_upload_attachment(monkeypatch):
    from ai_workshop.labs.rag.conversations.attachment_service import ConversationUploadJournal
    from ai_workshop.platform.assets.intake_repository import UploadIntakeJournal

    monkeypatch.setattr(UploadIntakeJournal, "prepare_attachment", AsyncMock())
    service = SimpleNamespace(
        sessions=Mock(),
        authorize=AsyncMock(side_effect=AppError("not_found", "Deleted", 404)),
        _spaces=AsyncMock(),
    )
    journal = ConversationUploadJournal(
        service, slug="demo", conversation_id=uuid4(), actor_id=uuid4(), attachment_id=uuid4()
    )
    session = SimpleNamespace(get=AsyncMock())
    with pytest.raises(AppError):
        await journal.prepare_attachment(session, SimpleNamespace(), SimpleNamespace())
    session.get.assert_not_called()
    service._spaces.assert_not_called()


def test_projection_ready_alone_does_not_make_attachment_searchable():
    from ai_workshop.labs.rag.conversations.attachment_service import attachment_readiness

    assert attachment_readiness("ready", None) == "processing"
    build = SimpleNamespace(status="ready", is_active=False)
    assert attachment_readiness("ready", build) == "processing"
    build.is_active = True
    assert attachment_readiness("ready", build) == "ready"
    assert attachment_readiness("partial_ready", build) == "failed"


def test_attachments_never_use_company_or_another_owners_workspace():
    actor, workspace_id = uuid4(), uuid4()
    space = SimpleNamespace(id=workspace_id, kind="personal", created_by=actor, expires_at=None)
    assert eligible_attachment_workspace(space, actor)
    assert not eligible_attachment_workspace(space, uuid4())
    space.kind = "company"
    assert not eligible_attachment_workspace(space, actor)
    space.kind = "temporary"
    space.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert not eligible_attachment_workspace(space, actor)


def test_attachment_finalization_rejects_deleted_session_and_wrong_reserved_source():
    actor, conversation, document, version, workspace = (uuid4() for _ in range(5))
    record = SimpleNamespace(
        owner_id=actor,
        conversation_id=conversation,
        planned_document_id=document,
        planned_version_id=version,
        workspace_id=workspace,
        state="uploading",
    )
    source = SimpleNamespace(document_id=document, asset_version_id=version, workspace_id=workspace)
    require_upload_binding(record, actor, conversation, source, live=True)
    for wrong_actor, live in ((uuid4(), True), (actor, False)):
        with pytest.raises(AppError):
            require_upload_binding(record, wrong_actor, conversation, source, live=live)
    source.asset_version_id = uuid4()
    with pytest.raises(AppError):
        require_upload_binding(record, actor, conversation, source, live=True)
