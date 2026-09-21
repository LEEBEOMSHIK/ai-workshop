from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.conversations.api import get_conversation_service, router
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.shared.errors import register_error_handlers
from tests.unit.labs.rag.conversations.test_service import setup  # noqa: F401


@pytest.mark.asyncio
async def test_crud_contract_no_store_and_forbidden_history(setup):  # noqa: F811
    service, _, _, executor, actor, request = setup
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_conversation_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=actor)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, secret_key="synthetic-test-secret-for-conversations-only"
    )
    base = "/api/v1/rag/domains/demo/conversations"
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        created = await client.post(base, json={})
        assert created.status_code == 201
        assert created.headers["cache-control"] == "no-store"
        id = created.json()["id"]
        listing = await client.get(base)
        assert listing.json()[0]["id"] == id
        assert listing.headers["cache-control"] == "no-store"
        data = request.model_dump(mode="json", exclude_none=True)
        forged = await client.post(f"{base}/{id}/turns", json={**data, "history": []})
        assert forged.status_code == 422
        assert executor.execute.await_count == 0
        detail = await client.get(f"{base}/{id}")
        assert detail.json()["turns"] == []
        renamed = await client.patch(
            f"{base}/{id}", json={"title": "Saved", "expected_revision": 1}
        )
        assert renamed.json()["title"] == "Saved"
        stale = await client.delete(f"{base}/{id}", params={"expected_revision": 1})
        assert stale.status_code == 409
        deleted = await client.delete(f"{base}/{id}", params={"expected_revision": 2})
        assert deleted.status_code == 204
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4())
        assert (await client.get(base)).json() == []
        assert (await client.get(f"{base}/{id}")).status_code == 404
