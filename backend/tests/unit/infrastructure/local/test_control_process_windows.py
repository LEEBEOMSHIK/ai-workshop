"""Owned-child lifecycle tests; kernel fakes never launch a process or daemon."""

import ctypes
import importlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

import pytest


def module():
    name = "ai_workshop.infrastructure.local.control_process_windows"
    assert importlib.util.find_spec(name) is not None, "owned suspended-child runtime is missing"
    return importlib.import_module(name)


class Kernel:
    def __init__(self):
        self.calls = []
        self.previous_suspend = 1
        self.signaled = True
        self.active = 0
        self.output = {104: bytearray(b"private stdout"), 105: bytearray(b"private stderr")}
        self.fail = None

    def create(self, argv, env, cwd):
        self.calls.append(("create", argv, dict(env), cwd))
        return module().NativeChild(101, 102, 103, 104, 105, 1234, "987654321")

    def thread_id(self):
        return 9

    def resume(self, handle):
        self.calls.append(("resume", handle))
        if self.fail == "resume":
            raise OSError("private kernel detail")
        return self.previous_suspend

    def poll(self, handle):
        self.calls.append(("poll", handle))
        if self.fail == "poll":
            raise OSError("private kernel detail")
        return self.signaled

    def active_processes(self, handle):
        self.calls.append(("active", handle))
        return self.active

    def read(self, handle, limit):
        part = bytes(self.output[handle][:limit])
        del self.output[handle][:limit]
        return part

    def exit_code(self, handle):
        return 17

    def close(self, handle):
        self.calls.append(("close", handle))
        if self.fail == handle:
            raise OSError("private close detail")


def case(**options):
    kernel = Kernel()
    runtime = module().WindowsControlProcess(native=kernel, **options)
    token = runtime.create_suspended(
        (r"C:\owned\helper.exe", "a b"), {"SYNTHETIC": "1"}, Path(r"C:\owned")
    )
    return runtime, kernel, token


def test_suspended_identity_single_resume_and_local_completion():
    runtime, kernel, token = case()
    assert token.child.pid == 1234 and token.child.creation_time == "987654321"
    assert type(token.child.job_id) is UUID
    assert not any(call[0] == "resume" for call in kernel.calls)
    with pytest.raises(module().ControlProcessError):
        runtime.wait(token, 10)
    runtime.resume(token)
    with pytest.raises(module().ControlProcessError):
        runtime.resume(token)
    result = runtime.wait(token, 100)
    assert result.child is token.child and result.exit_code == 17
    assert (result.stdout, result.stderr) == (b"private stdout", b"private stderr")
    assert "private" not in repr(result)
    assert [c for c in kernel.calls if c[0] == "resume"] == [("resume", 102)]
    runtime.close(token)
    assert [c[1] for c in kernel.calls if c[0] == "close"] == [103, 102, 101, 104, 105]
    with pytest.raises(module().ControlProcessError):
        runtime.close(token)


@pytest.mark.parametrize("previous", [0, 2, 0xFFFFFFFF, True])
def test_nonexact_resume_count_poison_prevents_replay(previous):
    runtime, kernel, token = case()
    kernel.previous_suspend = previous
    with pytest.raises(module().ControlProcessError, match="control_process_resume_unknown"):
        runtime.resume(token)
    with pytest.raises(module().ControlProcessError):
        runtime.resume(token)
    with pytest.raises(module().ControlProcessError):
        runtime.wait(token, 100)
    assert len([c for c in kernel.calls if c[0] == "resume"]) == 1
    runtime.close(token)


def test_resume_ack_loss_is_sanitized_and_never_retried():
    runtime, kernel, token = case()
    kernel.fail = "resume"
    with pytest.raises(module().ControlProcessError) as failure:
        runtime.resume(token)
    assert str(failure.value) == "control_process_resume_unknown"
    with pytest.raises(module().ControlProcessError):
        runtime.resume(token)
    runtime.close(token)
    assert len([c for c in kernel.calls if c[0] == "resume"]) == 1


