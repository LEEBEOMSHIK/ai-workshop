"""Live, handle-pinned capabilities for flat document temporary workspaces.

The journal owns writer/cleaning transitions. This adapter never reconstructs
deletion authority from a path, a journal row, or a restarted process.
"""

from __future__ import annotations

import json
import os
import re
import stat
from contextlib import ExitStack
from pathlib import Path
from uuid import UUID

from ai_workshop.infrastructure.object_store.originals import TrackedOriginalStore
from ai_workshop.platform.assets.temporary_contracts import (
    TemporaryBinding,
    TemporaryClaim,
    TemporaryOwnershipError,
)

_MARKER = ".ai-workshop-temporary-store.json"
_Identity = tuple[int, int]
_NAME = re.compile(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}\Z")
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}


def _identity(status: os.stat_result) -> _Identity:
    return status.st_dev, status.st_ino


def _plain(status: os.stat_result, *, directory: bool = False) -> None:
    valid = (
        stat.S_ISDIR(status.st_mode)
        if directory
        else stat.S_ISREG(status.st_mode) and status.st_nlink == 1
    )
    if (
        not valid
        or stat.S_ISLNK(status.st_mode)
        or getattr(status, "st_file_attributes", 0) & 0x400
    ):
        raise TemporaryOwnershipError("unsafe_path")


