"""Prefer opt-in preserves synchronous clients and returns the stored resource location."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.conversations.api import get_conversation_service, router
from ai_workshop.platform.identity.api import get_current_user
from tests.unit.labs.rag.conversations.test_background import detail, question


@pytest.mark.parametrize("kind", ["start", "submit"])
async def test_prefer_accepted_and_existing_synchronous_contract(kind):
    accepted, actor = detail(), uuid4()
    service = SimpleNamespace(start=AsyncMock(return_value=accepted),
                              submit=AsyncMock(return_value=accepted))
    background = SimpleNamespace(start=AsyncMock(return_value=accepted),
                                 submit=AsyncMock(return_value=accepted))
    app = FastAPI()
    app.include_router(router)
    app.state.conversation_background = background
    app.dependency_overrides[get_conversation_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=actor)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, secret_key="public-synthetic-background-test-secret",
    )
    base = "/api/v1/rag/domains/demo/conversations"
    path = f"{base}/start" if kind == "start" else f"{base}/{accepted.id}/turns"
    incoming = question() if kind == "start" else question().turn_request()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(path, json=incoming.model_dump(mode="json", exclude_none=True),
                                     headers={"Prefer": "respond-async"})
        assert response.status_code == 202
        assert response.headers["preference-applied"] == "respond-async"
        assert response.headers["location"] == f"{base}/{accepted.id}"
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["id"] == str(accepted.id)
        assert getattr(background, kind).await_count == 1
        assert getattr(service, kind).await_count == 0
        response = await client.post(
            path, json=incoming.model_dump(mode="json", exclude_none=True),
        )
        assert response.status_code == (201 if kind == "start" else 200)
        assert "preference-applied" not in response.headers
        assert getattr(service, kind).await_count == 1


async def test_application_drains_background_before_shared_model_host():
    from ai_workshop.main import create_app

    app = create_app()
    closed = []

    async def close_background():
        closed.append("background")

    async def close_host():
        closed.append("host")

    app.state.conversation_background = SimpleNamespace(aclose=close_background)
    app.state.local_model_host = SimpleNamespace(aclose=close_host)
    async with app.router.lifespan_context(app):
        assert closed == []
    assert closed == ["background", "host"]
