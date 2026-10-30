"""Independent worker resource contexts close in reverse order; no real connections."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


@pytest.mark.parametrize("failed", [False, True])
async def test_worker_assembly_owns_sessions_clients_and_borrows_shared_host(monkeypatch, failed):
    from ai_workshop.labs.rag.conversations import api
    from ai_workshop.labs.rag.conversations import background_composition as composition

    events = []
    search_session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    domain_session, shared_host, service = object(), object(), object()

    @asynccontextmanager
    async def context(name, value):
        events.append("open-" + name)
        try:
            yield value
        finally:
            events.append("close-" + name)

    class Sessions:
        def begin(self):
            return context("domain", domain_session)

        def __call__(self):
            return context("search", search_session)

    async def dispose():
        events.append("dispose")

    monkeypatch.setattr(composition, "create_engine", lambda _: SimpleNamespace(dispose=dispose))
    monkeypatch.setattr(composition, "create_session_factory", lambda _: Sessions())
    monkeypatch.setattr(composition, "DomainService", lambda *args: object())
    monkeypatch.setattr(composition, "DomainSearchExecutor", lambda *args: object())
    monkeypatch.setattr(composition, "SqlAlchemyDomainRepository", lambda _: object())
    monkeypatch.setattr(composition, "SqlAlchemyDomainConfigurationProvider",
                        lambda *args, **kwargs: object())
    monkeypatch.setattr(composition, "SqlAlchemyDomainSearchConfigurationResolver",
                        lambda *args: object())
    monkeypatch.setattr(composition, "get_search_configuration_resolver", lambda *args: object())
    monkeypatch.setattr(composition, "codex_services", lambda _: context("codex", object()))

    async def search(session, settings, resolver, codex, host):
        assert session is search_session and host is shared_host
        async with context("client", object()) as value:
            yield value

    async def conversation(settings, domains, executor):
        async with context("conversation", service) as value:
            yield value

    monkeypatch.setattr(composition, "get_search_service", search)
    monkeypatch.setattr(api, "get_conversation_service", conversation)
    try:
        async with composition.background_conversation_service(
            object(), uuid4(), shared_host,
        ) as value:
            assert value is service and not search_session.commit.called
            assert events == ["open-domain", "open-search", "open-codex",
                              "open-client", "open-conversation"]
            if failed:
                raise RuntimeError("synthetic")
    except RuntimeError:
        assert failed
    assert events[-6:] == ["close-conversation", "close-client", "close-codex",
                           "close-search", "close-domain", "dispose"]
    assert search_session.commit.await_count == (0 if failed else 1)
    assert search_session.rollback.await_count == (1 if failed else 0)