@pytest.mark.parametrize("signaled,active", [(False, 0), (True, 1)])
def test_completion_requires_both_root_exit_and_empty_job(signaled, active):
    runtime, kernel, token = case()
    kernel.signaled, kernel.active = signaled, active
    runtime.resume(token)
    with pytest.raises(module().ControlProcessError, match="control_process_timeout"):
        runtime.wait(token, 1)
    with pytest.raises(module().ControlProcessError):
        runtime.wait(token, 100)
    with pytest.raises(module().ControlProcessError):
        runtime.resume(token)
    runtime.close(token)


def test_private_output_limit_is_combined_and_failure_has_no_body():
    runtime, _, token = case(max_output_bytes=20)
    runtime.resume(token)
    with pytest.raises(module().ControlProcessError) as failure:
        runtime.wait(token, 100)
    assert str(failure.value) == "control_process_output_limit"
    with pytest.raises(module().ControlProcessError):
        runtime.wait(token, 100)
    runtime.close(token)


@pytest.mark.parametrize("method", ["resume", "wait", "close"])
def test_forged_token_and_foreign_runtime_cannot_operate_owned_handles(method):
    runtime, kernel, token = case()
    forged = module().ChildToken(token.child)
    other = module().WindowsControlProcess(native=Kernel())
    before = list(kernel.calls)
    for owner, candidate in ((runtime, forged), (other, token)):
        with pytest.raises(module().ControlProcessError):
            getattr(owner, method)(candidate, *([100] if method == "wait" else []))
    assert kernel.calls == before
    runtime.close(token)


@pytest.mark.parametrize("method", ["resume", "wait", "close"])
def test_foreign_thread_denied_even_with_reused_native_tid(method):
    runtime, kernel, token = case()
    before = list(kernel.calls)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(getattr(runtime, method), token, *([100] if method == "wait" else []))
        with pytest.raises(module().ControlProcessError):
            future.result()
    assert kernel.calls == before
    runtime.close(token)


def test_close_failure_attempts_all_owned_handles_but_never_retries_close():
    runtime, kernel, token = case()
    kernel.fail = 103
    with pytest.raises(module().ControlProcessError, match="control_process_cleanup_unknown"):
        runtime.close(token)
    assert [c[1] for c in kernel.calls if c[0] == "close"] == [103, 102, 101, 104, 105]
    with pytest.raises(module().ControlProcessError):
        runtime.close(token)
    assert len([c for c in kernel.calls if c[0] == "close"]) == 5


@pytest.mark.parametrize("timeout", [0, -1, True, 60001, 0xFFFFFFFF])
def test_unbounded_or_invalid_wait_rejected_without_native_wait(timeout):
    runtime, kernel, token = case()
    runtime.resume(token)
    with pytest.raises(module().ControlProcessError):
        runtime.wait(token, timeout)
    assert not any(c[0] == "poll" for c in kernel.calls)
    runtime.close(token)


@pytest.mark.parametrize(
    "argv,env,cwd",
    [
        ((), {}, Path(r"C:\owned")),
        (("helper.exe",), {}, Path(r"C:\owned")),
        ((r"C:\owned\helper.exe", "bad\0arg"), {}, Path(r"C:\owned")),
        ((r"C:\owned\helper.exe",), {"A=B": "v"}, Path(r"C:\owned")),
        ((r"C:\owned\helper.exe",), {"PATH": "x", "Path": "y"}, Path(r"C:\owned")),
        ((r"C:\owned\helper.exe",), {}, Path("relative")),
    ],
)
def test_ambiguous_launch_inputs_never_create_a_child(argv, env, cwd):
    kernel = Kernel()
    runtime = module().WindowsControlProcess(native=kernel)
    with pytest.raises(module().ControlProcessError, match="control_process_launch_denied"):
        runtime.create_suspended(argv, env, cwd)
    assert kernel.calls == []


class Function:
    def __init__(self, action):
        self.action = action

    def __call__(self, *args):
        return self.action(*args)


