"""Real constructor/path/handle logic over low Win32 transport and owned files."""

import ctypes
import io
import os
from pathlib import Path
from typing import Any, cast

import pytest

from ai_workshop.infrastructure.local.windows_private_state import (
    Acl,
    NativePrivateStateError,
    NativeWindowsPrivateState,
)
from tests.unit.labs.rag.indexing.test_access_epoch_secured_read_assembly import win32


@pytest.fixture
def protected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[NativeWindowsPrivateState, Path, dict[str, Any]]:
    win32(monkeypatch)
    dll_transport = ctypes.WinDLL
    acl = Acl(2, 0, 8, 2, 0)
    buffers = [
        ctypes.create_string_buffer(
            bytes([0, 0, 12, 0]) + (0x1F01FF).to_bytes(4, "little") + b"xxxx"
        )
        for _ in range(2)
    ]
    state: dict[str, Any] = {"acl": True, "owner": True, "paths": []}
    sid_values = {
        42: "S-1-5-21-12345",
        100: "S-1-5-21-12345",
        ctypes.addressof(buffers[0]) + 8: "S-1-5-21-12345",
        ctypes.addressof(buffers[1]) + 8: "S-1-5-18",
    }

    def sid(pointer: Any, output: Any) -> bool:
        key = pointer.value if isinstance(pointer, ctypes.c_void_p) else pointer
        output._obj.value = sid_values[cast(int, key)] if state["owner"] else "S-1-5-21-other"
        return True

    def info(
        path: str,
        _kind: object,
        _parts: object,
        owner: Any,
        _group: object,
        dacl: Any,
        _sacl: object,
        descriptor: Any,
    ) -> int:
        state["paths"].append(Path(path))
        owner._obj.value = 100
        dacl._obj.value = ctypes.addressof(acl)
        descriptor._obj.value = 500
        return 0

    def control(_descriptor: object, output: Any, _revision: object) -> bool:
        output._obj.value = 0x1000 if state["acl"] else 0
        return True

    def ace(_acl: object, index: int, output: Any) -> bool:
        output._obj.value = ctypes.addressof(buffers[index])
        return True

    def dll(name: str, **kwargs: Any) -> Any:
        result = cast(Any, dll_transport(name, **kwargs))
        if name == "advapi32":
            result.ConvertSidToStringSidW.implementation = sid
            result.GetNamedSecurityInfoW.implementation = info
            result.GetSecurityDescriptorControl.implementation = control
            result.GetAce.implementation = ace
        return result

    monkeypatch.setattr(ctypes, "WinDLL", dll)
    native = NativeWindowsPrivateState(tmp_path)
    path = native.private / "tls" / "ordinary" / "bundle.dpapi"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"synthetic protected bytes")
    return native, path, state


def read(native: NativeWindowsPrivateState, path: Path, limit: object = 64) -> Any:
    return cast(Any, native).read_protected(str(path), limit=limit)


