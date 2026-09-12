"""Real synthetic Windows children; never invokes a model or account."""

import importlib
import os
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest


def test_runner_module_exists() -> None:
    from importlib.util import find_spec

    assert find_spec("ai_workshop.labs.rag.generation.windows_process") is not None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
@pytest.mark.parametrize(
    ("script", "failure", "stdout", "stderr"),
    [
        ("import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())", None, b"hello", b""),
        ("import sys; sys.stderr.write('private'); sys.exit(7)", "nonzero_exit", b"", b"private"),
        ("import time; time.sleep(30)", "timeout", b"", b""),
        ("import sys; sys.stdout.buffer.write(b'x'*1000000)", "stdout_limit", None, b""),
        ("import sys; sys.stderr.buffer.write(b'x'*1000000)", "stderr_limit", b"", None),
    ],
)
def test_real_process_outcomes(
    tmp_path: Path, script: str, failure: str | None, stdout: bytes | None,
    stderr: bytes | None,
) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.windows_process")
    request = module.ProcessRequest(
        Path(sys.executable), ("-I", "-c", script), tmp_path,
        {"SystemRoot": os.environ["SYSTEMROOT"]}, b"hello",
        module.ProcessLimits(1.0, 100, 1024, 1024),
    )
    result = module.WindowsProcessRunner().run(request)
    assert result.failure == failure
    assert result.cleanup_verified
    assert result.active_processes_after_cleanup == 0
    assert len(result.stdout) <= 1024 and len(result.stderr) <= 1024
    if stdout is not None:
        assert result.stdout == stdout
    if stderr is not None:
        assert result.stderr == stderr
    assert "private" not in repr(result)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
def test_cancellation_and_parent_exit_reap_descendants(tmp_path: Path) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.windows_process")
    for cancel in (False, True):
        script = (
            "import subprocess,sys,time; "
            "p=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(30)']); "
            "print(p.pid,flush=True); " + ("time.sleep(30)" if cancel else "sys.exit(0)")
        )
        request = module.ProcessRequest(
            Path(sys.executable), ("-I", "-c", script), tmp_path,
            {"SystemRoot": os.environ["SYSTEMROOT"]}, b"",
            module.ProcessLimits(5, 100, 1024, 1024),
        )
        event = threading.Event()
        timer = threading.Timer(0.6, event.set)
        if cancel:
            timer.start()
        try:
            result = module.WindowsProcessRunner().run(request, event)
        finally:
            if cancel:
                timer.join()
        assert result.stdout.strip().isdigit()
        assert result.failure == ("cancelled" if cancel else None)
        assert result.cleanup_verified and result.active_processes_after_cleanup == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
def test_unicode_argv_stdin_and_explicit_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.windows_process")
    monkeypatch.setenv("WORKSHOP_SYNTHETIC_SECRET", "must-not-inherit")
    script = (
        "import os,sys; "
        "assert 'WORKSHOP_SYNTHETIC_SECRET' not in os.environ; "
        "sys.stdout.buffer.write(sys.argv[1].encode()+b'|'+sys.stdin.buffer.read()); "
        "sys.stderr.buffer.write(os.environ['EXPLICIT'].encode())"
    )
    request = module.ProcessRequest(
        Path(sys.executable), ("-I", "-c", script, '한글 \\"argument'), tmp_path,
        {"SystemRoot": os.environ["SYSTEMROOT"], "EXPLICIT": "명시"}, "입력".encode(),
        module.ProcessLimits(2, 1024, 1024, 1024),
    )
    result = module.WindowsProcessRunner().run(request)
    assert result.failure is None
    assert result.stdout == '한글 \\"argument|입력'.encode()
    assert result.stderr == "명시".encode()
    assert result.cleanup_verified


@pytest.mark.skipif(sys.platform != "win32", reason="Windows validation")
def test_invalid_requests_never_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.windows_process")
    request = module.ProcessRequest(
        Path(sys.executable), ("-I", "-c", "pass"), tmp_path, {}, b"",
        module.ProcessLimits(2, 1024, 1024, 1024),
    )

    def forbidden(*args: object) -> None:
        pytest.fail("validation reached process creation")

    monkeypatch.setattr(module.WindowsProcessRunner, "_run_windows", forbidden)
    for invalid in (
        replace(request, executable=Path("relative.exe")),
        replace(request, cwd=tmp_path / "missing"),
        replace(request, argv=("nul\0value",)),
        replace(request, environment={"a": "one", "A": "two"}),
        replace(request, environment={"invalid=key": "value"}),
        replace(request, environment={"key": "nul\0value"}),
        replace(request, environment={"key": "x" * 40000}),
        replace(request, stdin=b"x" * 1025),
        replace(request, limits=module.ProcessLimits(float("nan"), 0, 1, 1)),
        replace(request, limits=module.ProcessLimits(1, 0, -1, 1)),
    ):
        result = module.WindowsProcessRunner().run(invalid)
        assert result.failure == "validation"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
