"""Actual child/capture classes; only external kernel, ACL and DPAPI are fake."""

import asyncio
import importlib
import threading
from uuid import UUID

import pytest

from ai_workshop.infrastructure.local.control_process_windows import (
    NativeChild,
    WindowsControlProcess,
)
from tests.unit.infrastructure.local.test_native_private_state import capture_adapter


def module():
    name = "ai_workshop.labs.rag.indexing.access_epoch_secured_read_process"
    assert importlib.util.find_spec(name) is not None, "secured read cleanup barrier is missing"
    return importlib.import_module(name)


class Kernel:
    def __init__(self):
        self.calls = []
        self.threads = set()
        self.polling = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.fail = None
        self.stdout = bytearray(b"private wire body")

    def note(self, name):
        self.threads.add(threading.get_ident())
        self.calls.append(name)

    def thread_id(self):
        return threading.get_ident()

    def create(self, argv, env, cwd):
        self.note("create")
        self.argv, self.env, self.cwd = argv, env, cwd
        return NativeChild(101, 102, 103, 104, 105, 1234, "987654321")

    def resume(self, handle):
        self.note("resume")
        if self.fail == "resume":
            raise OSError("private native failure")
        return 1

    def poll(self, handle):
        self.note("poll")
        self.polling.set()
        if self.fail == "poll":
            raise OSError("private native failure")
        return self.release.is_set()

    def active_processes(self, job):
        return 0 if self.release.is_set() else 1

    def read(self, handle, limit):
        if handle == 105:
            return b""
        data = bytes(self.stdout[:limit])
        del self.stdout[:limit]
        return data

    def exit_code(self, process):
        return 0

    def close(self, handle):
        self.note(f"close{handle}")
        if self.fail == "close" and handle == 103:
            raise OSError("private close failure")


def case(tmp_path, monkeypatch):
    m = module()
    files, external = capture_adapter(tmp_path)
    monkeypatch.setattr(m, "PROJECT_ROOT", files.root)
    kernel = Kernel()
    native = WindowsControlProcess(kernel, max_output_bytes=2 * 1024 * 1024, max_wait_ms=10000)
    catalog = m.SecuredDockerReadCatalog("a" * 64, "sha256:" + "b" * 64)
    kwargs = dict(
        catalog=catalog,
        native=native,
        files=files,
        nonce=UUID(int=123),
        slot=0,
        binding_json='{"epoch_id":"synthetic"}',
        environment={"SystemRoot": r"C:\Windows"},
    )
    return m, kernel, native, files, external, kwargs


@pytest.mark.parametrize("slot", range(5))
async def test_fixed_slots_complete_close_and_private_capture(tmp_path, monkeypatch, slot):
    m, kernel, native, files, external, kwargs = case(tmp_path, monkeypatch)
    kwargs["slot"] = slot
    result = await m._capture_docker_read(**kwargs)
    assert result.stdout == b"private wire body" and result.exit_code == 0
    assert len(kernel.threads) == 1 and threading.get_ident() not in kernel.threads
    assert kernel.calls[-5:] == ["close103", "close102", "close101", "close104", "close105"]
    assert "private" not in repr(result)
    for phase in ("intent", "child", "resume_intent", "terminal", "cleanup", "capture"):
        assert files.read_read_capture(kwargs["nonce"], slot, phase) is not None
    assert kernel.argv[0] == m.DOCKER_EXE and kernel.argv[1:3] == (
        "--host",
        "npipe:////./pipe/dockerDesktopLinuxEngine",
    )
    expected = (
        ("info", "--format", "{{json .}}"),
        ("container", "inspect", "a" * 64),
        ("network", "inspect", m.NETWORK),
        ("image", "inspect", "sha256:" + "b" * 64),
        ("volume", "inspect", "ai-workshop_elasticsearch-data"),
    )
    assert kernel.argv[3:] == expected[slot]
    count = kernel.calls.count("create")
    with pytest.raises(ValueError, match="^secured_read_process_denied$"):
        await m._capture_docker_read(**kwargs)
    assert kernel.calls.count("create") == count


@pytest.mark.parametrize(
    "change",
    [
        "bool_slot",
        "large_slot",
        "zero_nonce",
        "string_nonce",
        "proxy_env",
        "docker_env",
        "secret_env",
        "bad_binding",
        "relative_catalog",
        "loose_runtime",
    ],
)
async def test_invalid_inputs_create_no_child(tmp_path, monkeypatch, change):
    m, kernel, native, files, external, kwargs = case(tmp_path, monkeypatch)
    if change == "bool_slot":
        kwargs["slot"] = True
    elif change == "large_slot":
        kwargs["slot"] = 5
    elif change == "zero_nonce":
        kwargs["nonce"] = UUID(int=0)
    elif change == "string_nonce":
        kwargs["nonce"] = str(kwargs["nonce"])
    elif change == "proxy_env":
        kwargs["environment"]["HTTPS_PROXY"] = "private"
    elif change == "docker_env":
        kwargs["environment"]["DOCKER_HOST"] = "private"
    elif change == "secret_env":
        kwargs["environment"]["API_KEY"] = "private"
    elif change == "bad_binding":
        kwargs["binding_json"] = '{ "epoch_id": "synthetic" }'
    elif change == "relative_catalog":
        object.__setattr__(kwargs["catalog"], "container_id", "alias-name")
    elif change == "loose_runtime":
        kwargs["native"] = WindowsControlProcess(kernel)
    with pytest.raises(ValueError, match="^secured_read_process_denied$"):
        await m._capture_docker_read(**kwargs)
    assert "create" not in kernel.calls


