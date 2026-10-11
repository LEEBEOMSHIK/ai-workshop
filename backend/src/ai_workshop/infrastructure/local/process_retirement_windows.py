"""Retire one exact Windows process lifetime through one owned handle.

This is not authorization: a controller must enforce the current committed
reservation, held ownership, durable journal and explicit approved target list.
No enumeration, ancestry traversal, shell or privilege elevation is performed.
"""

import ctypes
import os
import re
from ctypes import wintypes as w
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from threading import Thread, current_thread
from typing import Any, Protocol
from uuid import UUID, uuid4

RETIREMENT_EXIT_CODE = 1
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_PROCESS_RIGHTS = 0x00101001  # SYNCHRONIZE | QUERY_LIMITED_INFORMATION | TERMINATE


class ProcessRetirementError(ValueError):
    """Finite codes only; never contains a path, native message or private data."""


def _error(code: str = "process_retirement_denied") -> ProcessRetirementError:
    return ProcessRetirementError(code)


@dataclass(frozen=True, slots=True)
class ProcessLifetime:
    pid: int
    creation_time: str
    executable: Path = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False)
class ProcessRetirementToken:
    nonce: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True, eq=False)
class ProcessRetirementResult:
    lifetime: ProcessLifetime
    exit_code: int


class ProcessRetirementPort(Protocol):
    def open_process(self, pid: int) -> int: ...
    def identity(self, handle: int) -> ProcessLifetime: ...
    def thread_id(self) -> int: ...
    def terminate(self, handle: int, exit_code: int) -> None: ...
    def wait(self, handle: int, timeout_ms: int) -> int: ...
    def exit_code(self, handle: int) -> int: ...
    def close(self, handle: int) -> None: ...


@dataclass(slots=True)
class _OwnedProcess:
    handle: int
    lifetime: ProcessLifetime
    thread: Thread
    tid: int
    state: str = "opened"


def _validate(value: ProcessLifetime) -> None:
    if (
        type(value) is not ProcessLifetime
        or type(value.pid) is not int
        or not 0 < value.pid <= 0xFFFFFFFF
        or value.pid == os.getpid()
        or type(value.creation_time) is not str
        or re.fullmatch(r"[1-9][0-9]{0,19}", value.creation_time) is None
        or int(value.creation_time) > 0xFFFFFFFFFFFFFFFF
        or not isinstance(value.executable, Path)
    ):
        raise _error()
    path = PureWindowsPath(str(value.executable))
    if (
        not path.is_absolute()
        or re.fullmatch(r"[A-Za-z]:", path.drive) is None
        or path.suffix.lower() != ".exe"
        or len(str(path)) >= 32768
        or any(ch in str(path) for ch in ("\0", '"', "*", "?"))
        or any(part == ".." or part.endswith((".", " ")) or ":" in part for part in path.parts[1:])
    ):
        raise _error()


def _same_lifetime(actual: ProcessLifetime, expected: ProcessLifetime) -> bool:
    _validate(actual)
    # Exact spelling after separator normalization, not basename, case-folding,
    # filesystem alias resolution or an independently reopened PID.
    return (
        actual.pid == expected.pid
        and actual.creation_time == expected.creation_time
        and str(PureWindowsPath(actual.executable)) == str(PureWindowsPath(expected.executable))
    )


