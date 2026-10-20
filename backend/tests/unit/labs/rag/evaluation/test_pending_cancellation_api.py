"""The new management route keeps normal owner authentication and a bounded body."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from ai_workshop.labs.rag.evaluation import generative_api as api
from ai_workshop.labs.rag.evaluation import generative_schemas as schemas
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.shared.errors import AppError, register_error_handlers


@pytest.mark.parametrize("role,expected", [(None, 401), (UserRole.MEMBER, 403)])
async def test_cancel_requires_authenticated_owner(role, expected):
    app = FastAPI()
    app.include_router(api.router)
    register_error_handlers(app)

    async def user():
        if role is None:
            raise AppError("authentication_required", "Login required.", 401)
        return SimpleNamespace(id=uuid4(), role=role)

    # Synthetic test app only; no live sessions or credentials are used.
    app.dependency_overrides[get_current_user] = user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/v1/rag/generative-evaluations/{uuid4()}/cancel",
            json={"reason": "user_requested"},
        )
    assert response.status_code == expected


@pytest.mark.parametrize(
    "body",
    [
        {"reason": ""},
        {"reason": " "},
        {"reason": "arbitrary"},
        {"reason": "user_requested", "cancelled_by": str(uuid4())},
        {"reason": "user_requested", "cancelled_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_cancel_body_cannot_supply_audit_identity_or_free_text(body):
    with pytest.raises(ValidationError):
        schemas.GenerativeCancelRequest.model_validate(body)


async def test_cancel_materializes_response_before_commit(monkeypatch):
    actor, run_id = SimpleNamespace(id=uuid4()), uuid4()
    sequence = []
    session = SimpleNamespace(
        flush=AsyncMock(), commit=AsyncMock(side_effect=lambda: sequence.append("commit"))
    )

    async def cancel(*args):
        sequence.append("cancel")

    async def detail(*args):
        sequence.append("detail")
        return SimpleNamespace(status="cancelled")

    monkeypatch.setattr(api.GenerativeRepository, "cancel_pending", cancel)
    monkeypatch.setattr(api, "run_detail", detail)
    result = await api.cancel(
        run_id, schemas.GenerativeCancelRequest(reason="user_requested"), actor, session
    )
    assert result.status == "cancelled"
    assert sequence == ["cancel", "detail", "commit"]
