"""Thread-affine OS serialization only; never proof of historical settlement.

Not a CutoverControlPort. Command submission and durable ownership still need a
separate fixed adapter. No callbacks, arbitrary commands, or elapsed-time lease.
"""

import ctypes
import hashlib
import json
import os
import re
from ctypes import wintypes as w
from dataclasses import dataclass
from threading import Lock, Thread, current_thread
from typing import Protocol
from uuid import UUID, uuid4

WAIT_OBJECT_0 = 0
WAIT_ABANDONED = 0x80
WAIT_TIMEOUT = 0x102


class ControlLockError(ValueError):
    """Fixed, body-free refusal; no native error or identity in its message."""


class MutexPort(Protocol):
    def create(self, name: str) -> int: ...
    def wait(self, handle: int) -> int: ...
    def release(self, handle: int) -> None: ...
    def close(self, handle: int) -> None: ...
    def thread_id(self) -> int: ...


class NativeWindowsMutex:
    def __init__(self) -> None:
        if os.name != "nt":
            raise ControlLockError("cutover_control_lock_denied")
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.CreateMutexW.argtypes = [w.LPVOID, w.BOOL, w.LPCWSTR]
        self._kernel.CreateMutexW.restype = w.HANDLE
        self._kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        self._kernel.WaitForSingleObject.restype = w.DWORD
        self._kernel.ReleaseMutex.argtypes = [w.HANDLE]
        self._kernel.ReleaseMutex.restype = w.BOOL
        self._kernel.CloseHandle.argtypes = [w.HANDLE]
        self._kernel.CloseHandle.restype = w.BOOL
        self._kernel.GetCurrentThreadId.argtypes = []
        self._kernel.GetCurrentThreadId.restype = w.DWORD

    def create(self, name: str) -> int:
        handle = self._kernel.CreateMutexW(None, False, name)
        if not handle:
            raise ControlLockError("cutover_control_lock_denied")
        return int(handle)

    def wait(self, handle: int) -> int:
        return int(self._kernel.WaitForSingleObject(handle, 0))

    def release(self, handle: int) -> None:
        if not self._kernel.ReleaseMutex(handle):
            raise ControlLockError("cutover_control_lock_unknown")

    def close(self, handle: int) -> None:
        if not self._kernel.CloseHandle(handle):
            raise ControlLockError("cutover_control_lock_unknown")

    def thread_id(self) -> int:
        return int(self._kernel.GetCurrentThreadId())


@dataclass(frozen=True, slots=True)
class HeldControlLock:
    execution_id: UUID
    executor_generation: str
    session_id: UUID


# Windows mutexes are recursive per THREAD, even across different handles.
# Poisoned entries deliberately persist until process exit; no forced takeover.
_registry: set[tuple[str, Thread]] = set()
_registry_guard = Lock()


class WindowsControlLock:
    def __init__(
        self, daemon_sha256: str, project: str, *, native: MutexPort | None = None
    ) -> None:
        if (
            type(daemon_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", daemon_sha256) is None
            or type(project) is not str
            or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project) is None
        ):
            raise ControlLockError("cutover_control_lock_denied")
        digest = hashlib.sha256(json.dumps([daemon_sha256, project]).encode("utf-8")).hexdigest()
        self._name = "Global\\AIWorkshop.Cutover." + digest
        self._native = native if native is not None else NativeWindowsMutex()
        self._state = "new"
        self._handle: int | None = None
        self._thread: Thread | None = None
        self._tid: int | None = None
        self._token: HeldControlLock | None = None

    @property
    def scope_sha256(self) -> str:
        """Derived cooperative lock scope; not a verified deployment capability."""
        return self._name.removeprefix("Global\\AIWorkshop.Cutover.")

    def _unregister(self) -> None:
        if self._thread is not None:
            with _registry_guard:
                _registry.discard((self._name, self._thread))

    def _cleanup(self, *, owned: bool) -> bool:
        """Close even after release error; never describe unknown cleanup as success."""
        clean = True
        interruption: BaseException | None = None
        if self._handle is not None:
            if owned:
                try:
                    self._native.release(self._handle)
                except BaseException as exc:
                    clean = False
                    if not isinstance(exc, Exception):
                        interruption = exc
            try:
                self._native.close(self._handle)
            except BaseException as exc:
                clean = False
                if not isinstance(exc, Exception) and interruption is None:
                    interruption = exc
            self._handle = None
        if interruption is not None:
            raise interruption
        return clean

    def acquire(self, execution_id: UUID, executor_generation: str) -> HeldControlLock:
        try:
            if (
                type(execution_id) is not UUID
                or type(executor_generation) is not str
                or str(UUID(executor_generation)) != executor_generation
            ):
                raise ValueError
        except Exception:
            raise ControlLockError("cutover_control_lock_denied") from None
        with _registry_guard:
            if self._state != "new":
                raise ControlLockError("cutover_control_lock_denied")
            self._state = "failed"
            self._thread = current_thread()
            key = (self._name, self._thread)
            if key in _registry:
                raise ControlLockError("cutover_control_lock_denied")
            _registry.add(key)
        owned = False
        known_unowned = False
        code = "cutover_control_lock_denied"
        try:
            self._tid = self._native.thread_id()
            if type(self._tid) is not int or self._tid <= 0:
                raise ValueError
            self._handle = self._native.create(self._name)
            if type(self._handle) is not int or self._handle <= 0:
                self._handle = None
                raise ValueError
            outcome = self._native.wait(self._handle)
            if type(outcome) is not int:
                raise ValueError
            owned = outcome in {WAIT_OBJECT_0, WAIT_ABANDONED}
            known_unowned = outcome == WAIT_TIMEOUT
            if outcome == WAIT_ABANDONED:
                code = "cutover_control_lock_abandoned"
                raise ValueError
            if outcome == WAIT_TIMEOUT:
                code = "cutover_control_lock_busy"
                raise ValueError
            if outcome != WAIT_OBJECT_0:
                raise ValueError
            self._token = HeldControlLock(execution_id, executor_generation, uuid4())
            self._state = "held"
            return self._token
        except BaseException as exc:
            self._state = "failed"
            try:
                clean = self._cleanup(owned=owned)
            except BaseException:
                if not isinstance(exc, Exception):
                    raise exc from None
                raise
            if clean and (owned or known_unowned):
                self._unregister()
            if not isinstance(exc, Exception):
                raise
            if not clean:
                code = "cutover_control_lock_unknown"
            raise ControlLockError(code) from None

    def assert_owned(self, token: HeldControlLock) -> None:
        try:
            if (
                self._state != "held"
                or token is not self._token
                or self._handle is None
                or current_thread() is not self._thread
            ):
                raise ValueError
            tid = self._native.thread_id()
            if type(tid) is not int or tid != self._tid:
                raise ValueError
            with _registry_guard:
                if (self._name, current_thread()) not in _registry:
                    raise ValueError
        except Exception:
            raise ControlLockError("cutover_control_lock_denied") from None

    def close(self, token: HeldControlLock) -> None:
        self.assert_owned(token)
        self._state = "failed"
        if not self._cleanup(owned=True):
            raise ControlLockError("cutover_control_lock_unknown")
        self._unregister()
        self._state = "closed"
