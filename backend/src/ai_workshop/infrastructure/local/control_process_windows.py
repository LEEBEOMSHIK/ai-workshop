"""Own a suspended Windows child and its Job, never a daemon-side operation.

Only the creating Python/native thread may use an exact issued token. A failed
resume/wait cannot be retried. Closing owned handles is cleanup, not settlement.
"""

import ctypes
import os
import subprocess
import time
from ctypes import wintypes as w
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from threading import Thread, current_thread
from typing import Any, Protocol
from uuid import UUID, uuid4


class ControlProcessError(ValueError):
    """Fixed error codes only: no paths, command, environment or private output."""


@dataclass(frozen=True, slots=True)
class ChildIdentity:
    pid: int
    creation_time: str
    job_id: UUID


@dataclass(frozen=True, slots=True, eq=False)
class ChildToken:
    child: ChildIdentity


@dataclass(frozen=True, slots=True)
class LocalProcessResult:
    child: ChildIdentity
    exit_code: int
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class NativeChild:
    process: int
    thread: int
    job: int
    stdout: int
    stderr: int
    pid: int
    creation_time: str
    stdin: int | None = None

    def handles(self) -> tuple[int, ...]:
        # Kill-on-close is applied first, even when another CloseHandle fails.
        handles = (self.job, self.thread, self.process, self.stdout, self.stderr)
        return handles if self.stdin is None else (*handles, self.stdin)


class ProcessPort(Protocol):
    def create(
        self, argv: tuple[str, ...], env: dict[str, str], cwd: Path, *, stdin_pipe: bool = False
    ) -> NativeChild: ...
    def thread_id(self) -> int: ...
    def resume(self, thread: int) -> int: ...
    def poll(self, process: int) -> bool: ...
    def active_processes(self, job: int) -> int: ...
    def read(self, pipe: int, limit: int) -> bytes: ...
    def write(self, pipe: int, data: memoryview) -> int: ...
    def exit_code(self, process: int) -> int: ...
    def close(self, handle: int) -> None: ...


@dataclass(slots=True)
class _OwnedChild:
    native: NativeChild
    thread: Thread
    tid: int
    state: str = "suspended"
    input_data: bytearray = field(default_factory=bytearray, repr=False)
    input_offset: int = 0
    stdin_closed: bool = False


def _launch_inputs(argv: tuple[str, ...], env: dict[str, str], cwd: Path) -> tuple[str, str]:
    try:
        if (
            type(argv) is not tuple
            or not argv
            or any(type(arg) is not str or "\0" in arg for arg in argv)
            or not PureWindowsPath(argv[0]).is_absolute()
            or PureWindowsPath(argv[0]).suffix.lower() != ".exe"
            or '"' in argv[0]
            or not isinstance(cwd, Path)
            or not PureWindowsPath(str(cwd)).is_absolute()
            or "\0" in str(cwd)
            or type(env) is not dict
        ):
            raise ValueError
        keys: set[str] = set()
        for key, value in env.items():
            if (
                type(key) is not str
                or type(value) is not str
                or not key
                or "=" in key
                or "\0" in key
                or "\0" in value
                or key.upper() in keys
            ):
                raise ValueError
            keys.add(key.upper())
        command = subprocess.list2cmdline(argv)
        environment = "\0".join(f"{key}={env[key]}" for key in sorted(env, key=str.upper)) + "\0\0"
        if (
            len(command.encode("utf-16-le")) // 2 >= 32767
            or len(environment.encode("utf-16-le")) // 2 > 32767
        ):
            raise ValueError
        str(cwd).encode("utf-16-le")
        return command, environment
    except Exception:
        raise ControlProcessError("control_process_launch_denied") from None


