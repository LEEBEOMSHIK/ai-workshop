"""Bounded, request-owned process lifecycle. No CLI or model semantics.

Callers own authorization, executable registry and temporary-directory policy.
This primitive never merges the server environment or deletes request files.
"""

import ctypes as c
import math
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from ctypes import wintypes as w
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path


class ProcessFailure(StrEnum):
    VALIDATION = "validation"
    UNSUPPORTED_OS = "unsupported_os"
    START_FAILED = "start_failed"
    NONZERO_EXIT = "nonzero_exit"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    STDOUT_LIMIT = "stdout_limit"
    STDERR_LIMIT = "stderr_limit"
    OUTPUT_REJECTED = "output_rejected"
    IO_FAILED = "io_failed"
    CLEANUP_FAILED = "cleanup_failed"


@dataclass(frozen=True)
class ProcessLimits:
    timeout_seconds: float
    stdin_bytes: int
    stdout_bytes: int
    stderr_bytes: int
    cleanup_seconds: float = 5.0


@dataclass(frozen=True, repr=False)
class ProcessRequest:
    executable: Path
    argv: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]
    stdin: bytes
    limits: ProcessLimits


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int | None = None
    stdout: bytes = field(default=b"", repr=False)
    stderr: bytes = field(default=b"", repr=False)
    failure: ProcessFailure | None = None
    cleanup_verified: bool = True
    active_processes_after_cleanup: int | None = None