class Win32:
    """Actual ctypes structures pass through production code; only Win32 is faked."""

    def __init__(self, failure=None):
        self.failure = failure
        self.next_handle = 200
        self.open = set()
        self.closed = []
        self.inherited = set()
        self.attributes = {}
        self.deleted = 0
        self.created = []
        self.job_limit = None
        self.output = b"synthetic capture"
        self.poll_result = 0
        self.active = 0
        self.resume_result = 1
        for name in (
            "CreateJobObjectW",
            "SetInformationJobObject",
            "CreatePipe",
            "SetHandleInformation",
            "CreateFileW",
            "InitializeProcThreadAttributeList",
            "UpdateProcThreadAttribute",
            "DeleteProcThreadAttributeList",
            "CreateProcessW",
            "GetProcessTimes",
            "CloseHandle",
            "GetCurrentThreadId",
            "ResumeThread",
            "WaitForSingleObject",
            "QueryInformationJobObject",
            "PeekNamedPipe",
            "ReadFile",
            "GetExitCodeProcess",
            "CreateNamedPipeW",
            "ConnectNamedPipe",
            "GetNamedPipeClientProcessId",
            "GetCurrentProcessId",
            "WriteFile",
            "LocalFree",
            "ConvertStringSecurityDescriptorToSecurityDescriptorW",
        ):
            setattr(self, name, Function(lambda *args, name=name: self.call(name, *args)))

    def handle(self, inherit=False):
        self.next_handle += 1
        self.open.add(self.next_handle)
        if inherit:
            self.inherited.add(self.next_handle)
        return self.next_handle

    def call(self, name, *args):
        if name == self.failure:
            return 0
        if name == "CreateJobObjectW":
            assert args == (None, None)
            return self.handle()
        if name == "SetInformationJobObject":
            self.job_limit = args[2]._obj.BasicLimitInformation.LimitFlags
        elif name == "CreatePipe":
            inherit = bool(args[2]._obj.bInheritHandle)
            args[0]._obj.value, args[1]._obj.value = self.handle(inherit), self.handle(inherit)
        elif name == "SetHandleInformation":
            self.inherited.discard(args[0])
        elif name == "CreateFileW":
            assert args[0] == "NUL" or args[0].startswith("\\\\.\\pipe\\")
            assert args[1] == 0x80000000
            return self.handle(bool(args[3]._obj.bInheritHandle))
        elif name == "InitializeProcThreadAttributeList":
            assert args[1:3] == (2, 0)
            args[3]._obj.value = 256
            return 0 if args[0] is None else 1
        elif name == "UpdateProcThreadAttribute":
            handles = ctypes.cast(args[3], ctypes.POINTER(ctypes.c_void_p))
            self.attributes[args[2]] = tuple(
                handles[i] for i in range(args[4] // ctypes.sizeof(ctypes.c_void_p))
            )
        elif name == "DeleteProcThreadAttributeList":
            self.deleted += 1
        elif name == "CreateProcessW":
            startup = args[8]._obj.StartupInfo
            environment = args[6]
            index, pieces = 0, []
            while environment[index] != "\0":
                part = []
                while environment[index] != "\0":
                    part.append(environment[index])
                    index += 1
                pieces.append("".join(part))
                index += 1
            self.created.append(
                {
                    "app": args[0],
                    "command": args[1].value,
                    "process_security": args[2],
                    "thread_security": args[3],
                    "inherit": args[4],
                    "flags": args[5],
                    "env": pieces,
                    "cwd": args[7],
                    "attributes": dict(self.attributes),
                    "stdio": (startup.hStdInput, startup.hStdOutput, startup.hStdError),
                    "startup_flags": startup.dwFlags,
                    "startup_size": startup.cb,
                }
            )
            pi = args[9]._obj
            pi.hProcess, pi.hThread = self.handle(), self.handle()
            pi.dwProcessId, pi.dwThreadId = 1234, 4321
        elif name == "GetProcessTimes":
            args[1]._obj.dwHighDateTime = 2
            args[1]._obj.dwLowDateTime = 7
        elif name == "CloseHandle":
            self.open.remove(args[0])
            self.closed.append(args[0])
        elif name == "GetCurrentThreadId":
            return 9
        elif name == "ResumeThread":
            return self.resume_result
        elif name == "WaitForSingleObject":
            assert args[1] == 0
            return self.poll_result
        elif name == "QueryInformationJobObject":
            assert args[1] == 1
            args[2]._obj.ActiveProcesses = self.active
        elif name == "PeekNamedPipe":
            args[4]._obj.value = len(self.output)
        elif name == "ReadFile":
            data, self.output = self.output[: args[2]], self.output[args[2] :]
            ctypes.memmove(args[1], data, len(data))
            args[3]._obj.value = len(data)
        elif name == "GetExitCodeProcess":
            args[1]._obj.value = 23
        elif name == "ConvertStringSecurityDescriptorToSecurityDescriptorW":
            assert args[0] == "D:P(A;;GA;;;OW)" and args[1] == 1
            args[2]._obj.value = 999
        elif name == "LocalFree":
            return None
        elif name == "CreateNamedPipeW":
            assert args[1:7] == (0x80002, 9, 1, 4096, 0, 0)
            assert args[7]._obj.bInheritHandle == 0
            assert args[7]._obj.lpSecurityDescriptor == 999
            return self.handle()
        elif name == "ConnectNamedPipe":
            return 0
        elif name == "GetNamedPipeClientProcessId":
            args[1]._obj.value = 777
        elif name == "GetCurrentProcessId":
            return 777
        elif name == "WriteFile":
            args[3]._obj.value = min(args[2], 2)
        return 1


def native_case(failure=None):
    kernel = Win32(failure)
    return module().NativeWindowsProcess(kernel=kernel), kernel


def test_native_create_is_suspended_atomic_job_and_only_exact_stdio_inherited():
    native, kernel = native_case()
    child = native.create(
        (r"C:\owned\helper.exe", "a b", 'quote"value'),
        {"Z": "last", "A": "first"},
        Path(r"C:\owned"),
    )
    record = kernel.created[0]
    assert record["app"] == r"C:\owned\helper.exe"
    assert record["command"] == 'C:\\owned\\helper.exe "a b" quote\\"value'
    assert record["env"] == ["A=first", "Z=last"] and record["cwd"] == r"C:\owned"
    assert record["flags"] == 0x08080404  # NO_WINDOW | EXTENDED | UNICODE | SUSPENDED
    assert record["process_security"] is None and record["thread_security"] is None
    assert record["inherit"] is True and record["startup_flags"] == 0x100
    assert record["attributes"][0x2000D] == (child.job,)
    assert record["attributes"][0x20002] == record["stdio"]
    assert not set(child.handles()) & kernel.inherited
    assert kernel.job_limit == 0x2000  # KILL_ON_JOB_CLOSE with no breakaway flags
    assert child.creation_time == "8589934599" and child.pid == 1234
    assert kernel.open == set(child.handles()) and kernel.deleted == 1
    for handle in child.handles():
        native.close(handle)
    assert kernel.open == set()


@pytest.mark.parametrize(
    "failure",
    [
        "CreateJobObjectW",
        "SetInformationJobObject",
        "CreatePipe",
        "SetHandleInformation",
        "CreateFileW",
        "InitializeProcThreadAttributeList",
        "UpdateProcThreadAttribute",
        "CreateProcessW",
        "GetProcessTimes",
    ],
)
def test_partial_native_creation_closes_only_its_handles_and_never_launches_uncontained(failure):
    native, kernel = native_case(failure)
    with pytest.raises(module().ControlProcessError, match="control_process_launch_denied"):
        native.create((r"C:\owned\helper.exe",), {}, Path(r"C:\owned"))
    assert kernel.open == set()
    if kernel.created:
        assert kernel.created[0]["attributes"][0x2000D]
        assert kernel.created[0]["flags"] & 4
        assert kernel.closed[-5] == kernel.created[0]["attributes"][0x2000D][0]


def test_native_poll_accounting_bounded_capture_and_exit_code():
    native, kernel = native_case()
    assert native.thread_id() == 9 and native.resume(102) == 1
    assert native.poll(101) is True
    kernel.poll_result = 0x102
    assert native.poll(101) is False
    kernel.active = 2
    assert native.active_processes(103) == 2
    assert native.read(104, 4) == b"synt"
    assert native.read(104, 100) == b"hetic capture"
    assert native.read(104, 100) == b""
    assert native.exit_code(101) == 23
    kernel.poll_result = 0xFFFFFFFF
    with pytest.raises(module().ControlProcessError):
        native.poll(101)


def test_lost_create_ack_still_closes_atomic_job_and_all_returned_handles():
    class Interrupted(Win32):
        def call(self, name, *args):
            result = super().call(name, *args)
            if name == "CreateProcessW":
                raise KeyboardInterrupt
            return result

    kernel = Interrupted()
    native = module().NativeWindowsProcess(kernel=kernel)
    with pytest.raises(KeyboardInterrupt):
        native.create((r"C:\owned\helper.exe",), {}, Path(r"C:\owned"))
    assert kernel.open == set() and kernel.deleted == 1
    assert kernel.closed[-5] == kernel.created[0]["attributes"][0x2000D][0]


def test_create_cleanup_failure_is_explicitly_unknown_and_other_handles_still_close():
    class FailedClose(Win32):
        def call(self, name, *args):
            if name == "CloseHandle" and args[0] == 203:
                return 0
            return super().call(name, *args)

    kernel = FailedClose()
    native = module().NativeWindowsProcess(kernel=kernel)
    with pytest.raises(module().ControlProcessError, match="control_process_cleanup_unknown"):
        native.create((r"C:\owned\helper.exe",), {}, Path(r"C:\owned"))
    assert kernel.open == {203}  # Uncertain handle is never closed a second time.
    assert 201 in kernel.closed  # Owned Job is killed/closed despite pipe cleanup loss.


@pytest.mark.parametrize("operation", ["resume", "wait"])
def test_interrupt_poison_still_allows_only_owned_cleanup(operation):
    runtime, kernel, token = case()

    def interrupt(*args):
        raise KeyboardInterrupt

    if operation == "resume":
        kernel.resume = interrupt
    else:
        runtime.resume(token)
        kernel.poll = interrupt
    with pytest.raises(KeyboardInterrupt):
        getattr(runtime, operation)(token, *([100] if operation == "wait" else []))
    with pytest.raises(module().ControlProcessError):
        runtime.resume(token)
    with pytest.raises(module().ControlProcessError):
        runtime.wait(token, 100)
    runtime.close(token)
    assert len([c for c in kernel.calls if c[0] == "close"]) == 5


def test_native_thread_id_drift_denied_without_touching_child():
    runtime, kernel, token = case()
    kernel.thread_id = lambda: 10
    with pytest.raises(module().ControlProcessError):
        runtime.resume(token)
    with pytest.raises(module().ControlProcessError):
        runtime.close(token)
    assert len(kernel.calls) == 1
    kernel.thread_id = lambda: 9
    runtime.close(token)


@pytest.mark.parametrize(
    "api,operation,args",
    [
        ("PeekNamedPipe", "read", (104, 100)),
        ("ReadFile", "read", (104, 100)),
        ("QueryInformationJobObject", "active_processes", (103,)),
        ("GetExitCodeProcess", "exit_code", (101,)),
    ],
)
def test_native_capture_and_accounting_errors_fail_closed(api, operation, args, monkeypatch):
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    native, _ = native_case(api)
    with pytest.raises(module().ControlProcessError, match="control_process_wait_unknown"):
        getattr(native, operation)(*args)


def test_broken_output_pipe_is_eof_not_a_private_error(monkeypatch):
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 109, raising=False)
    native, _ = native_case("PeekNamedPipe")
    assert native.read(104, 100) == b""


