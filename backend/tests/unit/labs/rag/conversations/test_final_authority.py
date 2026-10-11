"""HTTP completion survives audit commit while final owner/source ACL remains current."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_mock_engine, literal, select
from sqlalchemy.orm import Session

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.conversations import api
from ai_workshop.labs.rag.domains.api import get_domain_search_executor, get_domain_service
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.conversations.start_support import attach_memory_starts
from tests.unit.labs.rag.conversations.test_service import response, seed_conversation, setup


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "followup,revoke_domain,revoke_source",
    [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, True, False),
        (True, False, True),
    ],
)
async def test_production_composition_final_authority_after_audit_commit(
    monkeypatch, followup, revoke_domain, revoke_source
):
    service, repo, access, _, actor, incoming = setup.__wrapped__()
    attach_memory_starts(repo)
    if followup:
        previous = await seed_conversation(service, "demo", actor)
        previous = await service.submit("demo", actor, previous.id, incoming)
        previous = await service.rename(
            "demo", actor, previous.id, "Synthetic private manual title", previous.revision
        )
        incoming = incoming.model_copy(
            update={"request_id": uuid4(), "expected_revision": previous.revision}
        )
    state = SimpleNamespace(committed=False, fresh_checks=0, fresh_opened=0, fresh_closed=0)

    class RequestDomains:
        async def detail_for_actor(self, slug, actor_id):
            if state.committed:
                # Real SQLAlchemy transaction-context check; no SQL can execute.
                request_session.execute(select(literal(1)))

        resolve_search = AsyncMock()

    class FreshDomains:
        async def detail_for_actor(self, slug, actor_id):
            state.fresh_checks += 1
            if revoke_domain:
                raise AppError("not_found", "The requested resource was not found.", 404)

    @asynccontextmanager
    async def fresh_sessions():
        state.fresh_opened += 1
        try:
            yield object()
        finally:
            state.fresh_closed += 1

    async def execute(**values):
        request_session.commit()  # Models the concrete generation-audit commit.
        state.committed = True
        if revoke_source:
            access.visible.return_value = False
        return response()

    executor = SimpleNamespace(preflight=AsyncMock(), execute=AsyncMock(side_effect=execute))
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(api, "create_engine", lambda settings: engine)
    monkeypatch.setattr(api, "create_session_factory", lambda engine: fresh_sessions)
    monkeypatch.setattr(api, "SqlAlchemyConversationRepository", lambda sessions: repo)
    monkeypatch.setattr(api, "ConversationAccess", lambda sessions: access)
    monkeypatch.setattr(api, "SqlAlchemyExecutionRecorder", lambda sessions: None)
    monkeypatch.setattr(api, "DomainService", lambda repository, configuration: FreshDomains())
    monkeypatch.setattr(api, "SqlAlchemyDomainRepository", lambda session: session, raising=False)
    monkeypatch.setattr(
        api,
        "SqlAlchemyDomainConfigurationProvider",
        lambda session, settings, **values: session,
        raising=False,
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, environment="test", secret_key="synthetic-final-authority-test-secret"
    )
    app.dependency_overrides[get_domain_service] = lambda: RequestDomains()
    app.dependency_overrides[get_domain_search_executor] = lambda: executor
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=actor)
    base = "/api/v1/rag/domains/demo/conversations"
    path = f"{base}/{previous.id}/turns" if followup else f"{base}/start"
    payload = incoming.model_dump(mode="json", exclude_none=True)
    if not followup:
        payload.pop("expected_revision")

    def no_sql(*values, **kwargs):
        raise AssertionError("The transaction-context reproduction must not execute SQL.")

    mock_engine = create_mock_engine("postgresql://", no_sql)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        with Session(bind=mock_engine) as request_session, request_session.begin():
            result = await client.post(path, json=payload)
        assert state.committed
        aggregate = next(
            item for item in repo.items.values() if item.turns[-1].request_id == incoming.request_id
        )
        assert (
            aggregate.turns[-1].status
            == ("failed" if revoke_domain or revoke_source else "completed")
            and aggregate.title
        )
        assert result.status_code == (404 if revoke_domain else 200 if followup else 201)
        assert result.headers["cache-control"] == "no-store"
        assert state.fresh_checks == state.fresh_opened == state.fresh_closed == 1
        assert executor.execute.await_count == 1
        if revoke_domain or revoke_source:
            saved = repo.items[aggregate.id].turns[-1]
            assert saved.status != "completed" and saved.response is None
        if revoke_domain:
            assert "Synthetic private manual title" not in result.text
            assert incoming.query not in result.text
        elif revoke_source:
            assert result.json()["title"] == "접근할 수 없는 대화"
            assert all(turn["redacted"] and turn["query"] == "" for turn in result.json()["turns"])
        else:
            state.committed = False
            with Session(bind=mock_engine) as request_session, request_session.begin():
                replay = await client.post(path, json=payload)
            assert replay.status_code == result.status_code
            assert replay.json()["id"] == str(aggregate.id)
            assert executor.execute.await_count == 1
            if followup:
                assert replay.json()["title"] == "Synthetic private manual title"
