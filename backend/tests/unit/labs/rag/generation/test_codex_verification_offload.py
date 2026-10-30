"""Full runner inspection stays fresh without blocking unrelated asyncio work."""

import asyncio
import gc
import hashlib
import threading
import weakref
from pathlib import Path

import pytest

from ai_workshop.labs.rag.generation.codex_runner_registry import (
    CodexRunnerRegistry,
    CodexRunnerSettings,
)
from tests.unit.labs.rag.generation.test_codex_verification import (
    _verify,
    verification_fixture,
)


async def _status(fixture):
    return await fixture.service.status(
        actor_id=fixture.context.actor_id,
        configuration_version_id=fixture.context.configuration_version_id,
    )


async def _checkpoint():
    """Let callbacks already queued on this loop run, without a timed sleep."""
    loop = asyncio.get_running_loop()
    completed = loop.create_future()
    loop.call_soon(completed.set_result, None)
    await completed


@pytest.mark.parametrize("operation, inspections", [("status", 1), ("health", 1), ("verify", 3)])
async def test_every_async_binding_inspects_outside_the_event_loop(operation, inspections):
    f = verification_fixture()
    loop_thread = threading.get_ident()
    inspection_threads = []
    original = f.registry.resolve

    def record(reference):
        inspection_threads.append(threading.get_ident())
        return original(reference)

    f.registry.resolve = record
    if operation == "verify":
        await _verify(f)
    elif operation == "health":
        await f.service.health(context=f.context, profile=f.request.profile)
    else:
        await _status(f)

    assert len(inspection_threads) == inspections
    assert all(thread != loop_thread for thread in inspection_threads)


class HeldInspection:
    def __init__(self, registry, *, fail=False):
        self.original = registry.resolve
        self.loop = asyncio.get_running_loop()
        self.loop_thread = threading.get_ident()
        self.entered = asyncio.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.calls = 0
        self.active = 0
        self.peak = 0
        self.fail = fail

    def __call__(self, reference):
        with self.lock:
            self.calls += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        self.loop.call_soon_threadsafe(self.entered.set)
        try:
            # The pre-fix implementation must fail promptly rather than deadlock
            # the test loop while we are proving that inspection is offloaded.
            if threading.get_ident() == self.loop_thread:
                return self.original(reference)
            assert self.release.wait(10), "test did not release the held inspection"
            if self.fail:
                raise ValueError("synthetic inspection failure")
            return self.original(reference)
        finally:
            with self.lock:
                self.active -= 1


async def test_unrelated_event_loop_work_completes_during_full_inspection():
    f = verification_fixture()
    held = HeldInspection(f.registry)
    f.registry.resolve = held
    task = asyncio.create_task(_status(f))
    try:
        await asyncio.wait_for(held.entered.wait(), 3)
        await _checkpoint()
        assert not task.done(), "inspection blocked the loop until it had already finished"
        assert held.active == 1
    finally:
        held.release.set()
        await asyncio.wait_for(task, 3)
    assert held.active == 0


@pytest.mark.parametrize("fail", [False, True])
async def test_repeated_cancellation_holds_shared_slot_and_cancelled_waiter_never_runs(fail):
    first, second, third = (verification_fixture() for _ in range(3))
    held = HeldInspection(first.registry, fail=fail)
    for fixture in (first, second, third):
        fixture.registry.resolve = held
    running = asyncio.create_task(_status(first))
    tasks = [running]

    async def request(fixture, entered):
        entered.set()
        return await _status(fixture)

    try:
        await asyncio.wait_for(held.entered.wait(), 3)
        assert not running.done(), "inspection must be off the event loop"
        running.cancel()
        await _checkpoint()
        assert not running.done(), "cancelled owner must join its actual inspection"

        waiting_started = asyncio.Event()
        waiting = asyncio.create_task(request(second, waiting_started))
        tasks.append(waiting)
        await waiting_started.wait()
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

        last_started = asyncio.Event()
        last = asyncio.create_task(request(third, last_started))
        tasks.append(last)
        await last_started.wait()
        running.cancel()
        await _checkpoint()
        assert not running.done() and not last.done()
        assert held.calls == held.active == held.peak == 1
    finally:
        held.release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 3)

    assert isinstance(results[0], asyncio.CancelledError)
    assert not isinstance(results[-1], BaseException)
    assert held.calls == 2 and held.active == 0 and held.peak == 1


async def test_cancelled_verification_records_failure_after_its_inspection_finishes():
    f = verification_fixture()
    held = HeldInspection(f.registry)
    f.registry.resolve = held
    task = asyncio.create_task(_verify(f))
    try:
        await asyncio.wait_for(held.entered.wait(), 3)
        assert not task.done()
        task.cancel()
        await _checkpoint()
        assert not task.done() and not f.proofs.attempts and not f.executor.calls
    finally:
        held.release.set()
        results = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
    assert isinstance(results[0], asyncio.CancelledError)
    assert len(f.proofs.attempts) == 1
    assert f.proofs.attempts[0].safe_error_code == "codex_verification_cancelled"
    assert not f.proofs.attempts[0].success and not f.executor.calls
    assert held.active == 0


async def test_full_digest_is_rechecked_after_a_successful_passive_status(tmp_path: Path):
    f = verification_fixture()
    install = tmp_path / "install"
    install.mkdir()
    executable = install / "synthetic.exe"
    original = b"synthetic executable; never launched"
    executable.write_bytes(original)
    requests = tmp_path / "requests"
    requests.mkdir()
    f.service._registry = CodexRunnerRegistry(
        {
            f.registry.runner.reference: CodexRunnerSettings(
                executable=executable,
                executable_sha256=hashlib.sha256(original).hexdigest(),
                expected_cli_version="1.2.3",
                request_root=requests,
            )
        },
        environment="test",
        protected_roots=(tmp_path / "repo",),
    )
    assert (await _verify(f)).ready
    assert (await _status(f)).ready
    executable.write_bytes(b"X" + original[1:])
    failed = await _status(f)
    assert not failed.ready and failed.safe_error_code == "codex_verification_required"
    executable.write_bytes(original)
    assert (await _status(f)).ready
    assert len(f.executor.calls) == 2


def test_contended_inspection_limit_does_not_retain_closed_event_loops():
    loop_refs = []

    async def run():
        loop_refs.append(weakref.ref(asyncio.get_running_loop()))
        first, second = verification_fixture(), verification_fixture()
        held = HeldInspection(first.registry)
        first.registry.resolve = second.registry.resolve = held
        running = asyncio.create_task(_status(first))
        waiting = None
        try:
            await asyncio.wait_for(held.entered.wait(), 3)
            assert not running.done()
            waiting = asyncio.create_task(_status(second))
            await _checkpoint()
            assert not waiting.done()
        finally:
            held.release.set()
            await asyncio.gather(running, *([waiting] if waiting is not None else []))

    asyncio.run(run())
    asyncio.run(run())
    gc.collect()
    assert all(reference() is None for reference in loop_refs)