def _validate(request: ProcessRequest) -> bool:
    try:
        limits = request.limits
        if any(type(value) is not int or value < 0 or value > 64 * 1024 * 1024
               for value in (limits.stdin_bytes, limits.stdout_bytes, limits.stderr_bytes)):
            return False
        if any(not math.isfinite(value) or not 0 < value <= 3600
               for value in (limits.timeout_seconds, limits.cleanup_seconds)):
            return False
        if not isinstance(request.stdin, bytes) or len(request.stdin) > limits.stdin_bytes:
            return False
        for path in (request.executable, request.cwd):
            if not path.is_absolute() or "\0" in str(path):
                return False
            if any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)):
                return False
        if not request.executable.is_file() or not request.cwd.is_dir():
            return False
        if request.executable.suffix.lower() != ".exe":
            return False
        if not isinstance(request.argv, tuple) or any(
            not isinstance(arg, str) or "\0" in arg for arg in request.argv
        ):
            return False
        keys: set[str] = set()
        for key, value in request.environment.items():
            if (not isinstance(key, str) or not isinstance(value, str) or not key
                    or "=" in key or "\0" in key or "\0" in value or key.upper() in keys):
                return False
            keys.add(key.upper())
        command = subprocess.list2cmdline([str(request.executable), *request.argv])
        environment = "\0".join(f"{key}={value}" for key, value in request.environment.items())
        return (len(command.encode("utf-16-le")) // 2 < 32767
                and len(environment.encode("utf-16-le")) // 2 + 2 <= 32767)
    except (OSError, TypeError, ValueError, AttributeError):
        return False


class WindowsProcessRunner:
    def run(
        self, request: ProcessRequest, cancellation: threading.Event | None = None,
        *, stdout_observer: Callable[[bytes], bool] | None = None,
        capture_output: bool = True,
    ) -> ProcessResult:
        """Observe stdout with trusted, bounded synchronous validation only.

        The observer runs on the lifecycle thread and must return a bool promptly.
        False, a non-bool return or an Exception rejects output and triggers cleanup.
        Disabling capture discards both streams while preserving their byte limits.
        """
        if sys.platform != "win32":
            return ProcessResult(failure=ProcessFailure.UNSUPPORTED_OS)
        if (stdout_observer is not None and not callable(stdout_observer)
                or type(capture_output) is not bool):
            return ProcessResult(failure=ProcessFailure.VALIDATION)
        try:
            request = replace(request, environment=dict(request.environment))
        except (TypeError, ValueError, AttributeError, RuntimeError):
            return ProcessResult(failure=ProcessFailure.VALIDATION)
        if not _validate(request):
            return ProcessResult(failure=ProcessFailure.VALIDATION)
        if cancellation is not None and cancellation.is_set():
            return ProcessResult(failure=ProcessFailure.CANCELLED)
        return self._run_windows(request, cancellation, stdout_observer, capture_output)

    def _run_windows(
        self, request: ProcessRequest, cancellation: threading.Event | None,
        stdout_observer: Callable[[bytes], bool] | None, capture_output: bool,
    ) -> ProcessResult:
        import msvcrt

        from .windows_process_native import ExtendedLimits, Native, ProcessInfo, StartupInfoEx

        native = Native()
        api = native.dll
        job = 0
        process = ProcessInfo()
        assigned = False
        fds: set[int] = set()
        output = [bytearray(), bytearray()]
        byte_counts = [0, 0]
        failure: ProcessFailure | None = None
        exit_code: int | None = None
        count: int | None = None
        cleanup_ok = True
        writer: threading.Thread | None = None
        writer_failed = threading.Event()
        attribute_buffer = None
        attributes_initialized = False
        started = time.monotonic()

        def close_fd(fd: int) -> None:
            if fd in fds:
                fds.remove(fd)
                os.close(fd)

        def write_input(fd: int) -> None:
            try:
                remaining = memoryview(request.stdin)
                while remaining:
                    remaining = remaining[os.write(fd, remaining[:4096]):]
            except OSError:
                writer_failed.set()
            finally:
                try:
                    os.close(fd)
                except OSError:
                    writer_failed.set()

        def drain(fd: int, index: int, maximum: int) -> None:
            nonlocal failure
            available = w.DWORD()
            if not api.PeekNamedPipe(msvcrt.get_osfhandle(fd), None, 0, None,
                                     c.byref(available), None):
                if c.get_last_error() != 109:  # ERROR_BROKEN_PIPE is EOF.
                    failure = failure or ProcessFailure.IO_FAILED
                return
            if available.value:
                chunk = os.read(fd, min(available.value, 4096))
                room = max(0, maximum - byte_counts[index])
                byte_counts[index] += len(chunk)
                if capture_output:
                    output[index].extend(chunk[:room])
                if len(chunk) > room:
                    failure = failure or (
                        ProcessFailure.STDOUT_LIMIT if index == 0 else ProcessFailure.STDERR_LIMIT
                    )
                if (index == 0 and stdout_observer is not None and failure is None
                        and cleanup_ok and not writer_failed.is_set()):
                    try:
                        accepted = stdout_observer(chunk)
                    except Exception:
                        # Callback diagnostics may contain raw output; retain no exception.
                        accepted = False
                    if accepted is not True:
                        failure = ProcessFailure.OUTPUT_REJECTED

        try:
            job = int(api.CreateJobObjectW(None, None) or 0)
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
            if not job or not api.SetInformationJobObject(
                job, 9, c.byref(limits), c.sizeof(limits)
            ):
                raise OSError("job_setup_failed")
            stdin_read, stdin_write = os.pipe()
            fds.update((stdin_read, stdin_write))
            stdout_read, stdout_write = os.pipe()
            fds.update((stdout_read, stdout_write))
            stderr_read, stderr_write = os.pipe()
            fds.update((stderr_read, stderr_write))
            inherited = (stdin_read, stdout_write, stderr_write)
            for fd in inherited:
                os.set_inheritable(fd, True)
            handles = (w.HANDLE * 3)(*(msvcrt.get_osfhandle(fd) for fd in inherited))
            size = c.c_size_t()
            api.InitializeProcThreadAttributeList(None, 1, 0, c.byref(size))
            attribute_buffer = c.create_string_buffer(size.value)
            if not api.InitializeProcThreadAttributeList(attribute_buffer, 1, 0, c.byref(size)):
                raise OSError("attribute_setup_failed")
            attributes_initialized = True
            if not api.UpdateProcThreadAttribute(attribute_buffer, 0, 0x20002, handles,
                                                c.sizeof(handles), None, None):
                raise OSError("handle_list_failed")
            startup = StartupInfoEx()
            startup.startup.cb = c.sizeof(startup)
            startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = handles
            startup.attributes = c.cast(attribute_buffer, c.c_void_p)
            command = c.create_unicode_buffer(
                subprocess.list2cmdline([str(request.executable), *request.argv]))
            environment = c.create_unicode_buffer("\0".join(
                f"{key}={value}" for key, value in sorted(request.environment.items(),
                                                        key=lambda item: item[0].upper())
            ) + "\0\0")
            # CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT
            # | CREATE_NO_WINDOW. Explicit executable; never a shell.
            if not api.CreateProcessW(str(request.executable), command, None, None, True,
                                      0x08080404, environment, str(request.cwd),
                                      c.byref(startup), c.byref(process)):
                raise OSError("create_failed")
            if not api.AssignProcessToJobObject(job, process.process):
                raise OSError("assignment_failed")
            assigned = True
            for fd in inherited:
                close_fd(fd)
            if api.ResumeThread(process.thread) == 0xFFFFFFFF:
                raise OSError("resume_failed")
            writer = threading.Thread(target=write_input, args=(stdin_write,), daemon=True)
            writer.start()
            # The writer alone owns this descriptor after successful start.
            fds.remove(stdin_write)
            while True:
                drain(stdout_read, 0, request.limits.stdout_bytes)
                drain(stderr_read, 1, request.limits.stderr_bytes)
                if cancellation is not None and cancellation.is_set():
                    failure = failure or ProcessFailure.CANCELLED
                if time.monotonic() - started >= request.limits.timeout_seconds:
                    failure = failure or ProcessFailure.TIMEOUT
                state = api.WaitForSingleObject(process.process, 0)
                if state == 0:
                    code = w.DWORD()
                    if not api.GetExitCodeProcess(process.process, c.byref(code)):
                        raise OSError("exit_query_failed")
                    exit_code = code.value
                    failure = failure or (ProcessFailure.NONZERO_EXIT if exit_code else None)
                    break
                if state != 258:
                    raise OSError("wait_failed")
                if failure:
                    break
                time.sleep(0.005)
        except (OSError, ValueError, RuntimeError):
            failure = failure or ProcessFailure.START_FAILED
        finally:
            deadline = time.monotonic() + request.limits.cleanup_seconds
            if process.process:
                if assigned:
                    cleanup_ok = bool(api.TerminateJobObject(job, 1)) and cleanup_ok
                else:
                    cleanup_ok = bool(api.TerminateProcess(process.process, 1)) and cleanup_ok
                cleanup_ok = (api.WaitForSingleObject(process.process,
                    max(0, int((deadline - time.monotonic()) * 1000))) == 0) and cleanup_ok
            if job:
                try:
                    count = native.active_count(job)
                    while count and time.monotonic() < deadline:
                        time.sleep(0.005)
                        count = native.active_count(job)
                    cleanup_ok = count == 0 and cleanup_ok
                except OSError:
                    cleanup_ok = False
            if writer is not None and writer.ident is not None:
                writer.join(max(0, deadline - time.monotonic()))
                cleanup_ok = not writer.is_alive() and cleanup_ok
            if assigned:
                # Job is empty: drain the remaining finite pipe buffers without waiting for EOF.
                try:
                    for fd, index, maximum in (
                        (stdout_read, 0, request.limits.stdout_bytes),
                        (stderr_read, 1, request.limits.stderr_bytes),
                    ):
                        for _ in range(32):  # anonymous pipe backlog is bounded
                            drain(fd, index, maximum)
                except OSError:
                    failure = failure or ProcessFailure.IO_FAILED
            if attributes_initialized:
                api.DeleteProcThreadAttributeList(attribute_buffer)
            for handle in (process.thread, process.process, job):
                if handle:
                    cleanup_ok = native.close(handle) and cleanup_ok
            if writer is not None and writer.ident is not None and writer.is_alive():
                writer.join(max(0, deadline - time.monotonic()))
            for fd in tuple(fds):
                try:
                    close_fd(fd)
                except OSError:
                    cleanup_ok = False
        if not cleanup_ok:
            failure = ProcessFailure.CLEANUP_FAILED
        elif writer_failed.is_set():
            failure = failure or ProcessFailure.IO_FAILED
        return ProcessResult(
            exit_code, bytes(output[0]), bytes(output[1]), failure, cleanup_ok, count
        )
