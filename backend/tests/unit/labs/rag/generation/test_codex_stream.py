"""Incremental Codex validation using synthetic local processes, without a CLI."""

import importlib
import json
import os
import sys
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from ai_workshop.labs.rag.generation.codex_events import CodexEventLimits, CodexEventReceiver
from ai_workshop.labs.rag.generation.windows_process import (
    ProcessFailure,
    ProcessLimits,
    ProcessRequest,
    ProcessResult,
    WindowsProcessRunner,
)


def _wire(final_text: str = '{"synthetic":true}', newline: bytes = b"\n") -> bytes:
    events = [
        {"type": "thread.started", "thread_id": "synthetic-thread"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {
            "id": "answer", "type": "agent_message", "text": final_text,
        }},
        {"type": "turn.completed", "usage": {
            "input_tokens": 7, "cached_input_tokens": 0, "output_tokens": 3,
        }},
    ]
    lines = (json.dumps(event, ensure_ascii=False).encode() for event in events)
    return newline.join(lines) + newline


def _request(tmp_path: Path, script: str) -> ProcessRequest:
    return ProcessRequest(
        Path(sys.executable), ("-I", "-c", script), tmp_path,
        {"SystemRoot": os.environ.get("SYSTEMROOT", "")}, b"",
        ProcessLimits(2, 0, 8192, 8192),
    )


def _emit(payload: bytes, after: str = "") -> str:
    return f"import sys,time; sys.stdout.buffer.write({payload!r}); sys.stdout.flush(); " + after


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
def test_success_requires_complete_stream_exit_and_cleanup(tmp_path: Path) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.codex_stream")
    result = module.CodexStreamRunner().run(_request(tmp_path, _emit(_wire())), CodexEventLimits())
    assert result.events is not None
    assert result.events.final_text == '{"synthetic":true}'
    assert result.events.observed_model is None
    assert result.events.usage.output_tokens == 3
    assert result.process_failure is result.event_failure is None
    assert result.cleanup_verified and result.active_processes_after_cleanup == 0
    assert "synthetic" not in repr(result)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
def test_fragmented_utf8_crlf_is_validated_incrementally(tmp_path: Path) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.codex_stream")
    payload = _wire('{"text":"합성"}', b"\r\n")
    script = (
        f"import sys,time\nfor value in {payload!r}:\n"
        " sys.stdout.buffer.write(bytes([value])); sys.stdout.flush(); time.sleep(0.001)\n"
    )
    result = module.CodexStreamRunner().run(_request(tmp_path, script), CodexEventLimits())
    assert result.events is not None and result.events.final_text == '{"text":"합성"}'
    assert result.process_failure is result.event_failure is None
    assert result.cleanup_verified and result.active_processes_after_cleanup == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
@pytest.mark.parametrize("payload", [
    b'{"type":"unknown.synthetic"}\n',
    b'{"type":"item.started","item":{"id":"tool","type":"command_execution"}}\n',
])
def test_forbidden_live_event_reaps_child_and_descendant(tmp_path: Path, payload: bytes) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.codex_stream")
    script = (
        "import subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(30)']); "
        "sys.stderr.write(str(p.pid)); sys.stderr.flush(); "
        f"sys.stdout.buffer.write({payload!r}); sys.stdout.flush(); time.sleep(30)"
    )
    result = module.CodexStreamRunner().run(_request(tmp_path, script), CodexEventLimits())
    assert result.events is None
    assert result.process_failure is ProcessFailure.OUTPUT_REJECTED
    assert result.event_failure == "invalid_event"
    assert result.cleanup_verified and result.active_processes_after_cleanup == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
@pytest.mark.parametrize(("payload", "limits", "expected"), [
    (b'{"synthetic-sensitive-token": invalid}\n', CodexEventLimits(), "invalid_jsonl"),
    (b'{"type":"error","message":"synthetic-sensitive-token"}\n',
     CodexEventLimits(), "cli_failed"),
    (_wire() + b'{"type":"turn.started"}\n', CodexEventLimits(), "invalid_event_sequence"),
    (_wire()[:-1], CodexEventLimits(), "invalid_jsonl"),
    (b'{"type":"thread.started","thread_id":"only"}\n', CodexEventLimits(),
     "invalid_event_sequence"),
    (b"", CodexEventLimits(), "invalid_jsonl"),
    (_wire(), CodexEventLimits(max_line_bytes=20), "line_bytes_exceeded"),
    (_wire(), CodexEventLimits(max_total_bytes=40), "total_bytes_exceeded"),
    (_wire(), CodexEventLimits(max_events=3), "event_count_exceeded"),
    (_wire(), CodexEventLimits(max_input_tokens=6), "input_tokens_exceeded"),
    (_wire(), CodexEventLimits(max_output_tokens=2), "output_tokens_exceeded"),
])
def test_invalid_stream_never_releases_events_or_diagnostics(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, payload: bytes,
    limits: CodexEventLimits, expected: str,
) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.codex_stream")
    request = _request(tmp_path, _emit(payload, "sys.stderr.write('synthetic-sensitive-token')"))
    result = module.CodexStreamRunner().run(request, limits)
    assert result.events is None and result.event_failure == expected
    assert result.cleanup_verified and result.active_processes_after_cleanup == 0
    assert "synthetic-sensitive" not in repr(result) + caplog.text
    assert not hasattr(result, "stdout") and not hasattr(result, "stderr")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
