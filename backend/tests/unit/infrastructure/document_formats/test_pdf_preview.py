import asyncio
import subprocess
import sys
import threading
from pathlib import Path

import pymupdf
import pytest

from ai_workshop.infrastructure.document_formats import pdf_preview as preview_module
from ai_workshop.infrastructure.document_formats.pdf_preview import (
    PdfInvalidError,
    PdfPageError,
    PdfPreviewLimitError,
    PdfPreviewRenderer,
    PdfPreviewTimeoutError,
)


def two_page_pdf() -> bytes:
    with pymupdf.open() as document:
        first = document.new_page(width=200, height=100)
        first.insert_text((20, 40), "Synthetic page one")
        second = document.new_page(width=120, height=80)
        second.insert_text((20, 40), "Synthetic page two")
        return bytes(document.tobytes())


@pytest.mark.asyncio
async def test_actual_two_page_pdf_is_inspected_and_rendered_in_worker() -> None:
    renderer = PdfPreviewRenderer(
        max_pages=2,
        max_pixels=20_000,
        timeout_seconds=5,
        max_concurrent=1,
    )

    inspection = await renderer.inspect(two_page_pdf())
    rendered = await renderer.render_page(two_page_pdf(), 2)

    assert inspection.page_count == 2
    assert rendered.page_count == 2
    assert rendered.content.startswith(b"\x89PNG\r\n\x1a\n")
    pixmap = pymupdf.Pixmap(rendered.content)
    assert (pixmap.width, pixmap.height) == (120, 80)


@pytest.mark.asyncio
async def test_invalid_page_pdf_and_pixel_bounds_are_explicit() -> None:
    content = two_page_pdf()
    renderer = PdfPreviewRenderer(
        max_pages=2,
        max_pixels=19_999,
        timeout_seconds=5,
        max_concurrent=1,
    )

    with pytest.raises(PdfPreviewLimitError):
        await renderer.render_page(content, 1)
    with pytest.raises(PdfPageError):
        await renderer.render_page(content, 3)
    with pytest.raises(PdfInvalidError):
        await renderer.inspect(b"%PDF-1.7\nnot-a-valid-pdf")


@pytest.mark.asyncio
async def test_input_limit_rejects_before_starting_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("oversize input must not start a worker")

    monkeypatch.setattr(preview_module.subprocess, "Popen", forbidden)
    renderer = PdfPreviewRenderer(
        max_input_bytes=16,
        max_pages=2,
        max_pixels=20_000,
        timeout_seconds=5,
        max_concurrent=1,
    )

    with pytest.raises(PdfPreviewLimitError):
        await renderer.inspect(b"x" * 17)


@pytest.mark.asyncio
async def test_worker_spawn_failure_is_a_safe_operational_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_spawn(*_args: object, **_kwargs: object) -> object:
        raise OSError("C:/sensitive/runtime/path")

    monkeypatch.setattr(preview_module.subprocess, "Popen", fail_spawn)
    renderer = PdfPreviewRenderer(
        max_pages=2,
        max_pixels=20_000,
        timeout_seconds=5,
        max_concurrent=1,
    )

    with pytest.raises(preview_module.PdfPreviewWorkerError) as failure:
        await renderer.inspect(two_page_pdf())

    assert "sensitive" not in str(failure.value)