def test_start_failure_and_failed_cleanup_are_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.windows_process")
    native = importlib.import_module("ai_workshop.labs.rag.generation.windows_process_native")
    invalid_exe = tmp_path / "invalid.exe"
    invalid_exe.write_bytes(b"synthetic invalid PE")
    request = module.ProcessRequest(
        invalid_exe, (), tmp_path, {}, b"", module.ProcessLimits(2, 100, 100, 100),
    )
    failed = module.WindowsProcessRunner().run(request)
    assert failed.failure == "start_failed"
    assert failed.cleanup_verified
    assert str(tmp_path) not in repr(failed)

    def unavailable(*args: object) -> int:
        raise OSError("synthetic private diagnostic")

    monkeypatch.setattr(native.Native, "active_count", unavailable)
    result = module.WindowsProcessRunner().run(replace(
        request, executable=Path(sys.executable), argv=("-I", "-c", "print('private')"),
    ))
    assert result.failure == "cleanup_failed"
    assert not result.cleanup_verified
    assert "private" not in repr(result)


def test_unsupported_os_does_not_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.windows_process")
    # Replace the module reference, avoiding global sys.platform mutation in pytest.
    from types import SimpleNamespace

    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="linux"))
    assert module.WindowsProcessRunner().run(None).failure == "unsupported_os"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows cleanup regression")
def test_writer_start_failure_still_reaps_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.windows_process")
    request = module.ProcessRequest(
        Path(sys.executable), ("-I", "-c", "import time; time.sleep(30)"), tmp_path,
        {}, b"", module.ProcessLimits(2, 100, 100, 100),
    )

    def unavailable(*args: object) -> None:
        raise RuntimeError("synthetic worker start failure")

    monkeypatch.setattr(threading.Thread, "start", unavailable)
    result = module.WindowsProcessRunner().run(request)
    assert result.failure == "start_failed"
    assert result.cleanup_verified and result.active_processes_after_cleanup == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows bounded input")
def test_unread_stdin_cannot_block_timeout(tmp_path: Path) -> None:
    module = importlib.import_module("ai_workshop.labs.rag.generation.windows_process")
    request = module.ProcessRequest(
        Path(sys.executable), ("-I", "-c", "import time; time.sleep(30)"), tmp_path,
        {}, b"x" * 1000000, module.ProcessLimits(0.3, 1000000, 100, 100),
    )
    result = module.WindowsProcessRunner().run(request)
    assert result.failure == "timeout"
    assert result.cleanup_verified and result.active_processes_after_cleanup == 0


