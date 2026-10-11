"""Owner API cache contract through the production application's middleware."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from ai_workshop.labs.rag.conversations.api import get_conversation_service
from ai_workshop.labs.rag.conversations.draft_api import draft_service
from ai_workshop.labs.rag.conversations.draft_service import DraftResponse
from ai_workshop.labs.rag.conversations.schemas import ConversationDetail
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.shared.errors import AppError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,status",
    [
        ("start", 200),
        ("start", 404),
        ("start", 410),
        ("draft", 200),
        ("draft", 410),
        ("start", 422),
        ("draft", 422),
        ("start", 401),
        ("draft", 401),
    ],
)
async def test_production_owner_response_no_store_including_errors_auth_and_validation(
    kind, status
):
    app = create_app()
    actor, id = uuid4(), uuid4()
    now = datetime.now(UTC)
    conversation = ConversationDetail(
        id=id, title="Synthetic title", revision=1, created_at=now, updated_at=now, turns=[]
    )
    draft = DraftResponse(
        id=id,
        state="open",
        revision=1,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
        bound_conversation_id=None,
        legacy_conversation_id=None,
    )
    conversations = SimpleNamespace(start_status=AsyncMock(return_value=conversation))
    drafts = SimpleNamespace(detail_draft=AsyncMock(return_value=draft))
    if status in {404, 410}:
        error = AppError("synthetic_owner_error", "Synthetic unavailable resource.", status)
        (conversations.start_status if kind == "start" else drafts.detail_draft).side_effect = error
    app.dependency_overrides[get_conversation_service] = lambda: conversations
    app.dependency_overrides[draft_service] = lambda: drafts
    if status == 401:

        async def unauthenticated():
            raise AppError("unauthenticated", "Authentication required.", 401)

        app.dependency_overrides[get_current_user] = unauthenticated
    else:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=actor)
    token = "invalid-uuid" if status == 422 else str(id)
    suffix = f"conversations/starts/{token}" if kind == "start" else f"attachment-drafts/{token}"
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/rag/domains/demo/{suffix}")
    assert response.status_code == status
    assert response.headers.get("cache-control") == "no-store"
    if status == 200:
        assert response.json()["id"] == str(id)
    if status in {401, 422}:
        assert conversations.start_status.await_count == drafts.detail_draft.await_count == 0