@pytest.mark.parametrize(("after", "expected"), [
    ("sys.exit(7)", ProcessFailure.NONZERO_EXIT),
    ("time.sleep(30)", ProcessFailure.TIMEOUT),
    ("sys.stderr.buffer.write(b'x'*1000000)", ProcessFailure.STDERR_LIMIT),
])
def test_final_text_is_discarded_on_later_process_failure(
    tmp_path: Path, after: str, expected: ProcessFailure,
) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.codex_stream")
    request = _request(tmp_path, _emit(_wire("synthetic-sensitive-final"), after))
    result = module.CodexStreamRunner().run(request, CodexEventLimits())
    assert result.events is None and result.process_failure is expected
    assert result.cleanup_verified and result.active_processes_after_cleanup == 0
    assert "synthetic-sensitive" not in repr(result)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
def test_process_stdout_limit_applies_with_adapter_nonretention(tmp_path: Path) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.codex_stream")
    request = _request(tmp_path, _emit(_wire()))
    request = replace(request, limits=replace(request.limits, stdout_bytes=10))
    result = module.CodexStreamRunner().run(request, CodexEventLimits())
    assert result.events is None and result.process_failure is ProcessFailure.STDOUT_LIMIT
    assert result.cleanup_verified and result.active_processes_after_cleanup == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
def test_cancellation_discards_final_text(tmp_path: Path) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.codex_stream")
    event = threading.Event()
    timer = threading.Timer(0.5, event.set)
    timer.start()
    try:
        result = module.CodexStreamRunner().run(
            _request(tmp_path, _emit(_wire(), "time.sleep(30)")), CodexEventLimits(), event,
        )
    finally:
        timer.join()
    assert result.events is None and result.process_failure is ProcessFailure.CANCELLED
    assert result.cleanup_verified and result.active_processes_after_cleanup == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
def test_sequential_calls_have_fresh_receivers(tmp_path: Path) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.codex_stream")
    runner = module.CodexStreamRunner()
    for payload, expected in [(_wire("first"), "first"), (b"bad\n", None),
                              (_wire("second"), "second")]:
        result = runner.run(_request(tmp_path, _emit(payload)), CodexEventLimits())
        assert (result.events.final_text if result.events else None) == expected
        assert result.cleanup_verified and result.active_processes_after_cleanup == 0


class _CompletedProcess(WindowsProcessRunner):
    """Exercise adapter gate states unavailable from a well-behaved real runner."""

    def __init__(self, result: ProcessResult | Exception) -> None:
        self.result = result

    def run(
        self, request: ProcessRequest, cancellation: threading.Event | None = None,
        *, stdout_observer: Callable[[bytes], bool] | None = None, capture_output: bool = True,
    ) -> ProcessResult:
        assert capture_output is False and stdout_observer is not None
        assert stdout_observer(_wire("synthetic-sensitive-final")) is True
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.parametrize(("process_result", "expected", "cleanup"), [
    (ProcessResult(), ProcessFailure.IO_FAILED, True),
    (ProcessResult(exit_code=7, active_processes_after_cleanup=0),
     ProcessFailure.NONZERO_EXIT, True),
    (ProcessResult(exit_code=0, cleanup_verified=False), ProcessFailure.CLEANUP_FAILED, False),
    (ProcessResult(exit_code=0, active_processes_after_cleanup=1),
     ProcessFailure.CLEANUP_FAILED, False),
    (ProcessResult(exit_code=0), ProcessFailure.CLEANUP_FAILED, False),
    (ProcessResult(exit_code=0, failure=ProcessFailure.CLEANUP_FAILED, cleanup_verified=False),
     ProcessFailure.CLEANUP_FAILED, False),
    (RuntimeError("synthetic-sensitive-runner-exception"), ProcessFailure.IO_FAILED, False),
])
def test_adapter_rejects_unverified_process_results_without_finishing_receiver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    process_result: ProcessResult | Exception, expected: ProcessFailure, cleanup: bool,
) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.codex_stream")

    def forbidden_finish(self: CodexEventReceiver):
        pytest.fail("receiver.finish called before successful exit and cleanup")

    monkeypatch.setattr(CodexEventReceiver, "finish", forbidden_finish)
    result = module.CodexStreamRunner(_CompletedProcess(process_result)).run(
        _request(tmp_path, "pass"), CodexEventLimits(),
    )
    assert result.events is None and result.process_failure is expected
    assert result.cleanup_verified is cleanup
    assert "synthetic-sensitive" not in repr(result) + caplog.text
