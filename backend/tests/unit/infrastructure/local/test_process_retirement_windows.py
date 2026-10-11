"""Same-handle process retirement; fake kernel only, no real targets are opened."""

import ctypes
import importlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest


def module():
    return importlib.import_module("ai_workshop.infrastructure.local.process_retirement_windows")


def target():
    return module().ProcessLifetime(12340, "133700000000000001", Path("C:/synthetic/python.exe"))


class Kernel:
    def __init__(self):
        self.calls = []
        self.observed = None
        self.handle = 500
        self.fail = None
        self.tid = 9
        self.wait_result = 0
        self.code = 1
        self.terminal_before = False

    def call(self, name, *args):
        self.calls.append((name, *args))
        if self.fail == name:
            raise OSError("private-native-detail")

    def thread_id(self):
        return self.tid

    def open_process(self, pid):
        self.call("open", pid)
        return self.handle

    def identity(self, handle):
        self.call("identity", handle)
        return self.observed or target()

    def terminate(self, handle, exit_code):
        self.call("terminate", handle, exit_code)

    def wait(self, handle, timeout_ms):
        self.call("wait", handle, timeout_ms)
        return (0 if self.terminal_before else 258) if timeout_ms == 0 else self.wait_result

    def exit_code(self, handle):
        self.call("exit", handle)
        return self.code

    def close(self, handle):
        self.call("close", handle)


def case():
    kernel = Kernel()
    return module().WindowsProcessRetirement(kernel), kernel


def test_same_handle_checked_before_one_termination_and_exact_terminal_readback():
    adapter, kernel = case()
    expected = target()
    token = adapter.open(expected)
    assert not hasattr(token, "handle")
    result = adapter.retire(token, 2500)
    assert result.lifetime == expected and result.exit_code == 1
    assert adapter.assert_result(result) is None
    with pytest.raises(ValueError):
        adapter.assert_result(replace(result))
    assert kernel.calls == [
        ("open", expected.pid),
        ("identity", 500),
        ("identity", 500),
        ("wait", 500, 0),
        ("terminate", 500, 1),
        ("wait", 500, 2500),
        ("exit", 500),
    ]
    assert "synthetic" not in repr(token) and "synthetic" not in repr(result)
    with pytest.raises(ValueError):
        adapter.retire(token, 2500)
    adapter.close(token)
    with pytest.raises(ValueError):
        adapter.close(token)
    assert kernel.calls[-1] == ("close", 500)
    assert len([x for x in kernel.calls if x[0] == "terminate"]) == 1


@pytest.mark.parametrize("change", ["pid", "created", "executable"])
def test_open_mismatch_closes_only_owned_handle_and_never_terminates(change):
    adapter, kernel = case()
    fields = (
        {"pid": 12344}
        if change == "pid"
        else {"creation_time": "133700000000000002"}
        if change == "created"
        else {"executable": Path("C:/other/python.exe")}
    )
    kernel.observed = replace(target(), **fields)
    with pytest.raises(ValueError, match="process_retirement_denied"):
        adapter.open(target())
    assert kernel.calls == [("open", 12340), ("identity", 500), ("close", 500)]


def test_identity_is_rechecked_on_held_handle_immediately_before_mutation():
    adapter, kernel = case()
    token = adapter.open(target())
    kernel.observed = replace(target(), creation_time="133700000000000009")
    with pytest.raises(ValueError):
        adapter.retire(token, 10)
    kernel.observed = target()
    with pytest.raises(ValueError):
        adapter.retire(token, 10)
    adapter.close(token)
    assert not any(x[0] == "terminate" for x in kernel.calls)


@pytest.mark.parametrize("stage", ["terminate", "wait", "exit"])
def test_native_failure_poisoned_attempt_never_retries_or_claims_completion(stage):
    adapter, kernel = case()
    token = adapter.open(target())
    if stage == "wait":
        kernel.wait_result = 0xFFFFFFFF
    else:
        kernel.fail = stage
    with pytest.raises(ValueError, match="process_retirement_unknown") as error:
        adapter.retire(token, 10)
    assert "private-native-detail" not in repr(error.value)
    kernel.fail, kernel.wait_result = None, 0
    with pytest.raises(ValueError):
        adapter.retire(token, 10)
    adapter.close(token)
    assert len([x for x in kernel.calls if x[0] == "terminate"]) == 1