def _stream_request(tmp_path: Path, script: str):
    from ai_workshop.labs.rag.generation.windows_process import ProcessLimits, ProcessRequest

    return ProcessRequest(
        Path(sys.executable), ("-I", "-c", script), tmp_path,
        {"SystemRoot": os.environ.get("SYSTEMROOT", "")}, b"",
        ProcessLimits(2, 0, 8192, 8192),
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
@pytest.mark.parametrize("behavior", ["reject", "exception", "nonbool"])
def test_observer_failure_stops_live_child_and_descendant(tmp_path: Path, behavior: str) -> None:
    from ai_workshop.labs.rag.generation.windows_process import ProcessFailure, WindowsProcessRunner

    request = _stream_request(tmp_path, (
        "import subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(30)']); "
        "print(p.pid,flush=True); time.sleep(30)"
    ))
    seen: list[bytes] = []

    def observe(chunk: bytes):
        seen.append(chunk)
        if behavior == "exception":
            raise RuntimeError("synthetic-sensitive-observer-diagnostic")
        return False if behavior == "reject" else 1

    result = WindowsProcessRunner().run(request, stdout_observer=observe, capture_output=False)
    assert result.failure is ProcessFailure.OUTPUT_REJECTED
    assert result.stdout == result.stderr == b""
    assert result.cleanup_verified and result.active_processes_after_cleanup == 0
    assert len(seen) == 1 and seen[0].strip().isdigit()
    assert "synthetic-sensitive" not in repr(result)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
@pytest.mark.parametrize("capture", [False, True])
def test_observer_receives_complete_output_through_exit(tmp_path: Path, capture: bool) -> None:
    from ai_workshop.labs.rag.generation.windows_process import WindowsProcessRunner

    request = _stream_request(tmp_path, (
        "import sys; sys.stdout.buffer.write(b'x'*8000); sys.stderr.buffer.write(b'private')"
    ))
    seen: list[bytes] = []

    def observe(chunk: bytes) -> bool:
        seen.append(chunk)
        return True

    result = WindowsProcessRunner().run(request, stdout_observer=observe, capture_output=capture)
    assert result.failure is None
    assert b"".join(seen) == b"x" * 8000
    assert result.stdout == (b"x" * 8000 if capture else b"")
    assert result.stderr == (b"private" if capture else b"")
    assert result.cleanup_verified and result.active_processes_after_cleanup == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object integration")
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_nonretention_still_enforces_cumulative_byte_caps(tmp_path: Path, stream: str) -> None:
    from ai_workshop.labs.rag.generation.windows_process import WindowsProcessRunner

    request = _stream_request(tmp_path, f"import sys; sys.{stream}.buffer.write(b'x'*1000000)")
    seen: list[bytes] = []

    def observe(chunk: bytes) -> bool:
        seen.append(chunk)
        return True

    result = WindowsProcessRunner().run(request, stdout_observer=observe, capture_output=False)
    assert result.failure == f"{stream}_limit"
    assert result.stdout == result.stderr == b""
    assert sum(map(len, seen)) <= request.limits.stdout_bytes
    assert result.cleanup_verified and result.active_processes_after_cleanup == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows validation")
@pytest.mark.parametrize("options", [{"stdout_observer": 1}, {"capture_output": 1},
                                          {"capture_output": None}])
def test_invalid_observer_options_never_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, options: dict,
) -> None:
    from ai_workshop.labs.rag.generation.windows_process import ProcessFailure, WindowsProcessRunner

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid observer options reached process creation")

    monkeypatch.setattr(WindowsProcessRunner, "_run_windows", forbidden)
    result = WindowsProcessRunner().run(_stream_request(tmp_path, "pass"), **options)
    assert result.failure is ProcessFailure.VALIDATION


@pytest.mark.skipif(sys.platform != "win32", reason="Windows post-exit draining")
@pytest.mark.parametrize("outcome", ["accept", "reject", "cleanup_failure"])
def test_post_exit_output_obeys_observer_and_prior_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    from ai_workshop.labs.rag.generation.windows_process import WindowsProcessRunner
    from ai_workshop.labs.rag.generation.windows_process_native import Native

    original_init = Native.__init__

    class ExitGatedPipes:
        """Keep real pipe bytes pending until the real process has exited."""

        def __init__(self, api):
            self.api = api
            self.exited = False

        def __getattr__(self, name: str):
            return getattr(self.api, name)

        def WaitForSingleObject(self, *args):
            result = self.api.WaitForSingleObject(*args)
            self.exited = self.exited or result == 0
            return result

        def PeekNamedPipe(self, handle, buffer, size, read, available, remaining):
            result = self.api.PeekNamedPipe(handle, buffer, size, read, available, remaining)
            if not self.exited:
                available._obj.value = 0
            return result

    def init(native: Native) -> None:
        original_init(native)
        native.dll = ExitGatedPipes(native.dll)

    def unavailable(*args: object) -> int:
        raise OSError("synthetic-sensitive-cleanup-diagnostic")

    monkeypatch.setattr(Native, "__init__", init)
    if outcome == "cleanup_failure":
        monkeypatch.setattr(Native, "active_count", unavailable)
    seen: list[bytes] = []

    def observe(chunk: bytes) -> bool:
        seen.append(chunk)
        return outcome != "reject"

    result = WindowsProcessRunner().run(
        _stream_request(tmp_path, "print('tail',flush=True)"),
        stdout_observer=observe, capture_output=False,
    )
    assert result.failure == {
        "accept": None, "reject": "output_rejected", "cleanup_failure": "cleanup_failed",
    }[outcome]
    assert b"".join(seen) == (b"" if outcome == "cleanup_failure" else b"tail\r\n")
    assert result.stdout == result.stderr == b""
    assert result.cleanup_verified is (outcome != "cleanup_failure")
    if outcome != "cleanup_failure":
        assert result.active_processes_after_cleanup == 0