class WindowsProcessRetirement:
    def __init__(self, native: ProcessRetirementPort | None = None) -> None:
        self._native = native if native is not None else NativeWindowsProcessRetirement()
        self._tokens: dict[ProcessRetirementToken, _OwnedProcess] = {}
        self._opened: set[tuple[int, str, str]] = set()
        self._results: dict[ProcessRetirementResult, tuple[Thread, int]] = {}

    def open(self, expected: ProcessLifetime) -> ProcessRetirementToken:
        handle = None
        try:
            _validate(expected)
            tid = self._native.thread_id()
            if type(tid) is not int or tid <= 0:
                raise _error()
            key = (expected.pid, expected.creation_time, str(PureWindowsPath(expected.executable)))
            if key in self._opened:
                raise _error()
            self._opened.add(key)
            opened = self._native.open_process(expected.pid)
            if type(opened) is not int or not 0 < opened < (1 << (8 * ctypes.sizeof(w.HANDLE))) - 1:
                raise _error()
            handle = opened
            if not _same_lifetime(self._native.identity(handle), expected):
                raise _error()
            token = ProcessRetirementToken()
            self._tokens[token] = _OwnedProcess(handle, expected, current_thread(), tid)
            return token
        except BaseException as exc:
            clean = True
            if handle is not None:
                try:
                    self._native.close(handle)
                except BaseException:
                    clean = False
            if not isinstance(exc, Exception):
                raise
            raise _error(
                "process_retirement_denied" if clean else "process_retirement_cleanup_unknown"
            ) from None

    def _owned(self, token: ProcessRetirementToken) -> _OwnedProcess:
        if type(token) is not ProcessRetirementToken:
            raise _error()
        owned = self._tokens.get(token)
        if (
            owned is None
            or owned.state == "closed"
            or owned.thread is not current_thread()
            or type(tid := self._native.thread_id()) is not int
            or tid != owned.tid
        ):
            raise _error()
        return owned

    def retire(self, token: ProcessRetirementToken, timeout_ms: int) -> ProcessRetirementResult:
        try:
            owned = self._owned(token)
            if (
                owned.state != "opened"
                or type(timeout_ms) is not int
                or not 1 <= timeout_ms <= 60000
            ):
                raise _error()
        except Exception:
            raise _error() from None
        owned.state = "poisoned"  # Consume before any uncertain native operation.
        try:
            if not _same_lifetime(self._native.identity(owned.handle), owned.lifetime):
                raise _error()
            before = self._native.wait(owned.handle, 0)
            if type(before) is not int or before != _WAIT_TIMEOUT:
                raise _error()
            self._native.terminate(owned.handle, RETIREMENT_EXIT_CODE)
            wait = self._native.wait(owned.handle, timeout_ms)
            if type(wait) is not int or wait != _WAIT_OBJECT_0:
                raise _error()
            code = self._native.exit_code(owned.handle)
            if type(code) is not int or code != RETIREMENT_EXIT_CODE:
                raise _error()
            owned.state = "finished"
            result = ProcessRetirementResult(owned.lifetime, code)
            self._results[result] = (owned.thread, owned.tid)
            return result
        except Exception:
            raise _error("process_retirement_unknown") from None

    def assert_result(self, result: ProcessRetirementResult) -> None:
        try:
            if type(result) is not ProcessRetirementResult:
                raise _error()
            owner = self._results.get(result)
            tid = self._native.thread_id()
            if type(tid) is not int or owner is None or owner != (current_thread(), tid):
                raise _error()
        except Exception:
            raise _error() from None

    def close(self, token: ProcessRetirementToken) -> None:
        try:
            owned = self._owned(token)
        except Exception:
            raise _error() from None
        owned.state = "closed"  # Lost close ACK must not lead to closing a reused handle.
        try:
            self._native.close(owned.handle)
        except Exception:
            raise _error("process_retirement_cleanup_unknown") from None


class NativeWindowsProcessRetirement:
    def __init__(self) -> None:
        if os.name != "nt":
            raise _error()
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures: dict[str, tuple[list[Any], Any]] = {
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "GetProcessId": ([w.HANDLE], w.DWORD),
            "GetCurrentThreadId": ([], w.DWORD),
            "GetProcessTimes": ([w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4)], w.BOOL),
            "QueryFullProcessImageNameW": (
                [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)],
                w.BOOL,
            ),
            "TerminateProcess": ([w.HANDLE, w.UINT], w.BOOL),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "GetExitCodeProcess": ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self._kernel, name)
            function.argtypes, function.restype = args, result

    def open_process(self, pid: int) -> int:
        handle = self._kernel.OpenProcess(_PROCESS_RIGHTS, False, pid)
        if not handle:
            raise _error()
        return int(handle)

    def identity(self, handle: int) -> ProcessLifetime:
        created, exited, kernel, user = w.FILETIME(), w.FILETIME(), w.FILETIME(), w.FILETIME()
        if not self._kernel.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise _error()
        size, image = w.DWORD(32768), ctypes.create_unicode_buffer(32768)
        if (
            not self._kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size))
            or not 0 < size.value < 32768
        ):
            raise _error()
        pid = int(self._kernel.GetProcessId(handle))
        value = ProcessLifetime(
            pid, str((created.dwHighDateTime << 32) | created.dwLowDateTime), Path(image.value)
        )
        _validate(value)
        return value

    def thread_id(self) -> int:
        return int(self._kernel.GetCurrentThreadId())

    def terminate(self, handle: int, exit_code: int) -> None:
        if not self._kernel.TerminateProcess(handle, exit_code):
            raise _error("process_retirement_unknown")

    def wait(self, handle: int, timeout_ms: int) -> int:
        return int(self._kernel.WaitForSingleObject(handle, timeout_ms))

    def exit_code(self, handle: int) -> int:
        code = w.DWORD()
        if not self._kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise _error("process_retirement_unknown")
        return int(code.value)

    def close(self, handle: int) -> None:
        if not self._kernel.CloseHandle(handle):
            raise _error("process_retirement_cleanup_unknown")
