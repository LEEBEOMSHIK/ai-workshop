"""ASGI disconnect ownership with synthetic async work and bounded barriers."""

import asyncio

import pytest
from starlette.requests import Request


def transport():
    messages = asyncio.Queue()
    request = Request(
        {"type": "http", "method": "POST", "path": "/synthetic"}, receive=messages.get
    )
    return request, messages


async def test_normal_result_joins_disconnect_watcher():
    from ai_workshop.labs.rag.generation.codex_http_lifecycle import run_until_disconnect

    request, messages = transport()

    async def operation():
        return "synthetic"

    assert await run_until_disconnect(request, operation()) == "synthetic"
    assert not messages._getters


@pytest.mark.parametrize("disconnect", [True, False])
async def test_disconnect_or_repeated_parent_cancel_joins_cleanup_before_return(disconnect):
    from ai_workshop.labs.rag.generation.codex_http_lifecycle import run_until_disconnect

    request, messages = transport()
    started, cleaning, release, cleaned = (asyncio.Event() for _ in range(4))

    async def operation():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            cleaned.set()

    task = asyncio.create_task(run_until_disconnect(request, operation()))
    await asyncio.wait_for(started.wait(), 2)
    if disconnect:
        await messages.put({"type": "http.disconnect"})
    else:
        task.cancel()
    await asyncio.wait_for(cleaning.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and not cleaned.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert cleaned.is_set() and not messages._getters


async def test_operation_failure_propagates_after_watcher_join():
    from ai_workshop.labs.rag.generation.codex_http_lifecycle import run_until_disconnect

    request, messages = transport()

    async def operation():
        raise ValueError("synthetic")

    with pytest.raises(ValueError, match="synthetic"):
        await run_until_disconnect(request, operation())
    assert not messages._getters
