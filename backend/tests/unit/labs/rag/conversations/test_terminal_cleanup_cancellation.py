"""Real conversation/observer ownership with offline cancellation barriers."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from starlette.requests import Request

from ai_workshop.labs.rag.executions import observer
from ai_workshop.labs.rag.generation.codex_http_lifecycle import run_until_disconnect
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.conversations.test_service import response, seed_conversation, setup
from tests.unit.labs.rag.executions.test_observer import Recorder


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