def _slow_worker(tmp_path: Path) -> Path:
    worker = tmp_path / "slow_worker.py"
    worker.write_text(
        "import time\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    return worker


def _gate_first_worker_reap(
    monkeypatch: pytest.MonkeyPatch,
    slow_worker: Path,
) -> tuple[
    list[subprocess.Popen[bytes]],
    threading.Event,
    threading.Event,
]:
    real_popen = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []
    terminate_called = threading.Event()
    allow_reap = threading.Event()
    calls = 0

    def gated_first_worker(
        args: list[str],
        **kwargs: object,
    ) -> subprocess.Popen[bytes]:
        nonlocal calls
        calls += 1
        command = [sys.executable, "-I", str(slow_worker)] if calls == 1 else args
        process = real_popen(command, **kwargs)
        processes.append(process)
        if calls == 1:
            real_terminate = process.terminate
            real_wait = process.wait

            def observed_terminate() -> None:
                real_terminate()
                terminate_called.set()

            def gated_wait(*args: object, **kwargs: object) -> int:
                assert terminate_called.wait(timeout=5)
                assert allow_reap.wait(timeout=5)
                return real_wait(*args, **kwargs)

            process.terminate = observed_terminate
            process.wait = gated_wait
        return process

    monkeypatch.setattr(preview_module.subprocess, "Popen", gated_first_worker)
    return processes, terminate_called, allow_reap


async def _event_is_set(event: threading.Event) -> None:
    assert await asyncio.wait_for(asyncio.to_thread(event.wait, 5), timeout=6)


@pytest.mark.asyncio
async def test_timeout_terminates_reaps_and_releases_slot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_popen = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []
    calls = 0
    slow_worker = _slow_worker(tmp_path)

    def first_worker_is_slow(
        args: list[str],
        **kwargs: object,
    ) -> subprocess.Popen[bytes]:
        nonlocal calls
        calls += 1
        command = [sys.executable, "-I", str(slow_worker)] if calls == 1 else args
        process = real_popen(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(preview_module.subprocess, "Popen", first_worker_is_slow)
    renderer = PdfPreviewRenderer(
        max_pages=2,
        max_pixels=20_000,
        timeout_seconds=1,
        max_concurrent=1,
    )

    with pytest.raises(PdfPreviewTimeoutError):
        await renderer.inspect(two_page_pdf())
    result = await renderer.inspect(two_page_pdf())

    assert result.page_count == 2
    assert processes[0].returncode is not None


@pytest.mark.asyncio
async def test_cancellation_terminates_reaps_and_releases_slot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_popen = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []
    calls = 0
    slow_worker = _slow_worker(tmp_path)

    def first_worker_is_slow(
        args: list[str],
        **kwargs: object,
    ) -> subprocess.Popen[bytes]:
        nonlocal calls
        calls += 1
        command = [sys.executable, "-I", str(slow_worker)] if calls == 1 else args
        process = real_popen(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(preview_module.subprocess, "Popen", first_worker_is_slow)
    renderer = PdfPreviewRenderer(
        max_pages=2,
        max_pixels=20_000,
        timeout_seconds=5,
        max_concurrent=1,
    )
    task = asyncio.create_task(renderer.inspect(two_page_pdf()))
    while not processes:
        await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    result = await renderer.inspect(two_page_pdf())

    assert result.page_count == 2
    assert processes[0].returncode is not None


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_release_slot_before_reap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    processes, terminate_called, allow_reap = _gate_first_worker_reap(
        monkeypatch,
        _slow_worker(tmp_path),
    )
    renderer = PdfPreviewRenderer(
        max_pages=2,
        max_pixels=20_000,
        timeout_seconds=5,
        max_concurrent=1,
    )
    owner = asyncio.create_task(renderer.inspect(two_page_pdf()))
    contender: asyncio.Task[object] | None = None
    try:
        while not processes:
            await asyncio.sleep(0)
        owner.cancel()
        await _event_is_set(terminate_called)
        owner.cancel()
        await asyncio.sleep(0)
        owner.cancel()
        contender = asyncio.create_task(renderer.inspect(two_page_pdf()))
        await asyncio.sleep(0.05)

        assert not owner.done()
        assert len(processes) == 1

        allow_reap.set()
        with pytest.raises(asyncio.CancelledError):
            await owner
        result = await contender
        assert result.page_count == 2
    finally:
        allow_reap.set()
        if not owner.done():
            owner.cancel()
        if contender is not None and not contender.done():
            contender.cancel()
        await asyncio.gather(
            owner,
            *(tuple([contender]) if contender is not None else ()),
            return_exceptions=True,
        )
    assert processes[0].returncode is not None


@pytest.mark.asyncio
async def test_cancellation_during_timeout_cleanup_waits_for_reap_and_releases_slot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    processes, terminate_called, allow_reap = _gate_first_worker_reap(
        monkeypatch,
        _slow_worker(tmp_path),
    )
    renderer = PdfPreviewRenderer(
        max_pages=2,
        max_pixels=20_000,
        timeout_seconds=1,
        max_concurrent=1,
    )
    owner = asyncio.create_task(renderer.inspect(two_page_pdf()))
    contender: asyncio.Task[object] | None = None
    try:
        await _event_is_set(terminate_called)
        owner.cancel()
        await asyncio.sleep(0)
        owner.cancel()
        contender = asyncio.create_task(renderer.inspect(two_page_pdf()))
        await asyncio.sleep(0.05)

        assert not owner.done()
        assert len(processes) == 1

        allow_reap.set()
        with pytest.raises(asyncio.CancelledError):
            await owner
        result = await contender
        assert result.page_count == 2
    finally:
        allow_reap.set()
        if not owner.done():
            owner.cancel()
        if contender is not None and not contender.done():
            contender.cancel()
        await asyncio.gather(
            owner,
            *(tuple([contender]) if contender is not None else ()),
            return_exceptions=True,
        )
    assert processes[0].returncode is not None


@pytest.mark.asyncio
async def test_worker_concurrency_never_exceeds_configured_slots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_popen = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []
    slow_worker = _slow_worker(tmp_path)

    def every_worker_is_slow(
        _args: list[str],
        **kwargs: object,
    ) -> subprocess.Popen[bytes]:
        process = real_popen([sys.executable, "-I", str(slow_worker)], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(preview_module.subprocess, "Popen", every_worker_is_slow)
    renderer = PdfPreviewRenderer(
        max_pages=2,
        max_pixels=20_000,
        timeout_seconds=5,
        max_concurrent=2,
    )
    tasks = [asyncio.create_task(renderer.inspect(two_page_pdf())) for _ in range(3)]
    while len(processes) < 2:
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)

    assert len(processes) == 2

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert all(process.returncode is not None for process in processes)
