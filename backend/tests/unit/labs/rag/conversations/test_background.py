"""Server-owned conversation lifetime; only synthetic execution and thread barriers."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from threading import Event, get_ident
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.conversations.schemas import ConversationDetail, ConversationStart
from ai_workshop.shared.errors import AppError


def question():
    return ConversationStart(
        request_id=uuid4(), query="Public synthetic?", connection_version_id=uuid4(),
        workspace_ids=[uuid4()],
    )


def detail():
    now = datetime.now(UTC)
    return ConversationDetail(
        id=uuid4(), title="Public synthetic", revision=2, created_at=now,
        updated_at=now, turns=[],
    )


async def wait_event(event):
    assert await asyncio.wait_for(asyncio.to_thread(event.wait, 3), 4)


async def test_acceptance_survives_waiter_cancel_and_blocking_execution():
    from ai_workshop.labs.rag.conversations.background import ConversationBackground

    entered, proceed, running, release, closed = (Event() for _ in range(5))
    ids, queries = [], []
    accepted = detail()

    async def start(slug, actor, request, *, on_accepted):
        entered.set()
        while not proceed.is_set():
            await asyncio.sleep(0.005)
        queries.append(request.query)
        on_accepted(accepted)
        running.set()
        assert release.wait(3)  # Deliberately block only the owned worker loop.
        return accepted

    @asynccontextmanager
    async def factory(actor):
        ids.append(get_ident())
        try:
            yield SimpleNamespace(start=start)
        finally:
            closed.set()

    runtime = ConversationBackground(factory)
    incoming = question()
    waiter = asyncio.create_task(runtime.start("demo", uuid4(), incoming))
    try:
        await wait_event(entered)
        incoming.query = "Changed after submission"
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        proceed.set()
        await wait_event(running)
        assert not closed.is_set()
        assert ids == [ids[0]] and ids[0] != get_ident()
        assert queries == ["Public synthetic?"]
        await asyncio.wait_for(asyncio.sleep(0), 0.2)
    finally:
        proceed.set()
        release.set()
        await runtime.aclose()
    assert closed.is_set()


async def test_acceptance_returns_before_worker_finishes():
    from ai_workshop.labs.rag.conversations.background import ConversationBackground

    release, closed = Event(), Event()
    accepted = detail()

    async def start(slug, actor, request, *, on_accepted):
        on_accepted(accepted)
        assert release.wait(3)
        return accepted

    @asynccontextmanager
    async def factory(actor):
        try:
            yield SimpleNamespace(start=start)
        finally:
            closed.set()

    runtime = ConversationBackground(factory)
    try:
        result = await asyncio.wait_for(runtime.start("demo", uuid4(), question()), 1)
        assert result == accepted and result is not accepted
        assert not closed.is_set()
    finally:
        release.set()
        await runtime.aclose()
    assert closed.is_set()


async def test_shutdown_joins_cleanup_and_rejects_new_admission():
    from ai_workshop.labs.rag.conversations.background import ConversationBackground

    cleaning, release, closed = Event(), Event(), Event()

    async def start(slug, actor, request, *, on_accepted):
        on_accepted(detail())
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            while not release.is_set():
                await asyncio.sleep(0.005)

    @asynccontextmanager
    async def factory(actor):
        try:
            yield SimpleNamespace(start=start)
        finally:
            closed.set()

    runtime = ConversationBackground(factory)
    await runtime.start("demo", uuid4(), question())
    closing = asyncio.create_task(runtime.aclose())
    try:
        await wait_event(cleaning)
        closing.cancel()
        assert not closed.is_set()
        with pytest.raises(AppError) as error:
            await runtime.start("demo", uuid4(), question())
        assert error.value.code == "conversation_background_unavailable"
    finally:
        release.set()
        await closing
    assert closed.is_set()


async def test_replay_and_safe_preaccept_failure():
    from ai_workshop.labs.rag.conversations.background import ConversationBackground

    accepted = detail()
    calls = 0

    async def start(slug, actor, request, *, on_accepted):
        nonlocal calls
        calls += 1
        if calls == 1:
            return accepted  # Existing core replay path emits no new acceptance callback.
        raise RuntimeError("private failure body")

    @asynccontextmanager
    async def factory(actor):
        yield SimpleNamespace(start=start)

    runtime = ConversationBackground(factory)
    try:
        assert await runtime.start("demo", uuid4(), question()) == accepted
        with pytest.raises(AppError) as error:
            await runtime.start("demo", uuid4(), question())
        assert error.value.code == "conversation_background_failed"
        assert "private" not in str(error.value)
    finally:
        await runtime.aclose()


async def test_cancel_while_worker_loop_starts_does_not_drop_submission(monkeypatch):
    from ai_workshop.labs.rag.conversations import background

    initializing, release, executed = Event(), Event(), Event()
    original = background.create_selector_event_loop

    def delayed_loop():
        initializing.set()
        assert release.wait(3)
        return original()

    monkeypatch.setattr(background, "create_selector_event_loop", delayed_loop)

    async def start(slug, actor, request, *, on_accepted):
        executed.set()
        return detail()

    @asynccontextmanager
    async def factory(actor):
        yield SimpleNamespace(start=start)

    runtime = background.ConversationBackground(factory)
    waiter = asyncio.create_task(runtime.start("demo", uuid4(), question()))
    try:
        await wait_event(initializing)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set()
        await wait_event(executed)
    finally:
        release.set()
        await runtime.aclose()