@pytest.mark.parametrize(
    "wait,exit_code", [(258, 1), (0x80, 1), (0, 259), (0, 0), (0, True), (False, 1), (0, 1.0)]
)
def test_timeout_or_nonexact_terminal_status_is_unknown(wait, exit_code):
    adapter, kernel = case()
    token = adapter.open(target())
    kernel.wait_result, kernel.code = wait, exit_code
    with pytest.raises(ValueError, match="process_retirement_unknown"):
        adapter.retire(token, 1)
    adapter.close(token)


def test_already_exited_is_not_a_successful_owned_termination():
    adapter, kernel = case()
    token = adapter.open(target())
    kernel.terminal_before = True
    with pytest.raises(ValueError):
        adapter.retire(token, 10)
    adapter.close(token)
    assert not any(x[0] == "terminate" for x in kernel.calls)


@pytest.mark.parametrize(
    "pid,time,exe",
    [
        (0, "1", "C:/safe/python.exe"),
        (True, "1", "C:/safe/python.exe"),
        (0x100000000, "1", "C:/safe/python.exe"),
        (12340, "01", "C:/safe/python.exe"),
        (12340, "0", "C:/safe/python.exe"),
        (12340, str(2**64), "C:/safe/python.exe"),
        (12340, 1, "C:/safe/python.exe"),
        (12340, "1", "relative.exe"),
        (12340, "1", "C:/safe/../other/python.exe"),
        (12340, "1", "//server/share/python.exe"),
        (12340, "1", "C:/safe/python.exe:stream"),
        (12340, "1", "C:/safe/python.exe "),
        (12340, "1", "C:/safe/script.ps1"),
    ],
)
def test_invalid_namespace_or_lifetime_never_opens(pid, time, exe):
    adapter, kernel = case()
    with pytest.raises(ValueError):
        adapter.open(module().ProcessLifetime(pid, time, Path(exe)))
    assert kernel.calls == []


def test_self_pid_is_never_opened_for_retirement():
    adapter, kernel = case()
    with pytest.raises(ValueError):
        adapter.open(replace(target(), pid=os.getpid()))
    assert kernel.calls == []


@pytest.mark.parametrize("change", ["copy", "foreign", "native_thread", "python_thread"])
def test_tokens_are_exact_object_adapter_and_thread_owned(change):
    adapter, kernel = case()
    token = adapter.open(target())
    before = list(kernel.calls)
    if change == "copy":
        with pytest.raises(ValueError):
            adapter.retire(replace(token), 10)
    elif change == "foreign":
        other, _ = case()
        with pytest.raises(ValueError):
            other.retire(token, 10)
    elif change == "native_thread":
        kernel.tid = 10
        with pytest.raises(ValueError):
            adapter.retire(token, 10)
        kernel.tid = 9
    else:
        with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(ValueError):
            pool.submit(adapter.retire, token, 10).result()
    assert kernel.calls == before
    adapter.close(token)


@pytest.mark.parametrize("timeout", [0, -1, True, 1.0, 60001, 0xFFFFFFFF])
def test_wait_is_finite_and_strict_integer(timeout):
    adapter, kernel = case()
    token = adapter.open(target())
    with pytest.raises(ValueError):
        adapter.retire(token, timeout)
    assert not any(x[0] == "terminate" for x in kernel.calls)
    adapter.close(token)


def test_close_lost_ack_is_consumed_and_never_recloses_reused_handle():
    adapter, kernel = case()
    token = adapter.open(target())
    kernel.fail = "close"
    with pytest.raises(ValueError, match="process_retirement_cleanup_unknown"):
        adapter.close(token)
    kernel.fail = None
    with pytest.raises(ValueError):
        adapter.close(token)
    assert len([x for x in kernel.calls if x[0] == "close"]) == 1
    assert not any(x[0] == "terminate" for x in kernel.calls)


def test_partial_identity_failure_cleans_only_owned_handle_and_reports_cleanup_unknown():
    adapter, kernel = case()
    kernel.observed = replace(target(), pid=9999)
    kernel.fail = "close"
    with pytest.raises(ValueError, match="process_retirement_cleanup_unknown"):
        adapter.open(target())
    assert kernel.calls[-1] == ("close", 500)


