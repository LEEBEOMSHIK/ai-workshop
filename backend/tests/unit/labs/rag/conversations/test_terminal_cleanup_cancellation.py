"""Real conversation/observer ownership with offline cancellation barriers."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from starlette.requests import Request

from ai_workshop.labs.rag.executions import observer
from ai_workshop.labs.rag.generation.codex_http_lifecycle import run_until_disconnect
from ai_workshop.labs.rag.generation.domain import ContextualizationRequest, GenerationRequest
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.openai_compatible import LocalOpenAICompatibleRuntime
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.conversations.test_service import response, seed_conversation, setup
from tests.unit.labs.rag.executions.test_observer import Recorder
from tests.unit.labs.rag.generation.test_openai_compatible import (
    evidence,
    local_deployment,
    profile,
)


class BarrierRecorder(Recorder):
    def __init__(self, boundary, reached, release, joined, *, fail=False):
        super().__init__()
        self.boundary, self.reached, self.release = boundary, reached, release
        self.joined, self.fail_write = joined, fail
        self.persisting = False

    async def record(self, id, observation):
        if observation.stage == "persistence":
            self.persisting = True
        if self.boundary == "observer_fail" and observation.state == "failed":
            assert self.joined.is_set(), "Observer finalization precedes executor cleanup"
            self.reached.set()
            await self.release.wait()
            if self.fail_write:
                raise RuntimeError("Synthetic observation failure")
        await super().record(id, observation)


@pytest.mark.parametrize(
    "boundary,mode",
    [
        ("observer_fail", "cancelled"),
        ("persistence", "cancelled"),
        ("final_authority", "cancelled"),
        ("persistence", "completed"),
        ("final_authority", "completed"),
        ("observer_fail", "model_error"),
        ("persistence", "model_error"),
        ("final_authority", "model_error"),
    ],
)
async def test_transport_cancel_joins_terminalization_without_rewriting_result(boundary, mode):
    service, repo, _, executor, actor, incoming = setup.__wrapped__()
    started, provider_release, joined, reached, release = (asyncio.Event() for _ in range(5))
    recorder = BarrierRecorder(boundary, reached, release, joined)
    service.recorder = recorder
    created = await seed_conversation(service, "domain", actor)

    async def execute(**kwargs):
        await observer.begin("retrieval")
        started.set()
        try:
            await provider_release.wait()
            if mode == "cancelled":
                raise asyncio.CancelledError
            if mode == "model_error":
                raise AppError("model_unavailable", "Synthetic private failure", 503)
            await observer.end("retrieval")
            return response()
        finally:
            joined.set()

    executor.execute.side_effect = execute
    locked = repo.locked

    @asynccontextmanager
    async def persistence_lock(*args):
        if boundary == "persistence" and recorder.persisting:
            assert joined.is_set()
            reached.set()
            await release.wait()
        async with locked(*args) as item:
            yield item

    repo.locked = persistence_lock

    async def final_authority(*args):
        if boundary == "final_authority":
            assert joined.is_set()
            reached.set()
            await release.wait()

    service.final_authority = final_authority
    messages = asyncio.Queue()
    request = Request(
        {"type": "http", "method": "POST", "path": "/synthetic"}, receive=messages.get
    )
    transport = asyncio.create_task(
        run_until_disconnect(request, service.submit("domain", actor, created.id, incoming))
    )
    try:
        await asyncio.wait_for(started.wait(), 2)
        if mode == "cancelled":
            await service.cancel("domain", actor, created.id, incoming.request_id)
        provider_release.set()
        await asyncio.wait_for(reached.wait(), 2)
        await messages.put({"type": "http.disconnect"})
        for _ in range(4):
            await asyncio.sleep(0)
        transport.cancel()
        await asyncio.sleep(0)
        assert not transport.done(), "HTTP ownership must join all terminal cleanup"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(transport, 2)
        saved = repo.items[created.id].turns[0]
        expected = {"cancelled": "cancelled", "completed": "completed", "model_error": "failed"}
        assert saved.execution_terminated and saved.status == expected[mode]
        assert (
            saved.error_code
            == {
                "cancelled": "conversation_cancelled",
                "completed": None,
                "model_error": "model_unavailable",
            }[mode]
        )
        assert recorder.outcome.state == saved.status
        assert recorder.outcome.error_code == saved.error_code and recorder.outcome.complete
        terminal = {row.stage: row for row in recorder.rows}
        assert terminal["retrieval"].state == ("completed" if mode == "completed" else "failed")
        assert terminal["persistence"].state == "completed"
        assert not messages._getters
    finally:
        provider_release.set()
        release.set()
        if not transport.done():
            transport.cancel()
        await asyncio.gather(transport, return_exceptions=True)


@pytest.mark.parametrize("initial_cancel", ["owned", "explicit"])
async def test_repeated_owned_cancel_does_not_interrupt_executor_finally_join(initial_cancel):
    service, repo, _, executor, actor, incoming = setup.__wrapped__()
    started, cleaning, release, joined = (asyncio.Event() for _ in range(4))
    recorder = Recorder()
    service.recorder = recorder
    created = await seed_conversation(service, "domain", actor)

    async def execute(**kwargs):
        await observer.begin("retrieval")
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            joined.set()

    executor.execute.side_effect = execute
    pending = asyncio.create_task(service.submit("domain", actor, created.id, incoming))
    try:
        await asyncio.wait_for(started.wait(), 2)
        if initial_cancel == "owned":
            pending.cancel()
        else:
            await service.cancel("domain", actor, created.id, incoming.request_id)
        await asyncio.wait_for(cleaning.wait(), 2)
        pending.cancel()
        await asyncio.sleep(0)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done() and not joined.is_set()
        assert not repo.items[created.id].turns[0].execution_terminated
        release.set()
        result = await asyncio.wait_for(pending, 2)
        assert joined.is_set() and result.turns[0].execution_terminated
        assert result.turns[0].status == "cancelled" and recorder.outcome.state == "cancelled"
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


async def test_explicit_cancel_is_preserved_when_completed_result_waits_for_persistence():
    service, repo, _, executor, actor, incoming = setup.__wrapped__()
    created = await seed_conversation(service, "domain", actor)
    reached, release, joined = (asyncio.Event() for _ in range(3))

    async def execute(**kwargs):
        try:
            return response()
        finally:
            joined.set()

    executor.execute.side_effect = execute
    recorder = BarrierRecorder("persistence", reached, release, joined)
    service.recorder = recorder
    locked = repo.locked

    @asynccontextmanager
    async def persistence_lock(*args):
        if recorder.persisting:
            assert joined.is_set()
            # Only the finalizer waits. The explicit cancel uses the saved repository
            # method so it can win before terminal persistence takes the aggregate lock.
            reached.set()
            await release.wait()
        async with locked(*args) as item:
            yield item

    repo.locked = persistence_lock
    pending = asyncio.create_task(service.submit("domain", actor, created.id, incoming))
    try:
        await asyncio.wait_for(reached.wait(), 2)
        repo.locked = locked
        cancelled = await service.cancel("domain", actor, created.id, incoming.request_id)
        assert cancelled.turns[0].status == "cancelled"
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
        release.set()
        result = await asyncio.wait_for(pending, 2)
        assert result.turns[0].status == "cancelled" and result.turns[0].response is None
        assert result.turns[0].execution_terminated
        assert recorder.outcome.state == "cancelled"
        assert recorder.outcome.error_code == "conversation_cancelled"
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


async def test_final_authority_error_propagates_after_repeated_cancel_and_terminal_record():
    service, repo, _, _, actor, incoming = setup.__wrapped__()
    recorder = Recorder()
    service.recorder = recorder
    created = await seed_conversation(service, "domain", actor)
    reached, release = asyncio.Event(), asyncio.Event()

    async def denied(*args):
        reached.set()
        await release.wait()
        raise AppError("not_found", "Synthetic current authority denial", 404)

    service.final_authority = denied
    pending = asyncio.create_task(service.submit("domain", actor, created.id, incoming))
    try:
        await asyncio.wait_for(reached.wait(), 2)
        for _ in range(3):
            pending.cancel()
            await asyncio.sleep(0)
        assert not pending.done()
        release.set()
        with pytest.raises(AppError) as error:
            await asyncio.wait_for(pending, 2)
        assert error.value.code == "not_found" and error.value.status_code == 404
        saved = repo.items[created.id].turns[0]
        assert saved.execution_terminated and saved.status == "failed"
        assert saved.response is None and saved.error_code == "not_found"
        assert recorder.outcome.state == "failed" and recorder.outcome.complete
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


async def test_observation_failure_does_not_replace_original_model_error_during_cleanup_cancel():
    service, _, _, executor, actor, incoming = setup.__wrapped__()
    joined, reached, release = (asyncio.Event() for _ in range(3))
    recorder = BarrierRecorder("observer_fail", reached, release, joined, fail=True)
    service.recorder = recorder
    created = await seed_conversation(service, "domain", actor)

    async def execute(**kwargs):
        await observer.begin("retrieval")
        try:
            raise AppError("model_unavailable", "Synthetic private provider error", 503)
        finally:
            joined.set()

    executor.execute.side_effect = execute
    pending = asyncio.create_task(service.submit("domain", actor, created.id, incoming))
    try:
        await asyncio.wait_for(reached.wait(), 2)
        for _ in range(3):
            pending.cancel()
            await asyncio.sleep(0)
        assert not pending.done()
        release.set()
        result = await asyncio.wait_for(pending, 2)
        assert result.turns[0].execution_terminated and result.turns[0].status == "failed"
        assert result.turns[0].error_code == "model_unavailable"
        assert result.turns[0].observation_complete is False
        assert recorder.outcome.error_code == "model_unavailable" and not recorder.outcome.complete
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


def local_http_fixture(handler, *, retries=0):
    selected = replace(local_deployment(), max_retries=retries)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
    runtime = LocalOpenAICompatibleRuntime(
        deployment=selected, endpoint="http://127.0.0.1:9999", client=client
    )
    request = GenerationRequest(
        question="Synthetic question", resolved_query="Synthetic question", history=(),
        evidence=(evidence(),), profile=replace(profile(), deployment=selected),
        correlation_id="synthetic-http-termination",
    )
    return client, runtime, request


def local_http_answer():
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps({"schema_version": 1, "claims": [{
            "text": evidence().text, "evidence_ids": [str(evidence().evidence_id)],
        }]}),
    }}]})


@pytest.mark.parametrize(
    "mode", ["cancel", "timeout", "transport", "retry_success", "context_timeout"],
)
async def test_local_http_unconfirmed_execution_is_persisted_and_blocks_next_question(mode):
    service, repo, _, executor, actor, incoming = setup.__wrapped__()
    created = await seed_conversation(service, "domain", actor)
    entered = asyncio.Event()
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        entered.set()
        if mode == "cancel":
            await asyncio.Event().wait()
        if mode == "transport":
            raise httpx.ReadError("synthetic private failure", request=request)
        if mode == "retry_success" and calls > 1:
            return local_http_answer()
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    client, runtime, request = local_http_fixture(handler, retries=int(mode == "retry_success"))
    async with client:
        async def execute(**kwargs):
            try:
                if mode == "context_timeout":
                    await runtime.contextualize(ContextualizationRequest(
                        question=request.question, history=(), profile=request.profile,
                    ))
                else:
                    await runtime.generate(request)
            except GenerationProviderError as exc:
                raise AppError(exc.code, "Synthetic safe provider error", 502) from None
            return response()

        executor.execute.side_effect = execute
        pending = asyncio.create_task(service.submit("domain", actor, created.id, incoming))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            if mode == "cancel":
                pending.cancel()
            result = await asyncio.wait_for(pending, 2)
            saved = repo.items[created.id].turns[0]
            assert saved.execution_terminated is False
            assert saved.error_code == "provider_termination_unconfirmed"
            assert saved.status == ("cancelled" if mode == "cancel" else "failed")
            assert saved.response is None
            assert result.turns[0].execution_terminated is False
            replay = await service.submit("domain", actor, created.id, incoming)
            assert replay.turns[0].error_code == saved.error_code
            with pytest.raises(AppError) as error:
                await service.submit("domain", actor, created.id, incoming.model_copy(update={
                    "request_id": uuid4(), "expected_revision": result.revision,
                }))
            assert error.value.code == "conversation_busy"
            assert executor.execute.await_count == 1
            assert calls == (2 if mode == "retry_success" else 1)
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def test_deleted_conversation_does_not_certify_unconfirmed_http_termination():
    service, repo, _, executor, actor, incoming = setup.__wrapped__()
    created = await seed_conversation(service, "domain", actor)
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.Event().wait()

    client, runtime, request = local_http_fixture(handler)
    async with client:
        async def execute(**kwargs):
            await runtime.generate(request)
            return response()

        executor.execute.side_effect = execute
        pending = asyncio.create_task(service.submit("domain", actor, created.id, incoming))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            current = await service.detail("domain", actor, created.id)
            await service.delete("domain", actor, created.id, current.revision)
            pending.cancel()
            with pytest.raises(AppError):
                await asyncio.wait_for(pending, 2)
            saved = repo.items[created.id]
            assert saved.deleted_at and saved.turns[0].query == ""
            assert saved.turns[0].execution_terminated is False
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def test_http_termination_scope_isolated_between_concurrent_conversations():
    bad_service, bad_repo, _, bad_executor, actor, bad_incoming = setup.__wrapped__()
    good_service, good_repo, _, good_executor, _, good_incoming = setup.__wrapped__()
    bad = await seed_conversation(bad_service, "domain", actor)
    good = await seed_conversation(good_service, "domain", actor)
    entered, release = asyncio.Event(), asyncio.Event()

    async def bad_handler(request):
        entered.set()
        await release.wait()
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    bad_client, bad_runtime, bad_request = local_http_fixture(bad_handler)
    good_client, good_runtime, good_request = local_http_fixture(lambda _: local_http_answer())
    async with bad_client, good_client:
        async def execute_bad(**kwargs):
            try:
                await bad_runtime.generate(bad_request)
            except GenerationProviderError as exc:
                raise AppError(exc.code, "Synthetic safe error", 502) from None
            return response()

        async def execute_good(**kwargs):
            await good_runtime.generate(good_request)
            return response()

        bad_executor.execute.side_effect = execute_bad
        good_executor.execute.side_effect = execute_good
        pending = asyncio.create_task(bad_service.submit("domain", actor, bad.id, bad_incoming))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            success = await good_service.submit("domain", actor, good.id, good_incoming)
            assert success.turns[0].status == "completed"
            assert good_repo.items[good.id].turns[0].execution_terminated
            release.set()
            await asyncio.wait_for(pending, 2)
            assert not bad_repo.items[bad.id].turns[0].execution_terminated
            # A later call in this task also has a fresh scope.
            again = await good_service.submit("domain", actor, good.id, good_incoming.model_copy(
                update={"request_id": uuid4(), "expected_revision": success.revision},
            ))
            assert again.turns[-1].execution_terminated
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize("cancel_after_response", [False, True])
async def test_context_http_completion_does_not_prove_later_generation_termination(
    cancel_after_response,
):
    service, repo, _, executor, actor, incoming = setup.__wrapped__()
    created = await seed_conversation(service, "domain", actor)
    reached = asyncio.Event()
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"resolved_query":"Synthetic question"}',
            }}]})
        if cancel_after_response:
            return local_http_answer()
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    client, runtime, request = local_http_fixture(handler)
    async with client:
        async def execute(**kwargs):
            try:
                await runtime.contextualize(ContextualizationRequest(
                    question=request.question, history=(), profile=request.profile,
                ))
                await runtime.generate(request)
                reached.set()
                await asyncio.Event().wait()
            except GenerationProviderError as exc:
                raise AppError(exc.code, "Synthetic safe error", 502) from None
            return response()

        executor.execute.side_effect = execute
        pending = asyncio.create_task(service.submit("domain", actor, created.id, incoming))
        try:
            if cancel_after_response:
                await asyncio.wait_for(reached.wait(), 2)
                pending.cancel()
            await asyncio.wait_for(pending, 2)
            saved = repo.items[created.id].turns[0]
            assert saved.execution_terminated is cancel_after_response
            assert saved.error_code == (
                "conversation_cancelled" if cancel_after_response
                else "provider_termination_unconfirmed"
            )
            assert calls == 2
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