class InputKernel(Kernel):
    def __init__(self):
        super().__init__()
        self.accepted = bytearray()
        self.write_counts = [0, 2, 1, 100]
        self.drains = 0

    def create(self, argv, env, cwd, *, stdin_pipe=False):
        assert stdin_pipe is True
        super().create(argv, env, cwd)
        return module().NativeChild(101, 102, 103, 104, 105, 1234, "987654321", 106)

    def read(self, pipe, limit):
        self.drains += 1
        return super().read(pipe, limit)

    def write(self, pipe, data):
        assert pipe == 106 and self.drains >= 2
        self.calls.append(("write", pipe))  # Never record input content.
        if self.fail == "write":
            raise OSError("synthetic private input detail")
        count = min(len(data), self.write_counts.pop(0) if self.write_counts else len(data))
        self.accepted.extend(data[:count])
        return count

    def poll(self, handle):
        return ("close", 106) in self.calls


def input_case(data=b"synthetic input", **options):
    kernel = InputKernel()
    runtime = module().WindowsControlProcess(native=kernel, **options)
    token = runtime.create_suspended((r"C:\owned\helper.exe",), {}, Path(r"C:\owned"), stdin=data)
    return runtime, kernel, token


def test_private_input_interleaves_partial_writes_drains_and_eof_after_resume():
    runtime, kernel, token = input_case()
    assert not any(c[0] == "write" for c in kernel.calls)
    assert "synthetic input" not in repr(runtime._children[token])
    runtime.resume(token)
    result = runtime.wait(token, 100)
    assert result.exit_code == 17
    assert kernel.accepted == b"synthetic input"
    assert len([c for c in kernel.calls if c[0] == "write"]) == 4
    assert runtime._children[token].input_data == bytearray()
    runtime.close(token)
    assert kernel.calls.count(("close", 106)) == 1