def test_checked_bytes_are_bound_to_one_opened_handle(protected: Any) -> None:
    native, path, state = protected
    result = read(native, path)
    assert result.data == b"synthetic protected bytes"
    current = path.stat(follow_symlinks=False)
    assert result.identity == (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
    assert "synthetic protected bytes" not in repr(result)
    assert str(path) not in repr(result)
    assert state["paths"] and all(p.is_relative_to(native.private) for p in state["paths"])


@pytest.mark.parametrize("helper", ["_require", "_sid_text"])
def test_constructor_bound_checks_cannot_be_replaced(
    protected: Any, monkeypatch: pytest.MonkeyPatch, helper: str
) -> None:
    native, path, _ = protected
    path.write_bytes(b"")
    monkeypatch.setattr(native, helper, lambda *args, **kwargs: None)
    monkeypatch.setattr(
        io, "open", lambda *args, **kwargs: pytest.fail("altered guard reached open")
    )
    with pytest.raises(NativePrivateStateError) as error:
        read(native, path)
    assert error.value.reason_code == "native_origin_changed"


def test_relative_input_cannot_skip_private_ancestor_acl(
    protected: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    native, path, _ = protected
    monkeypatch.chdir(native.root)
    with pytest.raises(NativePrivateStateError):
        native.read_protected(str(path.relative_to(native.root)), limit=64)


@pytest.mark.parametrize("change", ["require_code", "read_code", "defaults", "kwdefaults"])
def test_same_callable_mutable_content_remains_constructor_bound(
    protected: Any, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    native, path, _ = protected
    if change == "require_code":
        monkeypatch.setattr(native._require, "__code__", (lambda *args, **kwargs: None).__code__)
    elif change == "read_code":
        monkeypatch.setattr(
            native.read_protected.__func__, "__code__", (lambda *args, **kwargs: None).__code__
        )
    elif change == "defaults":
        monkeypatch.setattr(native._require, "__defaults__", ("different", None))
    else:
        monkeypatch.setattr(native.read_protected.__func__, "__kwdefaults__", {"limit": 64})
    with pytest.raises(NativePrivateStateError) as error:
        NativeWindowsPrivateState.assert_origin(native)
    assert error.value.reason_code == "native_origin_changed"


@pytest.mark.parametrize("limit", [True, 0, -1, 4 * 1024 * 1024 + 1, "64"])
def test_invalid_bounds_deny_before_file_open(
    protected: Any, monkeypatch: pytest.MonkeyPatch, limit: object
) -> None:
    native, path, _ = protected
    monkeypatch.setattr(io, "open", lambda *a, **k: pytest.fail("invalid input reached file open"))
    with pytest.raises(NativePrivateStateError):
        read(native, path, limit)


@pytest.mark.parametrize(
    "change", ["empty", "oversize", "missing", "directory", "outside", "owner", "acl", "origin"]
)
def test_missing_unsafe_or_changed_source_denies(protected: Any, change: str) -> None:
    native, path, state = protected
    if change == "empty":
        path.write_bytes(b"")
    elif change == "oversize":
        path.write_bytes(b"x" * 65)
    elif change == "missing":
        path.unlink()
    elif change == "directory":
        path = path.parent
    elif change == "outside":
        path = native.root / "outside"
    elif change in ("owner", "acl"):
        state[change] = False
    elif change == "origin":
        native.owner = "S-1-5-21-other"
    with pytest.raises(NativePrivateStateError):
        read(native, path)


def test_open_time_equal_byte_replacement_denies(
    protected: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    native, path, _ = protected
    old_open = io.open
    replacement = path.with_name("replacement")
    replacement.write_bytes(path.read_bytes())

    def opened(value: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(value) == path:
            os.replace(replacement, path)
        return old_open(value, *args, **kwargs)

    monkeypatch.setattr(io, "open", opened)
    with pytest.raises(NativePrivateStateError):
        read(native, path)


def test_foreign_handle_with_path_restored_denies(
    protected: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    native, path, _ = protected
    old_open = io.open
    replacement = path.with_name("replacement")
    replacement.write_bytes(path.read_bytes())
    monkeypatch.setattr(
        io,
        "open",
        lambda value, *a, **k: old_open(replacement if Path(value) == path else value, *a, **k),
    )
    with pytest.raises(NativePrivateStateError):
        read(native, path)


@pytest.mark.parametrize("failure", ["short", "extra", "cancel", "origin"])
def test_read_failures_close_handle(
    protected: Any, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    native, path, _ = protected
    old_open = io.open
    handles: list[Any] = []

    class Handle:
        def __init__(self, inner: Any) -> None:
            self.inner = inner

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> None:
            self.inner.close()

        def close(self) -> None:
            self.inner.close()

        def fileno(self) -> int:
            return cast(int, self.inner.fileno())

        def read(self, size: int) -> bytes:
            if failure == "cancel":
                raise KeyboardInterrupt("synthetic interrupt")
            if failure == "origin":
                native.owner = "S-1-5-21-other"
            data = cast(bytes, self.inner.read(size))
            return data[:-1] if failure == "short" else data + b"x" if failure == "extra" else data

    def opened(value: Any, *args: Any, **kwargs: Any) -> Any:
        inner = old_open(value, *args, **kwargs)
        handles.append(inner)
        return Handle(inner)

    monkeypatch.setattr(io, "open", opened)
    with pytest.raises(KeyboardInterrupt if failure == "cancel" else NativePrivateStateError):
        read(native, path)
    assert len(handles) == 1 and handles[0].closed