@pytest.mark.parametrize("failure", ["resume", "poll", "close"])
async def test_native_failure_still_closes_all_owned_handles_without_private_error(
    tmp_path, monkeypatch, failure
):
    m, kernel, native, files, external, kwargs = case(tmp_path, monkeypatch)
    kernel.fail = failure
    with pytest.raises(ValueError, match="^secured_read_process_denied$") as caught:
        await m._capture_docker_read(**kwargs)
    assert "private" not in str(caught.value)
    assert kernel.calls[-5:] == ["close103", "close102", "close101", "close104", "close105"]
    assert files.read_read_capture(kwargs["nonce"], 0, "capture") is None


@pytest.mark.parametrize("cleanup_failure", [False, True])
async def test_repeated_cancellation_waits_for_actual_same_thread_close(
    tmp_path, monkeypatch, cleanup_failure
):
    m, kernel, native, files, external, kwargs = case(tmp_path, monkeypatch)
    kernel.release.clear()
    task = asyncio.create_task(m._capture_docker_read(**kwargs))
    await asyncio.wait_for(asyncio.to_thread(kernel.polling.wait), 2)
    task.cancel("first")
    await asyncio.sleep(0)
    task.cancel("second")
    await asyncio.sleep(0)
    assert not task.done() and "close103" not in kernel.calls
    if cleanup_failure:
        kernel.fail = "close"
    kernel.release.set()
    with pytest.raises(asyncio.CancelledError) as caught:
        await asyncio.wait_for(task, 2)
    assert caught.value.args == ("first",)
    assert kernel.calls[-5:] == ["close103", "close102", "close101", "close104", "close105"]
    assert len(kernel.threads) == 1 and threading.get_ident() not in kernel.threads
    assert files.read_read_capture(kwargs["nonce"], 0, "capture") is None


@pytest.mark.parametrize("phase", ["intent", "child", "resume_intent", "terminal"])
async def test_cancel_during_phase_waits_for_cleanup_and_never_returns_output(
    tmp_path, monkeypatch, phase
):
    m, kernel, native, files, external, kwargs = case(tmp_path, monkeypatch)
    reached = threading.Event()
    release = threading.Event()
    original = files.kernel.MoveFileExW

    def block(source, target, flags):
        ok = original(source, target, flags)
        if target.endswith(f"0-{phase}.dpapi"):
            reached.set()
            assert release.wait(2)
        return ok

    files.kernel.MoveFileExW = block
    task = asyncio.create_task(m._capture_docker_read(**kwargs))
    await asyncio.wait_for(asyncio.to_thread(reached.wait), 2)
    task.cancel("phase cancellation")
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert files.read_read_capture(kwargs["nonce"], 0, "capture") is None
    if phase == "intent":
        assert "create" not in kernel.calls
    else:
        assert kernel.calls[-5:] == ["close103", "close102", "close101", "close104", "close105"]
    if phase in {"intent", "child", "resume_intent"}:
        assert "resume" not in kernel.calls


@pytest.mark.parametrize(
    "phase", ["intent", "child", "resume_intent", "terminal", "cleanup", "capture"]
)
async def test_phase_ack_loss_is_denied_and_cannot_replay_child(tmp_path, monkeypatch, phase):
    m, kernel, native, files, external, kwargs = case(tmp_path, monkeypatch)
    original = files.kernel.MoveFileExW

    def lost_ack(source, target, flags):
        ok = original(source, target, flags)
        if target.endswith(f"0-{phase}.dpapi"):
            return False
        return ok

    files.kernel.MoveFileExW = lost_ack
    with pytest.raises(ValueError, match="^secured_read_process_denied$"):
        await m._capture_docker_read(**kwargs)
    count = kernel.calls.count("create")
    with pytest.raises(ValueError, match="^secured_read_process_denied$"):
        await m._capture_docker_read(**kwargs)
    assert kernel.calls.count("create") == count
    if count:
        assert kernel.calls[-5:] == ["close103", "close102", "close101", "close104", "close105"]


async def test_output_overflow_never_publishes_capture(tmp_path, monkeypatch):
    m, kernel, native, files, external, kwargs = case(tmp_path, monkeypatch)
    kernel.stdout = bytearray(b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="^secured_read_process_denied$"):
        await m._capture_docker_read(**kwargs)
    assert kernel.calls[-5:] == ["close103", "close102", "close101", "close104", "close105"]
    assert files.read_read_capture(kwargs["nonce"], 0, "capture") is None


async def test_second_caller_cannot_use_same_live_runtime(tmp_path, monkeypatch):
    m, kernel, native, files, external, kwargs = case(tmp_path, monkeypatch)
    kernel.release.clear()
    first = asyncio.create_task(m._capture_docker_read(**kwargs))
    await asyncio.wait_for(asyncio.to_thread(kernel.polling.wait), 2)
    second = dict(kwargs, nonce=UUID(int=124), slot=1)
    with pytest.raises(ValueError, match="^secured_read_process_denied$"):
        await m._capture_docker_read(**second)
    kernel.release.set()
    await asyncio.wait_for(first, 2)
    assert kernel.calls.count("create") == 1