@pytest.mark.parametrize("data", ["text", bytearray(b"value"), memoryview(b"value"), b"x" * 9])
def test_invalid_or_oversized_input_rejected_before_create(data):
    kernel = InputKernel()
    runtime = module().WindowsControlProcess(native=kernel, max_input_bytes=8)
    with pytest.raises(module().ControlProcessError, match="control_process_launch_denied"):
        runtime.create_suspended((r"C:\owned\helper.exe",), {}, Path(r"C:\owned"), stdin=data)
    assert kernel.calls == []


def test_empty_explicit_input_delivers_eof_without_write():
    runtime, kernel, token = input_case(b"")
    runtime.resume(token)
    runtime.wait(token, 100)
    runtime.close(token)
    assert not any(c[0] == "write" for c in kernel.calls)
    assert kernel.calls.count(("close", 106)) == 1


@pytest.mark.parametrize("failure", ["write", 106])
def test_input_write_or_eof_ack_loss_poison_and_never_replay(failure):
    runtime, kernel, token = input_case(b"value")
    kernel.fail = failure
    runtime.resume(token)
    with pytest.raises(module().ControlProcessError) as error:
        runtime.wait(token, 100)
    assert str(error.value) == (
        "control_process_cleanup_unknown" if failure == 106 else "control_process_input_unknown"
    )
    assert "private" not in str(error.value)
    assert not runtime._children[token].input_data
    with pytest.raises(module().ControlProcessError):
        runtime.wait(token, 100)
    runtime.close(token)
    assert kernel.calls.count(("close", 106)) == 1


