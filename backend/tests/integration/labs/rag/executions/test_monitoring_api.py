from dataclasses import replace

import httpx
import pytest

from ai_workshop.labs.rag.executions.api import get_service
from ai_workshop.labs.rag.executions.service import ExecutionReadService
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from tests.unit.labs.rag.executions.test_read_service import Access, Repository, entry


@pytest.mark.asyncio
async def test_monitoring_is_no_store_and_nonadmin_denied():
    user = User.create_owner(
        display_name="Synthetic", email="synthetic@example.test", password_hash="unused"
    )
    app = create_app()
    row = entry(user.id)
    app.dependency_overrides[get_service] = lambda: ExecutionReadService(
        Repository([row]), Access()
    )
    app.dependency_overrides[get_current_user] = lambda: user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/admin/rag/executions/search", json={"query": "synthetic"}
        )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["total"] == 1
        detail = await client.get(f"/api/v1/admin/rag/executions/legacy/{row.turn.id}")
        assert detail.status_code == 200
        assert "validation_token" not in detail.text
        app.dependency_overrides[get_current_user] = lambda: replace(user, role=UserRole.MEMBER)
        assert (
            await client.post("/api/v1/admin/rag/executions/search", json={})
        ).status_code == 403
        assert (
            await client.get(f"/api/v1/admin/rag/executions/legacy/{row.turn.id}")
        ).status_code == 403