class WindowsControlProcess:
    def __init__(
        self,
        native: ProcessPort | None = None,
        *,
        max_output_bytes: int = 1024 * 1024,
        max_wait_ms: int = 60000,
        max_input_bytes: int = 65536,
    ) -> None:
        if (
            type(max_output_bytes) is not int
            or not 1 <= max_output_bytes <= 16 * 1024 * 1024
            or type(max_wait_ms) is not int
            or not 1 <= max_wait_ms <= 60000
            or type(max_input_bytes) is not int
            or not 1 <= max_input_bytes <= 1024 * 1024
        ):
            raise ControlProcessError("control_process_launch_denied")
        self._native = native if native is not None else NativeWindowsProcess()
        self._limit, self._max_wait_ms = max_output_bytes, max_wait_ms
        self._input_limit = max_input_bytes
        self._children: dict[ChildToken, _OwnedChild] = {}

    def create_suspended(
        self, argv: tuple[str, ...], env: dict[str, str], cwd: Path, *, stdin: bytes | None = None
    ) -> ChildToken:
        _launch_inputs(argv, env, cwd)
        if stdin is not None and (type(stdin) is not bytes or len(stdin) > self._input_limit):
            raise ControlProcessError("control_process_launch_denied")
        private_input = bytearray(stdin or b"")
        child = None
        try:
            tid = self._native.thread_id()
            if type(tid) is not int or tid <= 0:
                raise ValueError
            child = (
                self._native.create(argv, dict(env), cwd)
                if stdin is None
                else self._native.create(argv, dict(env), cwd, stdin_pipe=True)
            )
            if (
                type(child) is not NativeChild
                or any(type(h) is not int or h <= 0 for h in child.handles())
                or len(set(child.handles())) != (5 if stdin is None else 6)
                or (child.stdin is None) != (stdin is None)
                or type(child.pid) is not int
                or child.pid <= 0
                or type(child.creation_time) is not str
                or not child.creation_time.isascii()
                or not child.creation_time.isdecimal()
                or int(child.creation_time) <= 0
            ):
                raise ValueError
            token = ChildToken(ChildIdentity(child.pid, child.creation_time, uuid4()))
            self._children[token] = _OwnedChild(
                child, current_thread(), tid, input_data=private_input
            )
            return token
        except BaseException as exc:
            _wipe(private_input)
            clean = True
            if isinstance(child, NativeChild):
                clean = self._close_handles(child)
            if not isinstance(exc, Exception):
                raise
            if not clean or (
                isinstance(exc, ControlProcessError)
                and str(exc) == "control_process_cleanup_unknown"
            ):
                raise ControlProcessError("control_process_cleanup_unknown") from None
            raise ControlProcessError("control_process_launch_denied") from None

    def _owned(self, token: ChildToken) -> _OwnedChild:
        try:
            if type(token) is not ChildToken:
                raise ValueError
            owned = self._children.get(token)
            if owned is None or owned.thread is not current_thread() or owned.state == "closed":
                raise ValueError
            tid = self._native.thread_id()
            if type(tid) is not int or tid != owned.tid:
                raise ValueError
            return owned
        except Exception:
            raise ControlProcessError("control_process_token_denied") from None

    def resume(self, token: ChildToken) -> None:
        owned = self._owned(token)
        if owned.state != "suspended":
            raise ControlProcessError("control_process_token_denied")
        owned.state = "poisoned"  # Consume permission before an uncertain native ACK.
        try:
            previous = self._native.resume(owned.native.thread)
            if type(previous) is not int or previous != 1:
                raise ValueError
            owned.state = "resumed"
        except Exception:
            raise ControlProcessError("control_process_resume_unknown") from None
        finally:
            if owned.state == "poisoned":
                _wipe(owned.input_data)

    def wait(self, token: ChildToken, timeout_ms: int) -> LocalProcessResult:
        owned = self._owned(token)
        if (
            owned.state != "resumed"
            or type(timeout_ms) is not int
            or not 1 <= timeout_ms <= self._max_wait_ms
        ):
            raise ControlProcessError("control_process_token_denied")
        owned.state = "poisoned"
        stdout, stderr = bytearray(), bytearray()
        deadline = time.monotonic() + timeout_ms / 1000
        code = "control_process_wait_unknown"
        try:
            while True:
                received = False
                for handle, target in (
                    (owned.native.stdout, stdout),
                    (owned.native.stderr, stderr),
                ):
                    remaining = self._limit - len(stdout) - len(stderr)
                    part = self._native.read(handle, min(65536, remaining + 1))
                    if type(part) is not bytes:
                        raise ValueError
                    if len(part) > remaining:
                        code = "control_process_output_limit"
                        raise ValueError
                    received = received or bool(part)
                    target.extend(part)
                writer = owned.native.stdin
                if writer is not None and not owned.stdin_closed:
                    code = "control_process_input_unknown"
                    if owned.input_offset < len(owned.input_data):
                        with (
                            memoryview(owned.input_data) as data,
                            data[owned.input_offset : owned.input_offset + 4096] as part_view,
                        ):
                            written = self._native.write(writer, part_view)
                            if type(written) is not int or not 0 <= written <= len(part_view):
                                raise ValueError
                        owned.input_offset += written
                    if owned.input_offset == len(owned.input_data):
                        owned.stdin_closed = True  # Consume the close before a lost ACK.
                        code = "control_process_cleanup_unknown"
                        self._native.close(writer)
                        _wipe(owned.input_data)
                    code = "control_process_wait_unknown"
                signaled = self._native.poll(owned.native.process)
                active = self._native.active_processes(owned.native.job)
                if type(signaled) is not bool or type(active) is not int or active < 0:
                    raise ValueError
                if signaled and active == 0 and not received:
                    if writer is not None and not owned.stdin_closed:
                        code = "control_process_input_unknown"
                        raise ValueError
                    exit_code = self._native.exit_code(owned.native.process)
                    if type(exit_code) is not int or not 0 <= exit_code <= 0xFFFFFFFF:
                        raise ValueError
                    result = LocalProcessResult(
                        token.child, exit_code, bytes(stdout), bytes(stderr)
                    )
                    owned.state = "completed"
                    return result
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    code = "control_process_timeout"
                    raise ValueError
                if not received:
                    time.sleep(min(0.005, remaining_time))
        except Exception:
            raise ControlProcessError(code) from None
        finally:
            _wipe(owned.input_data)
            stdout.clear()
            stderr.clear()

    def _close_handles(self, child: NativeChild, *, stdin_closed: bool = False) -> bool:
        clean = True
        interruption: BaseException | None = None
        for handle in child.handles():
            if stdin_closed and handle == child.stdin:
                continue
            try:
                self._native.close(handle)
            except BaseException as exc:
                clean = False
                if not isinstance(exc, Exception) and interruption is None:
                    interruption = exc
        if interruption is not None:
            raise interruption
        return clean

    def close(self, token: ChildToken) -> None:
        owned = self._owned(token)
        owned.state = "closed"  # Never reuse handle numbers after a lost close ACK.
        _wipe(owned.input_data)
        if not self._close_handles(owned.native, stdin_closed=owned.stdin_closed):
            raise ControlProcessError("control_process_cleanup_unknown")


