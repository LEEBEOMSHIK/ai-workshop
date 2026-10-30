import asyncio
from dataclasses import replace

import httpx2
import pytest

from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    GenerationTermination,
    tracked_generation_call,
)
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, request, runner


class StreamingBody(httpx2.AsyncByteStream):
    def __init__(self, *, stall=False):
        self.stall = stall
        self.closed = False
        self.entered = asyncio.Event()
        self.chunks = 0

    async def __aiter__(self):
        self.entered.set()
        if self.stall:
            await asyncio.Event().wait()
        for _ in range(100):
            self.chunks += 1
            yield b" " * 65536

    async def aclose(self):
        self.closed = True


async def test_oversized_response_stops_reading_and_closes_stream_without_confirming_termination():
    stream = StreamingBody()
    target = runner(lambda value: httpx2.Response(200, stream=stream, request=value))
    termination = GenerationTermination()
    with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
        await tracked_generation_call(target.generate(request(), policy=POLICY), termination)
    assert stream.closed
    assert stream.chunks <= 17
    assert not termination.confirmed


@pytest.mark.parametrize("cancel", [False, True])
async def test_incomplete_response_stream_is_closed_on_timeout_or_cancel(cancel):
    stream = StreamingBody(stall=True)
    target = runner(lambda value: httpx2.Response(200, stream=stream, request=value))
    selected = request()
    if not cancel:
        selected = replace(selected, profile=replace(selected.profile, timeout_seconds=0.05))
    termination = GenerationTermination()
    task = asyncio.create_task(tracked_generation_call(
        target.generate(selected, policy=POLICY), termination,
    ))
    await asyncio.wait_for(stream.entered.wait(), 5)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(GenerationProviderError, match="provider_timeout"):
            await task
    assert stream.closed
    assert not termination.confirmed
