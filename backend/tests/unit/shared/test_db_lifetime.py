"""HTTP pools belong to a lifespan; transactions still belong to requests."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Annotated

import pytest
from fastapi import Depends, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.main import create_app
from ai_workshop.shared import db


@pytest.fixture
def database_spy(monkeypatch):
    engines, sessions, events = [], [], []

    def make_engine(settings):
        async def dispose():
            events.append(("dispose", len(engines)))
        engine = SimpleNamespace(dispose=dispose)
        engines.append(engine)
        return engine

    def make_factory(engine):
        @asynccontextmanager
        async def begin() -> AsyncIterator[object]:
            session = object()
            sessions.append(session)
            events.append(("begin", session))
            try:
                yield session
            except BaseException:
                events.append(("rollback", session))
                raise
            else:
                events.append(("commit", session))
            finally:
                events.append(("close", session))
        return SimpleNamespace(begin=begin)

    monkeypatch.setattr(db, "get_settings", lambda: object())
    monkeypatch.setattr(db, "create_engine", make_engine)
    monkeypatch.setattr(db, "create_session_factory", make_factory)
    return SimpleNamespace(engines=engines, sessions=sessions, events=events)


def application():
    app = create_app()

    @app.get("/database-probe")
    async def probe(
        session: Annotated[AsyncSession, Depends(db.get_session)], fail: bool = False,
    ):
        if fail:
            raise HTTPException(status_code=409, detail="synthetic_failure")
        return {"session": id(session)}

    return app


async def test_pool_reused_but_each_request_has_a_new_transaction(database_spy):
    app = application()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            first = await client.get("/database-probe")
            second = await client.get("/database-probe")
        assert first.status_code == second.status_code == 200
        assert first.json()["session"] != second.json()["session"]
        assert len(database_spy.engines) == 1
        assert [event for event, _ in database_spy.events].count("commit") == 2
        assert [event for event, _ in database_spy.events].count("close") == 2
        assert not any(event == "dispose" for event, _ in database_spy.events)
    assert [event for event, _ in database_spy.events].count("dispose") == 1


async def test_failed_request_rolls_back_without_poisoning_next_request(database_spy):
    app = application()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            failed = await client.get("/database-probe?fail=true")
            healthy = await client.get("/database-probe")
        assert failed.status_code == 409 and healthy.status_code == 200
        kinds = [event for event, _ in database_spy.events]
        assert kinds.count("rollback") == kinds.count("commit") == 1
        assert kinds.count("close") == 2
        assert len(database_spy.engines) == 1


async def test_apps_and_reentered_lifespans_do_not_share_pools(database_spy):
    first, second = application(), application()
    for app in (first, second, first):
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app), base_url="http://test") as client,
        ):
            assert (await client.get("/database-probe")).status_code == 200
            assert (await client.get("/database-probe")).status_code == 200
    assert len(database_spy.engines) == 3
    assert len({id(engine) for engine in database_spy.engines}) == 3
    assert [event for event, _ in database_spy.events].count("dispose") == 3


async def test_database_disposed_after_background_cleanup_even_when_host_close_fails(database_spy):
    app = application()

    async def background():
        database_spy.events.append(("background", None))

    async def host():
        database_spy.events.append(("host", None))
        raise RuntimeError("synthetic_close_failure")

    app.state.conversation_background = SimpleNamespace(aclose=background)
    app.state.local_model_host = SimpleNamespace(aclose=host)
    with pytest.raises(RuntimeError, match="synthetic_close_failure"):
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
                assert (await client.get("/database-probe")).status_code == 200
    assert [event for event, _ in database_spy.events][-3:] == ["background", "host", "dispose"]


async def test_no_lifespan_does_not_create_an_unowned_pool(database_spy):
    app = application()
    with pytest.raises(RuntimeError, match="Database lifespan is not running"):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            await client.get("/database-probe")
    assert database_spy.engines == []