def test_close_suspended_child_clears_private_input_and_owned_writer():
    runtime, kernel, token = input_case()
    runtime.close(token)
    assert not runtime._children[token].input_data
    assert [c[1] for c in kernel.calls if c[0] == "close"] == [103, 102, 101, 104, 105, 106]


def test_native_private_pipe_is_nonblocking_parent_and_only_child_read_is_inherited(monkeypatch):
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 535, raising=False)
    native, kernel = native_case()
    child = native.create((r"C:\owned\helper.exe",), {}, Path(r"C:\owned"), stdin_pipe=True)
    record = kernel.created[0]
    assert child.stdin not in kernel.inherited
    assert record["stdio"][0] in kernel.inherited
    assert child.stdin not in record["attributes"][0x20002]
    assert kernel.open == set(child.handles())
    with memoryview(bytearray(b"synthetic")) as data:
        assert native.write(child.stdin, data) == 2
    for handle in child.handles():
        native.close(handle)
    assert not kernel.open


@pytest.mark.parametrize("error", [536, 232, 231, 5])
def test_native_pipe_connect_listening_closed_busy_access_denied_fail_without_retry(
    error, monkeypatch
):
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    native, kernel = native_case()
    with pytest.raises(module().ControlProcessError, match="control_process_launch_denied"):
        native.create((r"C:\owned\helper.exe",), {}, Path(r"C:\owned"), stdin_pipe=True)
    assert not kernel.open and not kernel.created


@pytest.mark.parametrize(
    "failure",
    [
        "CreateNamedPipeW",
        "CreateFileW",
        "GetNamedPipeClientProcessId",
        "CreateProcessW",
        "GetProcessTimes",
        "ConvertStringSecurityDescriptorToSecurityDescriptorW",
    ],
)
def test_private_pipe_partial_creation_closes_owned_handles(failure, monkeypatch):
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 535, raising=False)
    native, kernel = native_case(failure)
    with pytest.raises(module().ControlProcessError, match="control_process_launch_denied"):
        native.create((r"C:\owned\helper.exe",), {}, Path(r"C:\owned"), stdin_pipe=True)
    assert not kernel.open