def _wipe(data: bytearray) -> None:
    data[:] = b"\0" * len(data)
    data.clear()


class SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", w.DWORD),
        ("lpSecurityDescriptor", w.LPVOID),
        ("bInheritHandle", w.BOOL),
    ]


class StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", w.DWORD),
        ("lpReserved", w.LPWSTR),
        ("lpDesktop", w.LPWSTR),
        ("lpTitle", w.LPWSTR),
        ("dwX", w.DWORD),
        ("dwY", w.DWORD),
        ("dwXSize", w.DWORD),
        ("dwYSize", w.DWORD),
        ("dwXCountChars", w.DWORD),
        ("dwYCountChars", w.DWORD),
        ("dwFillAttribute", w.DWORD),
        ("dwFlags", w.DWORD),
        ("wShowWindow", w.WORD),
        ("cbReserved2", w.WORD),
        ("lpReserved2", w.LPVOID),
        ("hStdInput", w.HANDLE),
        ("hStdOutput", w.HANDLE),
        ("hStdError", w.HANDLE),
    ]


class StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", StartupInfo), ("lpAttributeList", w.LPVOID)]


class ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", w.HANDLE),
        ("hThread", w.HANDLE),
        ("dwProcessId", w.DWORD),
        ("dwThreadId", w.DWORD),
    ]


class BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", w.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", w.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", w.DWORD),
        ("SchedulingClass", w.DWORD),
    ]


class IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", BasicLimitInformation),
        ("IoInfo", IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class BasicAccountingInformation(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", w.DWORD),
        ("TotalProcesses", w.DWORD),
        ("ActiveProcesses", w.DWORD),
        ("TotalTerminatedProcesses", w.DWORD),
    ]


class NativeWindowsProcess:
    """Win32 boundary; no shell, PID reopen, named Job or breakaway path."""

    def __init__(self, *, kernel: Any = None) -> None:
        if kernel is None and os.name != "nt":
            raise ControlProcessError("control_process_launch_denied")
        self._kernel = (
            kernel if kernel is not None else ctypes.WinDLL("kernel32", use_last_error=True)
        )
        self._security = (
            kernel if kernel is not None else ctypes.WinDLL("advapi32", use_last_error=True)
        )
        pointer = ctypes.POINTER
        signatures = {
            "CreateJobObjectW": ([w.LPVOID, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
            "CreatePipe": (
                [pointer(w.HANDLE), pointer(w.HANDLE), pointer(SecurityAttributes), w.DWORD],
                w.BOOL,
            ),
            "SetHandleInformation": ([w.HANDLE, w.DWORD, w.DWORD], w.BOOL),
            "CreateFileW": (
                [
                    w.LPCWSTR,
                    w.DWORD,
                    w.DWORD,
                    pointer(SecurityAttributes),
                    w.DWORD,
                    w.DWORD,
                    w.HANDLE,
                ],
                w.HANDLE,
            ),
            "InitializeProcThreadAttributeList": (
                [w.LPVOID, w.DWORD, w.DWORD, pointer(ctypes.c_size_t)],
                w.BOOL,
            ),
            "UpdateProcThreadAttribute": (
                [w.LPVOID, w.DWORD, ctypes.c_size_t, w.LPVOID, ctypes.c_size_t, w.LPVOID, w.LPVOID],
                w.BOOL,
            ),
            "DeleteProcThreadAttributeList": ([w.LPVOID], None),
            "CreateProcessW": (
                [
                    w.LPCWSTR,
                    w.LPWSTR,
                    w.LPVOID,
                    w.LPVOID,
                    w.BOOL,
                    w.DWORD,
                    w.LPVOID,
                    w.LPCWSTR,
                    pointer(StartupInfoEx),
                    pointer(ProcessInformation),
                ],
                w.BOOL,
            ),
            "GetProcessTimes": (
                [
                    w.HANDLE,
                    pointer(w.FILETIME),
                    pointer(w.FILETIME),
                    pointer(w.FILETIME),
                    pointer(w.FILETIME),
                ],
                w.BOOL,
            ),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "GetCurrentThreadId": ([], w.DWORD),
            "ResumeThread": ([w.HANDLE], w.DWORD),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "QueryInformationJobObject": (
                [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, pointer(w.DWORD)],
                w.BOOL,
            ),
            "PeekNamedPipe": (
                [w.HANDLE, w.LPVOID, w.DWORD, pointer(w.DWORD), pointer(w.DWORD), pointer(w.DWORD)],
                w.BOOL,
            ),
            "ReadFile": ([w.HANDLE, w.LPVOID, w.DWORD, pointer(w.DWORD), w.LPVOID], w.BOOL),
            "GetExitCodeProcess": ([w.HANDLE, pointer(w.DWORD)], w.BOOL),
            "CreateNamedPipeW": (
                [
                    w.LPCWSTR,
                    w.DWORD,
                    w.DWORD,
                    w.DWORD,
                    w.DWORD,
                    w.DWORD,
                    w.DWORD,
                    pointer(SecurityAttributes),
                ],
                w.HANDLE,
            ),
            "ConnectNamedPipe": ([w.HANDLE, w.LPVOID], w.BOOL),
            "GetNamedPipeClientProcessId": ([w.HANDLE, pointer(w.ULONG)], w.BOOL),
            "GetCurrentProcessId": ([], w.DWORD),
            "WriteFile": ([w.HANDLE, w.LPVOID, w.DWORD, pointer(w.DWORD), w.LPVOID], w.BOOL),
            "LocalFree": ([w.HLOCAL], w.HLOCAL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self._kernel, name)
            function.argtypes, function.restype = arguments, result
        convert = self._security.ConvertStringSecurityDescriptorToSecurityDescriptorW
        convert.argtypes = [w.LPCWSTR, w.DWORD, pointer(w.LPVOID), pointer(w.ULONG)]
        convert.restype = w.BOOL

    def create(
        self, argv: tuple[str, ...], env: dict[str, str], cwd: Path, *, stdin_pipe: bool = False
    ) -> NativeChild:
        command, environment = _launch_inputs(argv, env, cwd)
        if type(stdin_pipe) is not bool:
            raise ControlProcessError("control_process_launch_denied")
        kernel = self._kernel
        handles: list[int] = []
        temporary: list[int] = []
        attributes = None
        attributes_initialized = False
        process = ProcessInformation()
        child: NativeChild | None = None
        error: BaseException | None = None
        cleanup_unknown = False
        descriptor = w.LPVOID()
        writer = None

        def track(handle: Any) -> int:
            if not handle or handle == ctypes.c_void_p(-1).value:
                raise ValueError
            value = int(handle)
            handles.append(value)
            return value

        try:
            job = track(kernel.CreateJobObjectW(None, None))
            limits = ExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE only.
            if not kernel.SetInformationJobObject(
                job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise ValueError
            security = SecurityAttributes(ctypes.sizeof(SecurityAttributes), None, True)
            readers = []
            for _ in range(2):
                read, write = w.HANDLE(), w.HANDLE()
                try:
                    created_pipe = kernel.CreatePipe(
                        ctypes.byref(read), ctypes.byref(write), ctypes.byref(security), 0
                    )
                finally:
                    # Out handles remain ours if an interrupt loses CreatePipe's ACK.
                    for output in (read.value, write.value):
                        if output and output != ctypes.c_void_p(-1).value:
                            track(output)
                if not created_pipe or read.value is None or write.value is None:
                    raise ValueError
                readers.append(int(read.value))
                temporary.append(int(write.value))
                if not kernel.SetHandleInformation(read.value, 1, 0):
                    raise ValueError
            if stdin_pipe:
                if not self._security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    "D:P(A;;GA;;;OW)", 1, ctypes.byref(descriptor), None
                ):
                    raise ValueError
                private_security = SecurityAttributes(
                    ctypes.sizeof(SecurityAttributes), descriptor.value, False
                )
                pipe_name = rf"\\.\pipe\ai-workshop-private-{uuid4().hex}"
                # OUTBOUND | FIRST_PIPE_INSTANCE; BYTE | NOWAIT | REJECT_REMOTE_CLIENTS.
                writer = track(
                    kernel.CreateNamedPipeW(
                        pipe_name, 0x80002, 9, 1, 4096, 0, 0, ctypes.byref(private_security)
                    )
                )
                stdin = track(
                    kernel.CreateFileW(pipe_name, 0x80000000, 0, ctypes.byref(security), 3, 0, None)
                )
                temporary.append(stdin)
                # The reader was opened locally first. Any other state is uncertain;
                # never wait, reconnect, or accept LISTENING/NO_DATA/BUSY as connected.
                connected = kernel.ConnectNamedPipe(writer, None)
                if connected or ctypes.get_last_error() != 535:
                    raise ValueError
                client_pid = w.ULONG()
                if not kernel.GetNamedPipeClientProcessId(writer, ctypes.byref(client_pid)):
                    raise ValueError
                if client_pid.value != kernel.GetCurrentProcessId():
                    raise ValueError
            else:
                stdin = track(
                    kernel.CreateFileW("NUL", 0x80000000, 3, ctypes.byref(security), 3, 0x80, None)
                )
                temporary.append(stdin)
            inherited = (w.HANDLE * 3)(stdin, temporary[0], temporary[1])
            jobs = (w.HANDLE * 1)(job)
            size = ctypes.c_size_t()
            if (
                kernel.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
                or not 0 < size.value <= 1048576
            ):
                raise ValueError
            attributes = ctypes.create_string_buffer(size.value)
            if not kernel.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size)):
                raise ValueError
            attributes_initialized = True
            for key, value in ((0x20002, inherited), (0x2000D, jobs)):
                if not kernel.UpdateProcThreadAttribute(
                    attributes, 0, key, value, ctypes.sizeof(value), None, None
                ):
                    raise ValueError
            startup = StartupInfoEx()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.StartupInfo.dwFlags = 0x100  # STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = stdin
            startup.StartupInfo.hStdOutput, startup.StartupInfo.hStdError = temporary[:2]
            startup.lpAttributeList = ctypes.cast(attributes, w.LPVOID)
            command_buffer = ctypes.create_unicode_buffer(command)
            environment_buffer = ctypes.create_unicode_buffer(environment)
            # JOB_LIST places the child into the fresh Job in CreateProcess itself.
            # No AssignProcessToJobObject-after-create or breakaway fallback exists.
            if not kernel.CreateProcessW(
                argv[0],
                command_buffer,
                None,
                None,
                True,
                0x08080404,
                environment_buffer,
                str(cwd),
                ctypes.byref(startup),
                ctypes.byref(process),
            ):
                raise ValueError
            created, exited, system, user = w.FILETIME(), w.FILETIME(), w.FILETIME(), w.FILETIME()
            if not kernel.GetProcessTimes(
                process.hProcess,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(system),
                ctypes.byref(user),
            ):
                raise ValueError
            child = NativeChild(
                int(process.hProcess),
                int(process.hThread),
                job,
                readers[0],
                readers[1],
                int(process.dwProcessId),
                str((created.dwHighDateTime << 32) | created.dwLowDateTime),
                writer,
            )
        except BaseException as exc:
            error = exc
        finally:
            if descriptor.value:
                try:
                    if kernel.LocalFree(descriptor):
                        raise ValueError
                except BaseException as exc:
                    error = error or exc
                    cleanup_unknown = True
            # Out parameters still belong to us if a Python interrupt loses the ACK.
            for handle in (process.hThread, process.hProcess):
                if handle and int(handle) not in handles:
                    handles.append(int(handle))
            if attributes_initialized:
                try:
                    kernel.DeleteProcThreadAttributeList(attributes)
                except BaseException as exc:
                    error = error or exc
                    cleanup_unknown = True
            for handle in temporary:
                try:
                    self.close(handle)
                except BaseException as exc:
                    error = error or exc
                    cleanup_unknown = True
                handles.remove(handle)  # A lost close ACK must not cause a second close.
            if error is not None or child is None:
                # Job is first in this list: close it before process/thread/read handles.
                for handle in handles:
                    try:
                        self.close(handle)
                    except BaseException as exc:
                        error = error or exc
                        cleanup_unknown = True
        if error is not None and not isinstance(error, Exception):
            raise error from None
        if cleanup_unknown:
            raise ControlProcessError("control_process_cleanup_unknown") from None
        if error is not None or child is None:
            raise ControlProcessError("control_process_launch_denied") from None
        return child

    def thread_id(self) -> int:
        return int(self._kernel.GetCurrentThreadId())

    def resume(self, thread: int) -> int:
        return int(self._kernel.ResumeThread(thread))

    def poll(self, process: int) -> bool:
        result = self._kernel.WaitForSingleObject(process, 0)
        if result not in (0, 0x102):
            raise ControlProcessError("control_process_wait_unknown")
        return bool(result == 0)

    def active_processes(self, job: int) -> int:
        accounting = BasicAccountingInformation()
        if not self._kernel.QueryInformationJobObject(
            job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
        ):
            raise ControlProcessError("control_process_wait_unknown")
        return int(accounting.ActiveProcesses)

    def read(self, pipe: int, limit: int) -> bytes:
        available = w.DWORD()
        if not self._kernel.PeekNamedPipe(pipe, None, 0, None, ctypes.byref(available), None):
            if ctypes.get_last_error() == 109:  # ERROR_BROKEN_PIPE: all writers closed.
                return b""
            raise ControlProcessError("control_process_wait_unknown")
        size = min(available.value, limit)
        if size == 0:
            return b""
        buffer, received = ctypes.create_string_buffer(size), w.DWORD()
        if not self._kernel.ReadFile(pipe, buffer, size, ctypes.byref(received), None):
            if ctypes.get_last_error() == 109:
                return b""
            raise ControlProcessError("control_process_wait_unknown")
        if received.value > size:
            raise ControlProcessError("control_process_wait_unknown")
        return buffer.raw[: received.value]

    def exit_code(self, process: int) -> int:
        code = w.DWORD()
        if not self._kernel.GetExitCodeProcess(process, ctypes.byref(code)):
            raise ControlProcessError("control_process_wait_unknown")
        return int(code.value)

    def write(self, pipe: int, data: memoryview) -> int:
        # This handle is a synchronous NOWAIT byte pipe: zero/partial success is
        # capacity backpressure. No pending background I/O outlives this buffer.
        if not 0 < len(data) <= 4096 or data.readonly:
            raise ControlProcessError("control_process_input_unknown")
        buffer = (ctypes.c_char * len(data)).from_buffer_copy(data)
        written = w.DWORD()
        try:
            if not self._kernel.WriteFile(pipe, buffer, len(data), ctypes.byref(written), None):
                raise ControlProcessError("control_process_input_unknown")
            if written.value > len(data):
                raise ControlProcessError("control_process_input_unknown")
            return int(written.value)
        finally:
            # A retained native-call traceback must contain only a wiped copy, and
            # must not retain an export preventing the owner's input from clearing.
            ctypes.memset(buffer, 0, len(data))
            del buffer

    def close(self, handle: int) -> None:
        if not self._kernel.CloseHandle(handle):
            raise ControlProcessError("control_process_cleanup_unknown")