def _native_new(parent_fd: int, name: str, *, directory: bool) -> int:
    """FILE_CREATE returns the identity pin atomically, including directories.

    A relative OBJECT_ATTRIBUTES name anchors allocation to the pinned parent.
    No FILE_SHARE_DELETE: ordinary child readers/writers can use the file but
    cannot rename or replace it. No DELETE access: ordinary Python child opens
    need not opt into delete sharing.
    """
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(UnicodeString)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        ]

    class IoStatus(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

    buffer = ctypes.create_unicode_buffer(name)
    text = UnicodeString(
        len(name.encode("utf-16-le")), ctypes.sizeof(buffer), ctypes.cast(buffer, wintypes.LPWSTR)
    )
    attributes = ObjectAttributes(
        ctypes.sizeof(ObjectAttributes),
        msvcrt.get_osfhandle(parent_fd),
        ctypes.pointer(text),
        0x40,
        None,
        None,
    )
    handle = wintypes.HANDLE()
    status = IoStatus()
    native = ctypes.WinDLL("ntdll").NtCreateFile
    native.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.ULONG,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatus),
        wintypes.LPVOID,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.LPVOID,
        wintypes.ULONG,
    ]
    native.restype = wintypes.LONG
    result = native(
        ctypes.byref(handle),
        0x80100000,
        ctypes.byref(attributes),
        ctypes.byref(status),
        None,
        0x80,
        0x3,
        2,
        0x200020 | (1 if directory else 0x40),
        None,
        0,
    )
    if result < 0:
        raise TemporaryOwnershipError("file_conflict")
    try:
        assert handle.value is not None
        return msvcrt.open_osfhandle(handle.value, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
        raise


class TrackedTemporaryStore:
    def __init__(self, root: Path, binding: TemporaryBinding) -> None:
        if not isinstance(root, Path) or type(binding) is not TemporaryBinding:
            raise TemporaryOwnershipError("store_unavailable")
        self.root = root.absolute()
        self.binding = binding
        self._root_identity: _Identity | None = None
        self._attempted: set[UUID] = set()

    def _validate(self, claim: TemporaryClaim) -> None:
        if type(claim) is not TemporaryClaim:
            raise TemporaryOwnershipError("invalid_claim")
        try:
            claim.__post_init__()
            claim.context.__post_init__()
            claim.context.source.__post_init__()
            claim.binding.__post_init__()
        except (ValueError, TypeError, AttributeError):
            raise TemporaryOwnershipError("invalid_claim") from None
        if claim.binding != self.binding:
            raise TemporaryOwnershipError("binding_mismatch")

    def _pin(self, pins: ExitStack) -> int:
        if os.name != "nt":
            raise TemporaryOwnershipError("store_unavailable")
        root_fd = -1
        for path in reversed((self.root, *self.root.parents)):
            before = path.lstat()
            _plain(before, directory=True)
            fd = TrackedOriginalStore._windows_fd(path, directory=True)
            pins.callback(os.close, fd)
            opened = os.fstat(fd)
            _plain(opened, directory=True)
            if _identity(before) != _identity(opened):
                raise TemporaryOwnershipError("ownership_unconfirmed")
            root_fd = fd
        identity = _identity(os.fstat(root_fd))
        if self._root_identity is not None and identity != self._root_identity:
            raise TemporaryOwnershipError("binding_mismatch")
        if os.path.normcase(str(self.root.resolve(strict=True))) != os.path.normcase(
            str(self.root)
        ):
            raise TemporaryOwnershipError("unsafe_path")
        marker = self.root / _MARKER
        if _MARKER not in {entry.name for entry in self.root.iterdir()}:
            raise TemporaryOwnershipError("invalid_marker")
        _plain(marker.lstat())
        marker_fd = TrackedOriginalStore._windows_fd(marker)
        pins.callback(os.close, marker_fd)
        _plain(os.fstat(marker_fd))
        try:
            raw = os.read(marker_fd, 4097)
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TemporaryOwnershipError("invalid_marker") from None
        if (
            len(raw) > 4096
            or type(value) is not dict
            or type(value.get("schema_version")) is not int
            or value
            != {
                "schema_version": 1,
                "store_id": self.binding.store_id,
                "binding_id": str(self.binding.binding_id),
            }
        ):
            raise TemporaryOwnershipError("binding_mismatch")
        self._root_identity = identity
        return root_fd

    def create(self, claim: TemporaryClaim) -> TemporaryWorkspace:
        self._validate(claim)
        if os.name != "nt":
            raise TemporaryOwnershipError("store_unavailable")
        if claim.id in self._attempted:
            raise TemporaryOwnershipError("ownership_unconfirmed")
        self._attempted.add(claim.id)
        pins = ExitStack()
        try:
            parent_fd = self._pin(pins)
            fd = _native_new(parent_fd, str(claim.id), directory=True)
            return TemporaryWorkspace(self.root / str(claim.id), fd, pins)
        except OSError:
            pins.close()
            raise TemporaryOwnershipError("store_unavailable") from None
        except BaseException:
            pins.close()
            raise

    def observe(self, claim: TemporaryClaim) -> bool:
        self._validate(claim)
        try:
            with ExitStack() as pins:
                self._pin(pins)
                names = {entry.name for entry in self.root.iterdir()}
                name = str(claim.id)
                if any(value.casefold() == name and value != name for value in names):
                    raise TemporaryOwnershipError("unsafe_path")
                if name not in names:
                    return False
                _plain((self.root / name).lstat(), directory=True)
                return True
        except OSError:
            raise TemporaryOwnershipError("store_unavailable") from None


class TemporaryWorkspace:
    """Only instances returned by exclusive creation have cleanup capability."""

    def __init__(self, root: Path, fd: int, pins: ExitStack) -> None:
        self.root = root
        self._fd: int | None = fd
        self._identity = _identity(os.fstat(fd))
        self._pins = pins
        self._files: dict[str, tuple[int | None, _Identity]] = {}
        self._closed = False

    def _live(self) -> int:
        if self._closed or self._fd is None:
            raise TemporaryOwnershipError("ownership_unconfirmed")
        return self._fd

    def create_file(self, name: str) -> Path:
        fd = self._live()
        if (
            type(name) is not str
            or not _NAME.fullmatch(name)
            or name.endswith(".")
            or name.split(".")[0].upper() in _RESERVED
        ):
            raise TemporaryOwnershipError("unsafe_path")
        if any(value.casefold() == name.casefold() for value in self._files):
            raise TemporaryOwnershipError("file_conflict")
        try:
            self._check_root()
            child = _native_new(fd, name, directory=False)
            self._files[name] = (child, _identity(os.fstat(child)))
            return self.root / name
        except OSError:
            raise TemporaryOwnershipError("store_unavailable") from None

    def _check_root(self) -> None:
        status = os.fstat(self._live())
        _plain(status, directory=True)
        path_status = self.root.lstat()
        _plain(path_status, directory=True)
        if _identity(status) != self._identity or _identity(path_status) != self._identity:
            raise TemporaryOwnershipError("ownership_unconfirmed")

    def _preflight(self) -> None:
        self._check_root()
        if {entry.name for entry in self.root.iterdir()} != set(self._files):
            raise TemporaryOwnershipError("ownership_unconfirmed")
        for name, (fd, identity) in self._files.items():
            if fd is None:
                raise TemporaryOwnershipError("ownership_unconfirmed")
            opened = os.fstat(fd)
            status = (self.root / name).lstat()
            _plain(opened)
            _plain(status)
            if _identity(opened) != identity or _identity(status) != identity:
                raise TemporaryOwnershipError("ownership_unconfirmed")

    @staticmethod
    def _delete(path: Path, identity: _Identity, *, directory: bool = False) -> None:
        # Child writers use ordinary opens without FILE_SHARE_DELETE. Release
        # the old read pin only immediately before opening a DELETE handle.
        # Replacements in this gap fail identity verification and survive.
        fd = TrackedOriginalStore._windows_fd(path, directory=directory, delete=True)
        try:
            status = os.fstat(fd)
            _plain(status, directory=directory)
            if _identity(status) != identity:
                raise TemporaryOwnershipError("ownership_unconfirmed")
            TrackedOriginalStore._mark_delete(fd)
        finally:
            os.close(fd)

    def discard(self) -> None:
        self._live()
        try:
            self._preflight()
            for name in list(self._files):
                self._preflight()
                fd, identity = self._files[name]
                assert fd is not None
                os.close(fd)
                self._files[name] = (None, identity)
                self._delete(self.root / name, identity)
                del self._files[name]
            self._preflight()
            fd = self._live()
            self._fd = None
            os.close(fd)
            self._delete(self.root, self._identity, directory=True)
        except OSError:
            raise TemporaryOwnershipError("ownership_unconfirmed") from None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for fd, _ in self._files.values():
            if fd is not None:
                os.close(fd)
        self._files.clear()
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self._pins.close()