@pytest.mark.parametrize("error", [232, 231, 536, 109])
def test_native_private_write_failure_is_not_backpressure(error, monkeypatch):
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    native, _ = native_case("WriteFile")
    with (
        memoryview(bytearray(b"synthetic")) as data,
        pytest.raises(module().ControlProcessError, match="control_process_input_unknown"),
    ):
        native.write(106, data)


def test_native_write_failure_releases_private_buffer_before_wipe():
    native, _ = native_case("WriteFile")
    private = bytearray(b"synthetic")
    with (
        memoryview(private) as data,
        pytest.raises(module().ControlProcessError) as retained_error,
    ):
        native.write(106, data)
    module()._wipe(private)
    assert not private and retained_error.value


@pytest.mark.parametrize("count", [-1, True, 5000])
def test_invalid_private_write_counts_poison_without_replay(count):
    runtime, kernel, token = input_case()
    kernel.write = lambda pipe, data: count
    runtime.resume(token)
    with pytest.raises(module().ControlProcessError, match="control_process_input_unknown"):
        runtime.wait(token, 100)
    assert not runtime._children[token].input_data
    runtime.close(token)


def test_stalled_input_deadline_drains_output_then_poison_and_cleanup():
    runtime, kernel, token = input_case()
    kernel.write = lambda pipe, data: 0
    runtime.resume(token)
    with pytest.raises(module().ControlProcessError, match="control_process_timeout"):
        runtime.wait(token, 1)
    assert not runtime._children[token].input_data
    assert kernel.drains >= 2
    runtime.close(token)
    assert kernel.calls.count(("close", 106)) == 1


@pytest.mark.parametrize("operation", ["resume", "write"])
def test_private_input_interrupt_wipes_and_only_owned_cleanup_remains(operation):
    runtime, kernel, token = input_case()

    def interrupt(*args):
        raise KeyboardInterrupt

    if operation == "resume":
        kernel.resume = interrupt
    else:
        runtime.resume(token)
        kernel.write = interrupt
    with pytest.raises(KeyboardInterrupt):
        if operation == "resume":
            runtime.resume(token)
        else:
            runtime.wait(token, 100)
    assert not runtime._children[token].input_data
    runtime.close(token)
    assert kernel.calls.count(("close", 106)) == 1


def test_lost_anonymous_pipe_create_ack_reclaims_returned_handles():
    class Interrupted(Win32):
        def call(self, name, *args):
            result = super().call(name, *args)
            if name == "CreatePipe":
                raise KeyboardInterrupt
            return result

    kernel = Interrupted()
    native = module().NativeWindowsProcess(kernel=kernel)
    with pytest.raises(KeyboardInterrupt):
        native.create((r"C:\owned\helper.exe",), {}, Path(r"C:\owned"), stdin_pipe=True)
    assert not kernel.open


def test_private_pipe_client_pid_mismatch_never_launches(monkeypatch):
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 535, raising=False)
    native, kernel = native_case()
    kernel.GetCurrentProcessId = lambda: 888
    with pytest.raises(module().ControlProcessError, match="control_process_launch_denied"):
        native.create((r"C:\owned\helper.exe",), {}, Path(r"C:\owned"), stdin_pipe=True)
    assert not kernel.created and not kernel.open


def test_interrupted_native_write_wipes_temporary_buffer_even_with_retained_ack_traceback():
    class Interrupted(Win32):
        def call(self, name, *args):
            if name == "WriteFile":
                self.retained = args[1]
                raise KeyboardInterrupt
            return super().call(name, *args)

    kernel = Interrupted()
    native = module().NativeWindowsProcess(kernel=kernel)
    private = bytearray(b"synthetic")
    with memoryview(private) as data, pytest.raises(KeyboardInterrupt) as retained_error:
        native.write(106, data)
    module()._wipe(private)
    assert bytes(kernel.retained) == b"\0" * 9
    assert not private and retained_error.value
