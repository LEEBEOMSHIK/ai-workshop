"""Join owned search cleanup before request-scoped dependency disposal."""

import asyncio
from collections.abc import Coroutine
from typing import Any

from starlette.requests import Request


async def run_until_disconnect[T](request: Request, operation: Coroutine[Any, Any, T]) -> T:
    """Call after body parsing; repeated transport cancellation never cancels cleanup twice."""

    async def watch_disconnect() -> None:
        while True:
            if (await request.receive())["type"] == "http.disconnect":
                return

    owned = asyncio.create_task(operation)
    watcher = asyncio.create_task(watch_disconnect())
    interrupted = False
    try:
        completed, _ = await asyncio.wait((owned, watcher), return_when=asyncio.FIRST_COMPLETED)
        if watcher in completed:
            watcher.result()
            interrupted = True
    except asyncio.CancelledError:
        interrupted = True
    finally:
        if not owned.done():
            owned.cancel()
        if not watcher.done():
            watcher.cancel()
        joined = asyncio.gather(owned, watcher, return_exceptions=True)
        while not joined.done():
            try:
                await asyncio.shield(joined)
            except asyncio.CancelledError:
                interrupted = True
    if interrupted:
        raise asyncio.CancelledError
    return owned.result()
