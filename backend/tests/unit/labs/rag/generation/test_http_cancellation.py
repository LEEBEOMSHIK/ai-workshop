"""In-process HTTP cancellation contracts; no live provider termination claim."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import replace
from types import SimpleNamespace
from typing import Literal

import httpx
import pytest

from ai_workshop.labs.rag.generation import openai_compatible, openai_responses
from ai_workshop.labs.rag.generation.domain import ContextualizationRequest
from ai_workshop.labs.rag.generation.openai_compatible import LocalOpenAICompatibleRuntime
from ai_workshop.labs.rag.generation.openai_responses import OpenAIResponsesRuntime
from tests.unit.labs.rag.generation.test_openai_compatible import local_deployment
from tests.unit.labs.rag.generation.test_openai_responses import deployment, generation_request


@pytest.mark.parametrize("provider", ["local", "responses"])
@pytest.mark.parametrize("operation", ["generate", "contextualize"])
@pytest.mark.parametrize("phase", ["request", "timeout_backoff", "rate_limit_backoff"])
async def test_cancellation_propagates_without_retry(
    provider: Literal["local", "responses"],
    operation: Literal["generate", "contextualize"],
    phase: Literal["request", "timeout_backoff", "rate_limit_backoff"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    released = asyncio.Event()
    request_finished = asyncio.Event()
    backoff_finished = asyncio.Event()
    requests: list[httpx.Request] = []
    delays: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        try:
            if phase == "request":
                entered.set()
                await released.wait()
                return httpx.Response(500)
            if phase == "timeout_backoff":
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            return httpx.Response(429)
        finally:
            request_finished.set()

    async def backoff(delay: float) -> None:
        delays.append(delay)
        entered.set()
        try:
            await released.wait()
        finally:
            backoff_finished.set()

    module = openai_compatible if provider == "local" else openai_responses
    # Replace only the provider's binding, preserving the event loop/test timeouts.
    monkeypatch.setattr(module, "asyncio", SimpleNamespace(**(vars(asyncio) | {"sleep": backoff})))
    selected = replace(
        local_deployment() if provider == "local" else deployment(),
        max_retries=2,
        retry_backoff_seconds=0.25,
    )
    request = generation_request()
    request = replace(
        request,
        profile=replace(
            request.profile,
            deployment=selected,
            runtime_model=selected.provider_model_id,
        ),
    )
    transport = httpx.MockTransport(handler)
    async with AsyncExitStack() as stack:
        runtime: LocalOpenAICompatibleRuntime | OpenAIResponsesRuntime
        if provider == "local":
            client = await stack.enter_async_context(
                httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False)
            )
            runtime = LocalOpenAICompatibleRuntime(
                deployment=selected, endpoint="http://127.0.0.1:9999", client=client
            )
        else:
            runtime = OpenAIResponsesRuntime._for_test(
                deployment=selected,
                endpoint="https://provider.invalid",
                api_key="synthetic-key",
                transport=transport,
            )
        call = (
            runtime.generate(request)
            if operation == "generate"
            else runtime.contextualize(
                ContextualizationRequest(
                    question=request.question,
                    history=request.history,
                    profile=request.profile,
                )
            )
        )
        task = asyncio.create_task(call)
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            assert not task.done()
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=2)
            assert task in done, "Provider did not propagate cancellation"
            with pytest.raises(asyncio.CancelledError):
                await task
            assert task.cancelled()
            assert len(requests) == 1
            assert requests[0].method == "POST"
            assert request_finished.is_set()
            assert delays == ([] if phase == "request" else [0.25])
            assert backoff_finished.is_set() == (phase != "request")
        finally:
            released.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
