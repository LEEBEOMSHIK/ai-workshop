"""Bound full runner inspections without transferring ownership on cancellation."""

import asyncio
from weakref import WeakValueDictionary

from .codex_runner_registry import CodexRunnerRegistry, ResolvedCodexRunner

# Every active caller holds its limiter strongly, including while waiting for a
# slot. Weak values release the loop key after the final caller exits, even when
# contention has bound the semaphore back to that loop.
_limiters: WeakValueDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = WeakValueDictionary()


async def inspect_codex_runner(
    registry: CodexRunnerRegistry, reference: str
) -> ResolvedCodexRunner:
    """Inspect once per request, using at most one actual worker per event loop.

    The event loop owns and shuts down its default executor. Acquire before
    submitting work so queued or cancelled waiters do not create executor jobs.
    Once submitted, join the actual inspection even after repeated native task
    cancellation; releasing the slot earlier would allow unbounded live checks.
    """
    loop = asyncio.get_running_loop()
    limiter = _limiters.get(loop)
    if limiter is None:
        limiter = asyncio.Semaphore(1)
        _limiters[loop] = limiter
    async with limiter:
        inspection = loop.run_in_executor(None, registry.resolve, reference)
        cancelled = False
        while not inspection.done():
            try:
                await asyncio.shield(inspection)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                # Retrieve the original failure below, after ownership is joined.
                break
        if cancelled:
            if not inspection.cancelled():
                inspection.exception()
            raise asyncio.CancelledError
        return inspection.result()