def test_native_backend_uses_exact_rights_noninheritance_and_64bit_filetime(monkeypatch):
    m = module()
    calls = []

    class Function:
        def __init__(self, fn):
            self.fn = fn

        def __call__(self, *args):
            return self.fn(*args)

    def times(handle, created, exited, kernel, user):
        calls.append(("times", handle))
        out = ctypes.cast(created, ctypes.POINTER(m.w.FILETIME)).contents
        value = int(target().creation_time)
        out.dwLowDateTime = value & 0xFFFFFFFF
        out.dwHighDateTime = value >> 32
        return 1

    def image(handle, flags, buffer, size):
        calls.append(("image", handle, flags))
        buffer.value = str(target().executable)
        ctypes.cast(size, ctypes.POINTER(m.w.DWORD)).contents.value = len(buffer.value)
        return 1

    def exit_code(handle, output):
        calls.append(("exit", handle))
        ctypes.cast(output, ctypes.POINTER(m.w.DWORD)).contents.value = 1
        return 1

    class DLL:
        OpenProcess = Function(
            lambda rights, inherit, pid: calls.append(("open", rights, inherit, pid)) or 500
        )
        GetProcessTimes = Function(times)
        QueryFullProcessImageNameW = Function(image)
        GetProcessId = Function(lambda handle: 12340)
        GetCurrentThreadId = Function(lambda: 9)
        TerminateProcess = Function(
            lambda handle, code: calls.append(("terminate", handle, code)) or 1
        )
        WaitForSingleObject = Function(
            lambda handle, timeout: calls.append(("wait", handle, timeout)) or 0
        )
        GetExitCodeProcess = Function(exit_code)
        CloseHandle = Function(lambda handle: calls.append(("close", handle)) or 1)

    monkeypatch.setattr(m.ctypes, "WinDLL", lambda *a, **kw: DLL())
    native = m.NativeWindowsProcessRetirement()
    handle = native.open_process(12340)
    assert native.identity(handle) == target()
    native.terminate(handle, 1)
    assert native.wait(handle, 100) == 0 and native.exit_code(handle) == 1
    native.close(handle)
    assert calls[0] == ("open", 0x00101001, False, 12340)
    assert ("image", 500, 0) in calls
    assert calls[-1] == ("close", 500)


def test_result_origin_requires_integer_native_thread_identity():
    adapter, kernel = case()
    kernel.tid = 1
    token = adapter.open(target())
    result = adapter.retire(token, 1)
    kernel.tid = True
    with pytest.raises(ValueError):
        adapter.assert_result(result)
    kernel.tid = 1
    adapter.close(token)


def test_new_token_cannot_reopen_same_lifetime_after_unknown_termination():
    adapter, kernel = case()
    token = adapter.open(target())
    kernel.wait_result = 258
    with pytest.raises(ValueError):
        adapter.retire(token, 1)
    adapter.close(token)
    with pytest.raises(ValueError):
        adapter.open(target())
    assert len([call for call in kernel.calls if call[0] == "open"]) == 1


@pytest.mark.parametrize(
    "result", [0, None, -1, True, 2 ** (ctypes.sizeof(ctypes.c_void_p) * 8) - 1]
)
def test_open_failure_or_invalid_handle_never_closes_a_foreign_handle(result):
    adapter, kernel = case()
    kernel.handle = result
    with pytest.raises(ValueError, match="process_retirement_denied"):
        adapter.open(target())
    assert kernel.calls == [("open", target().pid)]


def test_exact_path_does_not_fold_distinct_case_sensitive_windows_names():
    adapter, kernel = case()
    kernel.observed = replace(target(), executable=Path("C:/synthetic/PYTHON.exe"))
    with pytest.raises(ValueError):
        adapter.open(target())
    assert not any(call[0] == "terminate" for call in kernel.calls)


def test_cancellation_consumes_termination_attempt_but_close_remains_owned_cleanup():
    adapter, kernel = case()
    token = adapter.open(target())
    wait = kernel.wait

    def interrupted(handle, timeout_ms):
        if timeout_ms:
            raise KeyboardInterrupt()
        return wait(handle, timeout_ms)

    kernel.wait = interrupted
    with pytest.raises(KeyboardInterrupt):
        adapter.retire(token, 10)
    kernel.wait = wait
    with pytest.raises(ValueError):
        adapter.retire(token, 10)
    adapter.close(token)
    assert len([call for call in kernel.calls if call[0] == "terminate"]) == 1
    assert kernel.calls[-1] == ("close", 500)
