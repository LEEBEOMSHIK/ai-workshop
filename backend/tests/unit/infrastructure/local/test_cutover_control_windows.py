"""Kernel calls are faked; no original daemon, command, or application is touched."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event, current_thread
from uuid import uuid4

import pytest

from ai_workshop.infrastructure.local.cutover_control_windows import (
    ControlLockError,
    WindowsControlLock,
)


class Kernel:
    def __init__(self, outcome=0):
        self.outcome = outcome
        self.calls = []
        self.fail = None

    def _call(self, kind, *args):
        self.calls.append((kind, *args))
        if kind == self.fail:
            raise OSError("private-marker")

    def create(self, name):
        self._call("create", name)
        return 101

    def wait(self, handle):
        self._call("wait", handle)
        return self.outcome

    def release(self, handle):
        self._call("release", handle)

    def close(self, handle):
        self._call("close", handle)

    def thread_id(self):
        return 7


def case(kernel=None, daemon=None):
    kernel = kernel or Kernel()
    lock = WindowsControlLock(daemon or uuid4().hex * 2, "synthetic-test", native=kernel)
    return lock, kernel, uuid4(), str(uuid4())


def test_owned_session_asserts_without_recursive_wait_and_closes_once():
    lock, kernel, execution, generation = case()
    token = lock.acquire(execution, generation)
    assert token.execution_id == execution and token.executor_generation == generation
    lock.assert_owned(token)
    lock.assert_owned(token)
    assert [call[0] for call in kernel.calls] == ["create", "wait"]
    lock.close(token)
    assert [call[0] for call in kernel.calls] == ["create", "wait", "release", "close"]
    with pytest.raises(ControlLockError):
        lock.assert_owned(token)
    with pytest.raises(ControlLockError):
        lock.acquire(execution, generation)


@pytest.mark.parametrize("outcome,code,released", [
    (0x102, "cutover_control_lock_busy", False),
    (0x80, "cutover_control_lock_abandoned", True),
    (0xFFFFFFFF, "cutover_control_lock_denied", False),
    (42, "cutover_control_lock_denied", False),
    (False, "cutover_control_lock_denied", False),
])
def test_only_clean_acquisition_succeeds_and_abandoned_is_released(outcome, code, released):
    lock, kernel, execution, generation = case(Kernel(outcome))
    with pytest.raises(ControlLockError, match=code):
        lock.acquire(execution, generation)
    kinds = [call[0] for call in kernel.calls]
    assert kinds == ["create", "wait", *(["release"] if released else []), "close"]
    with pytest.raises(ControlLockError):
        lock.acquire(execution, generation)


def test_two_instances_on_same_thread_cannot_recursively_acquire_same_name():
    daemon = uuid4().hex * 2
    first, kernel, execution, generation = case(daemon=daemon)
    second, second_kernel, _, _ = case(daemon=daemon)
    token = first.acquire(execution, generation)
    try:
        with pytest.raises(ControlLockError):
            second.acquire(uuid4(), str(uuid4()))
        assert second_kernel.calls == []
        first.assert_owned(token)
    finally:
        first.close(token)
    fresh, _, execution2, generation2 = case(daemon=daemon)
    token2 = fresh.acquire(execution2, generation2)
    fresh.close(token2)
    assert len([c for c in kernel.calls if c[0] == "wait"]) == 1


@pytest.mark.parametrize("method", ["assert_owned", "close"])
def test_foreign_thread_cannot_assert_or_release_even_if_native_tid_is_equal(method):
    lock, kernel, execution, generation = case()
    token = lock.acquire(execution, generation)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(ControlLockError):
            pool.submit(getattr(lock, method), token).result(timeout=3)
        assert [c[0] for c in kernel.calls] == ["create", "wait"]
        lock.assert_owned(token)
    finally:
        lock.close(token)


@pytest.mark.parametrize("change", ["copy", "execution", "generation", "session"])
def test_forged_or_altered_session_tokens_do_not_release_owner(change):
    lock, kernel, execution, generation = case()
    token = lock.acquire(execution, generation)
    changes = {
        "copy": {}, "execution": {"execution_id": uuid4()},
        "generation": {"executor_generation": str(uuid4())}, "session": {"session_id": uuid4()},
    }
    try:
        forged = replace(token, **changes[change])
        for operation in (lock.assert_owned, lock.close):
            with pytest.raises(ControlLockError):
                operation(forged)
        assert [c[0] for c in kernel.calls] == ["create", "wait"]
        lock.assert_owned(token)
    finally:
        lock.close(token)


@pytest.mark.parametrize("stage", ["create", "wait", "release", "close"])
def test_native_errors_are_body_free_and_session_is_never_reused(stage):
    lock, kernel, execution, generation = case()
    kernel.fail = stage
    with pytest.raises(ControlLockError) as captured:
        token = lock.acquire(execution, generation)
        lock.close(token)
    assert "private-marker" not in str(captured.value)
    with pytest.raises(ControlLockError):
        lock.acquire(execution, generation)
    if stage != "create":
        assert kernel.calls[-1][0] == "close"


@pytest.mark.parametrize("execution,generation", [("bad", str(uuid4())), (uuid4(), "bad"),
                                                 (uuid4(), str(uuid4()).upper())])
def test_invalid_execution_identity_never_creates_native_handle(execution, generation):
    lock, kernel, _, _ = case()
    with pytest.raises(ControlLockError):
        lock.acquire(execution, generation)
    assert kernel.calls == []


@pytest.mark.parametrize("daemon,project", [("bad", "synthetic"), ("A" * 64, "synthetic"),
                                           ("a" * 64, "../other"), ("a" * 64, "")])
def test_invalid_deployment_scope_cannot_choose_a_mutex_name(daemon, project):
    kernel = Kernel()
    with pytest.raises(ControlLockError):
        WindowsControlLock(daemon, project, native=kernel)
    assert kernel.calls == []


def test_name_is_fixed_namespace_and_derived_from_daemon_and_project():
    daemon = uuid4().hex * 2
    lock, kernel, execution, generation = case(daemon=daemon)
    token = lock.acquire(execution, generation)
    lock.close(token)
    other_kernel = Kernel()
    other = WindowsControlLock(daemon, "synthetic-other", native=other_kernel)
    other_token = other.acquire(uuid4(), str(uuid4()))
    other.close(other_token)
    name = kernel.calls[0][1]
    assert name.startswith("Global\\AIWorkshop.Cutover.")
    assert len(name.removeprefix("Global\\AIWorkshop.Cutover.")) == 64
    assert name != other_kernel.calls[0][1] and daemon not in name


@pytest.mark.parametrize("failure", ["release", "close", "wait"])
def test_unknown_cleanup_or_wait_blocks_new_instance_on_same_thread(failure):
    daemon = uuid4().hex * 2
    lock, kernel, execution, generation = case(daemon=daemon)
    kernel.fail = failure
    with pytest.raises(ControlLockError):
        token = lock.acquire(execution, generation)
        lock.close(token)
    next_lock, next_kernel, _, _ = case(daemon=daemon)
    with pytest.raises(ControlLockError):
        next_lock.acquire(uuid4(), str(uuid4()))
    assert next_kernel.calls == []


def test_native_thread_id_must_remain_exact_integer():
    class ChangingKernel(Kernel):
        tid = 1

        def thread_id(self):
            return self.tid

    lock, kernel, execution, generation = case(ChangingKernel())
    token = lock.acquire(execution, generation)
    try:
        kernel.tid = True
        with pytest.raises(ControlLockError):
            lock.assert_owned(token)
        kernel.tid = 2
        with pytest.raises(ControlLockError):
            lock.close(token)
        assert [call[0] for call in kernel.calls] == ["create", "wait"]
    finally:
        kernel.tid = 1
        lock.close(token)


def test_same_instance_simultaneous_first_acquire_has_only_one_owner():
    entered, resume = Event(), Event()

    class PausedStateLock(WindowsControlLock):
        pause_thread = None

        def __getattribute__(self, name):
            value = super().__getattribute__(name)
            if name == "_state" and current_thread() is self.pause_thread and value == "new":
                entered.set()
                assert resume.wait(3)
            return value

    kernel = Kernel()
    lock = PausedStateLock(uuid4().hex * 2, "synthetic-test", native=kernel)

    def attempt(pause=False):
        if pause:
            lock.pause_thread = current_thread()
        try:
            token = lock.acquire(uuid4(), str(uuid4()))
        except ControlLockError:
            return False
        lock.close(token)
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(attempt, True)
        assert entered.wait(3)
        second = pool.submit(attempt)
        # Give the competing call a bounded chance to finish; the held registry
        # guard in correct code will block it until the first state claim finishes.
        try:
            second.result(timeout=0.15)
        except TimeoutError:
            pass
        finally:
            resume.set()
        outcomes = [first.result(timeout=3), second.result(timeout=3)]
    assert sorted(outcomes) == [False, True]
    assert [c[0] for c in kernel.calls].count("create") == 1


@pytest.mark.parametrize("stage", ["wait", "release"])
def test_interrupt_cleans_handle_and_preserves_unknown_registry(stage):
    class InterruptedKernel(Kernel):
        def _call(self, kind, *args):
            self.calls.append((kind, *args))
            if kind == stage:
                raise KeyboardInterrupt

    daemon = uuid4().hex * 2
    lock, kernel, execution, generation = case(InterruptedKernel(), daemon)
    with pytest.raises(KeyboardInterrupt):
        token = lock.acquire(execution, generation)
        lock.close(token)
    assert kernel.calls[-1][0] == "close"
    fresh, fresh_kernel, _, _ = case(daemon=daemon)
    with pytest.raises(ControlLockError):
        fresh.acquire(uuid4(), str(uuid4()))
    assert fresh_kernel.calls == []
