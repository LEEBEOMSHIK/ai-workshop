"""Actual native constructor over external Win32 ports; no original private I/O."""

import ctypes
import gc
from copy import copy
from pathlib import Path
from typing import Any, cast
from weakref import ref

import pytest

from ai_workshop.infrastructure.local.windows_private_state import (
    NativePrivateStateError,
    NativeWindowsPrivateState,
)
from tests.unit.labs.rag.indexing.test_access_epoch_secured_read_assembly import win32


@pytest.mark.parametrize(
    "change",
    [
        "native_copy",
        "dll_copy",
        "function_copy",
        "argtypes",
        "restype",
        "handle",
        "owner",
        "root",
        "private",
        "bool_handle",
    ],
)
def test_origin_denies_changes_before_first_assertion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, change: str
) -> None:
    win32(monkeypatch)
    native = NativeWindowsPrivateState(tmp_path)
    if change == "native_copy":
        native = copy(native)
    elif change == "dll_copy":
        native.crypt = copy(native.crypt)
    elif change == "function_copy":
        cast(Any, native.crypt).CryptProtectData = copy(native.crypt.CryptProtectData)
    elif change == "argtypes":
        cast(Any, native.kernel.LocalFree.argtypes).clear()
    elif change == "restype":
        native.kernel.LocalFree.restype = None
    elif change == "handle":
        native.crypt._handle = 999
    elif change == "owner":
        native.owner = "S-1-5-21-other"
    elif change == "root":
        native.root = tmp_path / "other"
    elif change == "private":
        native.private = tmp_path / "other"
    elif change == "bool_handle":
        native.kernel._handle = True
    with pytest.raises(NativePrivateStateError) as error:
        NativeWindowsPrivateState.assert_origin(native)
    assert error.value.reason_code == "native_origin_changed"


def test_origin_is_memory_only_and_does_not_retain_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    win32(monkeypatch)
    native = NativeWindowsPrivateState(tmp_path)
    retained = (native.kernel, native.advapi, native.crypt)
    weak_owner = ref(native)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("origin assertion must perform no I/O")

    monkeypatch.setattr(ctypes, "WinDLL", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)
    NativeWindowsPrivateState.assert_origin(native)
    del native
    gc.collect()
    assert weak_owner() is None and len(retained) == 3


def test_failed_and_repeated_initialization_never_reissues_origin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    native = object.__new__(NativeWindowsPrivateState)

    def failing(*args: Any, **kwargs: Any) -> Any:
        raise OSError("synthetic transport failure")

    monkeypatch.setattr(ctypes, "WinDLL", failing)
    with pytest.raises(OSError, match="synthetic transport failure"):
        NativeWindowsPrivateState.__init__(native, tmp_path)
    with pytest.raises(NativePrivateStateError):
        NativeWindowsPrivateState.assert_origin(native)
    win32(monkeypatch)
    with pytest.raises(NativePrivateStateError):
        NativeWindowsPrivateState.__init__(native, tmp_path)
    healthy = NativeWindowsPrivateState(tmp_path)
    with pytest.raises(NativePrivateStateError):
        NativeWindowsPrivateState.__init__(healthy, tmp_path / "replacement")
    assert healthy.root == tmp_path
    NativeWindowsPrivateState.assert_origin(healthy)
