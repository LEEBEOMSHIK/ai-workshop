import asyncio
from pathlib import Path
from threading import Event

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.local_model_host import LocalModelHost, LocalModelSpec


def spec(tmp_path: Path) -> LocalModelSpec:
    return LocalModelSpec(
        model_id="synthetic/model", revision="a" * 40,
        snapshot_path=tmp_path, max_input_tokens=1024,
    )


async def wait_event(event: Event) -> None:
    async with asyncio.timeout(3):
        while not event.is_set():
            await asyncio.sleep(0.001)


async def test_host_reuses_loaded_model_and_closes(tmp_path: Path) -> None:
    loaded = []

    def loader(model_spec):
        engine = object()
        loaded.append(engine)
        return engine

    host = LocalModelHost(loader=loader)
    first = await host.run(spec(tmp_path), lambda engine, stop, deadline: engine, timeout=2)
    second = await host.run(spec(tmp_path), lambda engine, stop, deadline: engine, timeout=2)
    assert first is second
    assert len(loaded) == 1
    await host.aclose()
    with pytest.raises(GenerationProviderError, match="deployment_not_ready"):
        await host.run(spec(tmp_path), lambda *_: None, timeout=2)


async def test_repeated_cancel_keeps_admission_until_worker_exits(tmp_path: Path) -> None:
    started, stopping, release, exited = Event(), Event(), Event(), Event()
    host = LocalModelHost(loader=lambda _: object())

    def work(engine, stop, deadline):
        started.set()
        assert stop.wait(3)
        stopping.set()
        assert release.wait(3)
        exited.set()

    task = asyncio.create_task(host.run(spec(tmp_path), work, timeout=10))
    try:
        await wait_event(started)
        task.cancel()
        await wait_event(stopping)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        with pytest.raises(GenerationProviderError, match="provider_busy"):
            await host.run(spec(tmp_path), lambda *_: None, timeout=1)
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert exited.is_set()
    assert await host.run(spec(tmp_path), lambda *_: "next", timeout=1) == "next"
    await host.aclose()


async def test_timeout_drains_worker_before_reporting_failure(tmp_path: Path) -> None:
    started, stopping, release, exited = Event(), Event(), Event(), Event()
    host = LocalModelHost(loader=lambda _: object())

    def work(engine, stop, deadline):
        started.set()
        assert stop.wait(3)
        stopping.set()
        assert release.wait(3)
        exited.set()

    task = asyncio.create_task(host.run(spec(tmp_path), work, timeout=0.05))
    try:
        await wait_event(started)
        await wait_event(stopping)
        assert not task.done()
        with pytest.raises(GenerationProviderError, match="provider_busy"):
            await host.run(spec(tmp_path), lambda *_: None, timeout=1)
    finally:
        release.set()
    with pytest.raises(GenerationProviderError, match="provider_timeout"):
        await task
    assert exited.is_set()
    assert await host.run(spec(tmp_path), lambda *_: "next", timeout=1) == "next"
    await host.aclose()


async def test_cancel_during_timeout_drain_wins_after_native_termination(tmp_path: Path) -> None:
    stopping, release, exited = Event(), Event(), Event()
    host = LocalModelHost(loader=lambda _: object())

    def work(engine, stop, deadline):
        assert stop.wait(3)
        stopping.set()
        assert release.wait(3)
        exited.set()

    task = asyncio.create_task(host.run(spec(tmp_path), work, timeout=0.05))
    try:
        await wait_event(stopping)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert exited.is_set()
    await host.aclose()


async def test_loading_and_inference_failure_discard_cache(tmp_path: Path) -> None:
    calls = 0

    def loader(model_spec):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("private loader detail")
        return object()

    host = LocalModelHost(loader=loader)
    with pytest.raises(GenerationProviderError, match="deployment_not_ready"):
        await host.run(spec(tmp_path), lambda *_: None, timeout=2)

    def fail(*_):
        raise RuntimeError("private document detail")

    with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
        await host.run(spec(tmp_path), fail, timeout=2)
    assert await host.run(spec(tmp_path), lambda *_: "reloaded", timeout=2) == "reloaded"
    assert calls == 3
    await host.aclose()


async def test_shutdown_signals_and_drains_active_work(tmp_path: Path) -> None:
    started, stopping, release = Event(), Event(), Event()
    host = LocalModelHost(loader=lambda _: object())

    def work(engine, stop, deadline):
        started.set()
        assert stop.wait(3)
        stopping.set()
        assert release.wait(3)

    task = asyncio.create_task(host.run(spec(tmp_path), work, timeout=10))
    await wait_event(started)
    closing = asyncio.create_task(host.aclose())
    try:
        await wait_event(stopping)
        assert not closing.done()
    finally:
        release.set()
    with pytest.raises(GenerationProviderError, match="deployment_not_ready"):
        await task
    await closing


async def test_shutdown_from_another_loop_still_drains_native_work(tmp_path: Path) -> None:
    started, stopping, release = Event(), Event(), Event()
    host = LocalModelHost(loader=lambda _: object())

    def work(engine, stop, deadline):
        started.set()
        assert stop.wait(3)
        stopping.set()
        assert release.wait(3)

    task = asyncio.create_task(host.run(spec(tmp_path), work, timeout=10))
    await wait_event(started)
    closing = asyncio.create_task(asyncio.to_thread(lambda: asyncio.run(host.aclose())))
    try:
        await wait_event(stopping)
        await asyncio.sleep(0.02)
        assert not closing.done()
    finally:
        release.set()
    with pytest.raises(GenerationProviderError, match="deployment_not_ready"):
        await task
    await closing


@pytest.mark.parametrize("overrides", [
    {"revision": "main"}, {"snapshot_path": "relative/path"},
    {"device": "cuda"}, {"dtype": "float16"}, {"max_input_tokens": 0},
])
def test_spec_rejects_unpinned_or_unsupported_configuration(tmp_path: Path, overrides) -> None:
    values = spec(tmp_path).model_dump() | overrides
    with pytest.raises(ValidationError):
        LocalModelSpec.model_validate(values)
