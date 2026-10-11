"""Native DPAPI/owner ACL adapter. No runtime policy or RAG dependency."""

import ctypes
import os
import stat
from _ctypes import CFuncPtr
from ctypes import wintypes as w
from dataclasses import dataclass
from pathlib import Path
from types import FunctionType, MethodType
from typing import Literal
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary, WeakSet

type PrivateStateFailure = Literal[
    "native_call_failed",
    "owner_query_failed",
    "owner_mismatch",
    "dacl_set_failed",
    "dacl_query_failed",
    "dacl_missing",
    "dacl_not_protected",
    "ace_shape_invalid",
    "ace_principal_invalid",
    "read_capture_invalid",
    "read_capture_exists",
    "read_capture_outcome_unknown",
    "native_origin_changed",
    "protected_read_invalid",
    "protected_read_changed",
]

type ReadCapturePhase = Literal[
    "intent", "child", "resume_intent", "terminal", "capture", "cleanup"
]
_READ_PHASES = ("intent", "child", "resume_intent", "terminal", "capture", "cleanup")
_READ_MAGIC = b"AIWRREAD01"
_READ_PLAIN_LIMIT = 4 * 1024 * 1024
_READ_DATA_LIMIT = _READ_PLAIN_LIMIT - 32  # Selector-bound binary envelope is 32 bytes.
_READ_CIPHER_LIMIT = _READ_PLAIN_LIMIT + 64 * 1024


class NativePrivateStateError(OSError):
    def __init__(
        self, reason_code: PrivateStateFailure, native_error_code: int | None = None
    ) -> None:
        super().__init__("native_private_state_denied")
        self.reason_code = reason_code
        self.native_error_code = native_error_code


class Blob(ctypes.Structure):
    _fields_ = [("length", w.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


class SidAndAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", w.DWORD)]


class Acl(ctypes.Structure):
    _fields_ = [
        ("revision", w.BYTE),
        ("reserved", w.BYTE),
        ("size", w.WORD),
        ("count", w.WORD),
        ("reserved2", w.WORD),
    ]


_ORIGIN_DLLS = {
    "kernel": ("kernel32", ("GetCurrentProcess", "LocalFree", "CloseHandle", "MoveFileExW")),
    "advapi": (
        "advapi32",
        (
            "OpenProcessToken",
            "GetTokenInformation",
            "ConvertSidToStringSidW",
            "GetNamedSecurityInfoW",
            "GetSecurityDescriptorControl",
            "GetAce",
            "ConvertStringSecurityDescriptorToSecurityDescriptorW",
            "GetSecurityDescriptorOwner",
            "GetSecurityDescriptorDacl",
            "SetNamedSecurityInfoW",
        ),
    ),
    "crypt": ("crypt32", ("CryptProtectData", "CryptUnprotectData")),
}
_ORIGIN_METHODS = (
    "protect",
    "unprotect",
    "read",
    "write",
    "remove",
    "_check_path",
    "_check_acl",
    "read_protected",
    "_protected_file_state",
    "_protected_file_identity",
    "_sid_text",
)


@dataclass(frozen=True, slots=True, repr=False)
class ProtectedFileRead:
    """Ordinary checked bytes and identity; no source or operational authority."""

    data: bytes
    identity: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True, repr=False)
class _NativeOrigin:
    signature: object
    references: tuple[object, ...]


_ORIGINS: WeakKeyDictionary["NativeWindowsPrivateState", _NativeOrigin] = WeakKeyDictionary()
_ORIGIN_ATTEMPTS: WeakSet["NativeWindowsPrivateState"] = WeakSet()


def _function_origin(function: FunctionType) -> tuple[object, tuple[object, ...]]:
    """Copy mutable callable defaults, retaining immutable code independently."""

    def primitive(value: object) -> object:
        if type(value) not in {str, int, bool, bytes, type(None)}:
            raise NativePrivateStateError("native_origin_changed")
        return type(value), value

    defaults, keywords = function.__defaults__, function.__kwdefaults__
    if defaults is not None and type(defaults) is not tuple:
        raise NativePrivateStateError("native_origin_changed")
    if keywords is not None and (
        type(keywords) is not dict or any(type(key) is not str for key in keywords)
    ):
        raise NativePrivateStateError("native_origin_changed")
    return (
        (
            type(function.__code__),
            id(function.__code__),
            None if defaults is None else tuple(primitive(v) for v in defaults),
            None
            if keywords is None
            else tuple(sorted((k, primitive(v)) for k, v in keywords.items())),
        ),
        (function.__code__,),
    )


def _origin_snapshot(value: "NativeWindowsPrivateState") -> _NativeOrigin:
    if (
        type(value) is not NativeWindowsPrivateState
        or type(value.root) is not type(Path())
        or type(value.private) is not type(Path())
        or type(value.owner) is not str
        or not value.owner.startswith("S-1-")
    ):
        raise NativePrivateStateError("native_origin_changed")
    signature: list[object] = [
        (type(value.root), str(value.root)),
        (type(value.private), str(value.private)),
        (type(value.owner), value.owner),
    ]
    references: list[object] = []
    for attribute, (name, functions) in _ORIGIN_DLLS.items():
        dll = getattr(value, attribute)
        if type(dll._name) is not str or dll._name != name or type(dll._handle) is not int:
            raise NativePrivateStateError("native_origin_changed")
        references.append(dll)
        descriptors: list[object] = []
        for function in functions:
            fn = getattr(dll, function)
            arguments = fn.argtypes
            if arguments is not None and (
                type(arguments) not in (list, tuple)
                or not all(isinstance(item, type) for item in arguments)
            ):
                raise NativePrivateStateError("native_origin_changed")
            result = fn.restype
            if result is not None and not isinstance(result, type):
                raise NativePrivateStateError("native_origin_changed")
            address = ctypes.cast(fn, ctypes.c_void_p).value if isinstance(fn, CFuncPtr) else None
            checker = getattr(fn, "errcheck", None)
            references.extend((fn, result, checker))
            if arguments is not None:
                references.extend(arguments)
            descriptors.append(
                (
                    type(fn),
                    id(fn),
                    address,
                    type(arguments),
                    None if arguments is None else tuple((type(v), id(v)) for v in arguments),
                    type(result),
                    id(result),
                    type(checker),
                    id(checker),
                )
            )
        signature.append(
            (
                type(dll),
                id(dll),
                (type(dll._name), dll._name),
                (type(dll._handle), dll._handle),
                tuple(descriptors),
            )
        )
    for name in _ORIGIN_METHODS:
        method = getattr(value, name)
        if type(method) is not MethodType or method.__self__ is not value:
            raise NativePrivateStateError("native_origin_changed")
        method_function = method.__func__
        if type(method_function) is not FunctionType:
            raise NativePrivateStateError("native_origin_changed")
        content, retained = _function_origin(method_function)
        references.append(method_function)
        references.extend(retained)
        signature.append((name, type(method), id(method_function), content))
    requirement = value._require
    if type(requirement) is not FunctionType:
        raise NativePrivateStateError("native_origin_changed")
    content, retained = _function_origin(requirement)
    references.append(requirement)
    references.extend(retained)
    signature.append(("_require", type(requirement), id(requirement), content))
    return _NativeOrigin(tuple(signature), tuple(references))


class NativeWindowsPrivateState:
    def __init__(self, root: Path) -> None:
        if type(self) is not NativeWindowsPrivateState or self in _ORIGIN_ATTEMPTS:
            raise NativePrivateStateError("native_origin_changed")
        _ORIGIN_ATTEMPTS.add(self)
        if os.name != "nt":
            raise OSError("native_private_state_unavailable")
        self.root = root.absolute()
        self.private = self.root / ".local-data/access-epoch/private"
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        self.kernel.GetCurrentProcess.restype = w.HANDLE
        self.kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel.LocalFree.restype = ctypes.c_void_p
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.MoveFileExW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.DWORD]
        self.kernel.MoveFileExW.restype = w.BOOL
        self.advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
        self.advapi.GetTokenInformation.argtypes = [
            w.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            w.DWORD,
            ctypes.POINTER(w.DWORD),
        ]
        self.advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
        self.advapi.GetNamedSecurityInfoW.argtypes = [
            w.LPWSTR,
            ctypes.c_int,
            w.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.advapi.GetNamedSecurityInfoW.restype = w.DWORD
        self.advapi.GetSecurityDescriptorControl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(w.WORD),
            ctypes.POINTER(w.DWORD),
        ]
        self.advapi.GetAce.argtypes = [ctypes.c_void_p, w.DWORD, ctypes.POINTER(ctypes.c_void_p)]
        self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            w.LPCWSTR,
            w.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
        ]
        self.advapi.GetSecurityDescriptorOwner.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(w.BOOL),
        ]
        self.advapi.GetSecurityDescriptorDacl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(w.BOOL),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(w.BOOL),
        ]
        self.advapi.SetNamedSecurityInfoW.argtypes = [
            w.LPWSTR,
            ctypes.c_int,
            w.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.advapi.SetNamedSecurityInfoW.restype = w.DWORD
        for name in ("CryptProtectData", "CryptUnprotectData"):
            getattr(self.crypt, name).argtypes = [
                ctypes.POINTER(Blob),
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                w.DWORD,
                ctypes.POINTER(Blob),
            ]
        self.owner = self._current_sid()
        _ORIGINS[self] = _origin_snapshot(self)

    def assert_origin(self) -> None:
        """Memory-only constructor binding; never adopts an unregistered object."""
        try:
            if type(self) is not NativeWindowsPrivateState:
                raise NativePrivateStateError("native_origin_changed")
            origin = _ORIGINS.get(self)
            if origin is None or origin.signature != _origin_snapshot(self).signature:
                raise NativePrivateStateError("native_origin_changed")
        except Exception:
            raise NativePrivateStateError("native_origin_changed") from None

    @staticmethod
    def _require(
        success: object,
        reason_code: PrivateStateFailure = "native_call_failed",
        native_error_code: int | None = None,
    ) -> None:
        if not success:
            raise NativePrivateStateError(reason_code, native_error_code)

    def _sid_text(self, sid: ctypes.c_void_p) -> str:
        output = w.LPWSTR()
        self._require(self.advapi.ConvertSidToStringSidW(sid, ctypes.byref(output)))
        try:
            return output.value or ""
        finally:
            self.kernel.LocalFree(ctypes.cast(output, ctypes.c_void_p))

    def _current_sid(self) -> str:
        token, size = w.HANDLE(), w.DWORD()
        self._require(
            self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, ctypes.byref(token))
        )
        try:
            self.advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            self._require(0 < size.value < 65536)
            buffer = ctypes.create_string_buffer(size.value)
            self._require(
                self.advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size))
            )
            user = ctypes.cast(buffer, ctypes.POINTER(SidAndAttributes)).contents
            return self._sid_text(user.sid)
        finally:
            self.kernel.CloseHandle(token)

    def _transform(self, data: bytes, decrypt: bool) -> bytes:
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        incoming, outgoing = Blob(len(data), buffer), Blob()
        method = self.crypt.CryptUnprotectData if decrypt else self.crypt.CryptProtectData
        # CurrentUser only. UI forbidden; LOCAL_MACHINE is deliberately absent.
        self._require(
            method(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing))
        )
        try:
            return ctypes.string_at(outgoing.data, outgoing.length)
        finally:
            self.kernel.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))

    def protect(self, data: bytes) -> bytes:
        return self._transform(data, False)

    def unprotect(self, data: bytes) -> bytes:
        return self._transform(data, True)

    def _check_path(self, value: str) -> Path:
        path = Path(value)
        self._require(".." not in path.parts and path.absolute().is_relative_to(self.private))
        for item in (*reversed(path.parents), path):
            if item.exists() or item.is_symlink():
                info = item.stat(follow_symlinks=False)
                self._require(not item.is_symlink() and not (info.st_file_attributes & 0x400))
        return path

    def _check_owner(self, path: Path) -> None:
        owner, descriptor = ctypes.c_void_p(), ctypes.c_void_p()
        code = self.advapi.GetNamedSecurityInfoW(
            str(path), 1, 1, ctypes.byref(owner), None, None, None, ctypes.byref(descriptor)
        )
        self._require(code == 0, "owner_query_failed", code)
        try:
            self._require(self._sid_text(owner) == self.owner, "owner_mismatch")
        finally:
            self.kernel.LocalFree(descriptor)

    def _set_acl(self, path: Path) -> None:
        # Existing ownership is a precondition, never something this adapter takes.
        # Setting OWNER as well would require WRITE_OWNER even when unchanged.
        self._check_owner(path)
        descriptor, dacl = ctypes.c_void_p(), ctypes.c_void_p()
        present, defaulted = w.BOOL(), w.BOOL()
        sddl = f"D:P(A;;FA;;;{self.owner})(A;;FA;;;SY)"
        self._require(
            self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, ctypes.byref(descriptor), None
            )
        )
        try:
            self._require(
                self.advapi.GetSecurityDescriptorDacl(
                    descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
                )
            )
            self._require(present.value and dacl.value)
            code = self.advapi.SetNamedSecurityInfoW(
                str(path), 1, 0x80000004, None, None, dacl, None
            )
            self._require(code == 0, "dacl_set_failed", code)
            self._check_owner(path)
        finally:
            self.kernel.LocalFree(descriptor)

    def _check_acl(self, path: Path) -> None:
        owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        code = self.advapi.GetNamedSecurityInfoW(
            str(path),
            1,
            5,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        self._require(code == 0, "dacl_query_failed", code)
        try:
            self._require(self._sid_text(owner) == self.owner, "owner_mismatch")
            self._require(dacl.value, "dacl_missing")
            control, revision = w.WORD(), w.DWORD()
            self._require(
                self.advapi.GetSecurityDescriptorControl(
                    descriptor, ctypes.byref(control), ctypes.byref(revision)
                )
            )
            self._require(control.value & 0x1000, "dacl_not_protected")
            acl = ctypes.cast(dacl, ctypes.POINTER(Acl)).contents
            allowed = set()
            for index in range(acl.count):
                ace = ctypes.c_void_p()
                self._require(self.advapi.GetAce(dacl, index, ctypes.byref(ace)))
                header = ctypes.string_at(ace, 8)
                self._require(
                    header[0] == 0
                    and header[1] == 0
                    and int.from_bytes(header[4:8], "little") == 0x1F01FF,
                    "ace_shape_invalid",
                )
                sid = self._sid_text(ctypes.c_void_p((ace.value or 0) + 8))
                self._require(
                    sid in {self.owner, "S-1-5-18"} and sid not in allowed, "ace_principal_invalid"
                )
                allowed.add(sid)
            self._require(allowed == {self.owner, "S-1-5-18"}, "ace_principal_invalid")
        finally:
            self.kernel.LocalFree(descriptor)

    def _ensure_parents(self, path: Path) -> None:
        # Only this feature's private subtree is hardened; public project dirs are untouched.
        self.private.parent.mkdir(parents=True, exist_ok=True)
        if not self.private.exists():
            self.private.mkdir()
            self._set_acl(self.private)
        self._check_acl(self.private)
        current = self.private
        for part in path.parent.relative_to(self.private).parts:
            current /= part
            if not current.exists():
                current.mkdir()
                self._set_acl(current)
            self._check_acl(current)

    def write(self, value: str, data: bytes) -> None:
        path = self._check_path(value)
        self._ensure_parents(path)
        if path.exists():
            self._check_acl(path)
        temporary = path.with_name(f".{uuid4()}.pending")
        with temporary.open("xb") as output:
            self._set_acl(temporary)
            self._check_acl(temporary)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        self._check_acl(path)

    def read(self, value: str) -> bytes | None:
        path = self._check_path(value)
        if not path.exists():
            return None
        for item in (
            self.private,
            *[p for p in path.parents if p.is_relative_to(self.private)],
            path,
        ):
            self._check_acl(item)
        return path.read_bytes()

    def _protected_file_identity(self, info: os.stat_result) -> tuple[int, int, int, int]:
        self._require(
            stat.S_ISREG(info.st_mode)
            and not (info.st_file_attributes & 0x400)
            and all(
                type(v) is int for v in (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            )
            and info.st_dev != 0
            and info.st_ino != 0
            and info.st_size > 0,
            "protected_read_invalid",
        )
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

    def _protected_file_state(self, path: Path) -> tuple[int, int, int, int]:
        self._check_path(str(path))
        # Public ancestors retain their existing ACLs. Private ancestors must
        # already exist and have the protected owner/System policy.
        for parent in path.parents:
            self._require(parent.is_dir(), "protected_read_invalid")
        for item in (
            *reversed(tuple(p for p in path.parents if p.is_relative_to(self.private))),
            path,
        ):
            self._check_acl(item)
        result = self._protected_file_identity(path.stat(follow_symlinks=False))
        NativeWindowsPrivateState.assert_origin(self)
        return result

    def read_protected(self, value: str, *, limit: int) -> ProtectedFileRead:
        """Read once with opened-handle identity, without writes or DPAPI calls.

        This is a bounded sampled read, not an atomic filesystem snapshot or
        atomic handle ACL assertion. Missing/ambiguous material denies.
        """
        output = None
        primary: BaseException | None = None
        try:
            NativeWindowsPrivateState.assert_origin(self)
            self._require(
                type(value) is str and type(limit) is int and 1 <= limit <= _READ_PLAIN_LIMIT,
                "protected_read_invalid",
            )
            self._require(Path(value).is_absolute(), "protected_read_invalid")
            path = self._check_path(value)
            before = self._protected_file_state(path)
            self._require(before[2] <= limit, "protected_read_invalid")
            output = path.open("rb")
            opened = self._protected_file_identity(os.fstat(output.fileno()))
            NativeWindowsPrivateState.assert_origin(self)
            self._require(opened == before, "protected_read_changed")
            data = output.read(limit + 1)
            NativeWindowsPrivateState.assert_origin(self)
            after_open = self._protected_file_identity(os.fstat(output.fileno()))
            after = self._protected_file_state(path)
            self._require(before == after_open == after, "protected_read_changed")
            self._require(type(data) is bytes and len(data) == before[2], "protected_read_changed")
        except BaseException as error:
            primary = error
            if isinstance(error, Exception) and not isinstance(error, NativePrivateStateError):
                primary = NativePrivateStateError("protected_read_invalid")
                raise primary from None
            raise
        finally:
            if output is not None:
                try:
                    output.close()
                except BaseException:
                    if primary is None:
                        raise NativePrivateStateError("protected_read_changed") from None
                    primary.add_note("protected_read_close_unverified")
        NativeWindowsPrivateState.assert_origin(self)
        return ProtectedFileRead(data, before)

    def _read_capture_path(self, nonce: UUID, slot: int, phase: ReadCapturePhase) -> Path:
        self._require(
            type(nonce) is UUID
            and nonce.int != 0
            and type(slot) is int
            and 0 <= slot <= 4
            and type(phase) is str
            and phase in _READ_PHASES,
            "read_capture_invalid",
        )
        return self._check_path(
            str(self.private / "read-checks" / str(nonce) / f"{slot}-{phase}.dpapi")
        )

    def _read_capture_file(self, path: Path) -> os.stat_result:
        self._check_path(str(path))
        for item in (
            self.private,
            *[p for p in path.parents if p.is_relative_to(self.private)],
            path,
        ):
            self._check_acl(item)
        value = path.stat(follow_symlinks=False)
        self._require(stat.S_ISREG(value.st_mode), "read_capture_invalid")
        return value

    @staticmethod
    def _read_file_identity(value: os.stat_result) -> tuple[int, int, int, int]:
        return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns

    def create_read_capture(
        self, nonce: UUID, slot: int, phase: ReadCapturePhase, data: bytes
    ) -> None:
        """Create exactly once; <=4MiB plaintext including the 32-byte binding.

        Existing equal records are not retries or successful recovery. Only an
        explicitly owned unpublished temporary file may be removed on failure.
        """
        temporary: Path | None = None
        temporary_identity: tuple[int, int] | None = None
        primary: BaseException | None = None
        try:
            path = self._read_capture_path(nonce, slot, phase)
            self._require(
                type(data) is bytes and 0 < len(data) <= _READ_DATA_LIMIT, "read_capture_invalid"
            )
            envelope = (
                _READ_MAGIC
                + nonce.bytes
                + bytes((slot, _READ_PHASES.index(phase)))
                + len(data).to_bytes(4, "big")
                + data
            )
            ciphertext = self.protect(envelope)
            self._require(
                type(ciphertext) is bytes and 0 < len(ciphertext) <= _READ_CIPHER_LIMIT,
                "read_capture_invalid",
            )
            self._ensure_parents(path)
            self._require(not path.exists(), "read_capture_exists")
            temporary = path.with_name(f".{uuid4()}.pending")
            with temporary.open("xb") as output:
                created = os.fstat(output.fileno())
                temporary_identity = created.st_dev, created.st_ino
                self._set_acl(temporary)
                self._read_capture_file(temporary)
                self._require(
                    output.write(ciphertext) == len(ciphertext), "read_capture_outcome_unknown"
                )
                output.flush()
                os.fsync(output.fileno())
            checked = self._read_capture_file(temporary)
            self._require(
                (checked.st_dev, checked.st_ino) == temporary_identity,
                "read_capture_outcome_unknown",
            )
            self._read_capture_path(nonce, slot, phase)
            # WRITE_THROUGH only: unlike os.replace, this Windows move cannot
            # replace a destination that appeared after the existence check.
            self._require(
                self.kernel.MoveFileExW(str(temporary), str(path), 8),
                "read_capture_outcome_unknown",
                ctypes.get_last_error(),
            )
            published = self._read_capture_file(path)
            self._require(
                (published.st_dev, published.st_ino) == temporary_identity,
                "read_capture_outcome_unknown",
            )
            self._require(
                self.read_read_capture(nonce, slot, phase) == data, "read_capture_outcome_unknown"
            )
        except BaseException as exc:
            primary = (
                exc
                if isinstance(exc, NativePrivateStateError) or not isinstance(exc, Exception)
                else NativePrivateStateError("read_capture_outcome_unknown")
            )
            raise primary from None
        finally:
            if temporary is not None and temporary_identity is not None:
                try:
                    if temporary.exists() or temporary.is_symlink():
                        self._check_path(str(temporary))
                        value = temporary.stat(follow_symlinks=False)
                        self._require(
                            stat.S_ISREG(value.st_mode)
                            and (value.st_dev, value.st_ino) == temporary_identity,
                            "read_capture_outcome_unknown",
                        )
                        self._check_owner(temporary)
                        temporary.unlink()
                except BaseException:
                    if primary is None:
                        raise NativePrivateStateError("read_capture_outcome_unknown") from None
                    primary.add_note("read_capture_temporary_cleanup_unverified")

    def read_read_capture(self, nonce: UUID, slot: int, phase: ReadCapturePhase) -> bytes | None:
        """Decrypt one fixed record; readback never grants permission to recreate it."""
        try:
            path = self._read_capture_path(nonce, slot, phase)
            if not path.exists():
                for parent in (
                    self.private,
                    *[p for p in path.parents if p.is_relative_to(self.private)],
                ):
                    if parent.exists():
                        self._require(parent.is_dir(), "read_capture_invalid")
                        self._check_acl(parent)
                return None
            before = self._read_capture_file(path)
            self._require(0 < before.st_size <= _READ_CIPHER_LIMIT, "read_capture_invalid")
            with path.open("rb") as source:
                opened = os.fstat(source.fileno())
                self._require(
                    self._read_file_identity(opened) == self._read_file_identity(before),
                    "read_capture_outcome_unknown",
                )
                ciphertext = source.read(_READ_CIPHER_LIMIT + 1)
                after_open = os.fstat(source.fileno())
            after = self._read_capture_file(path)
            self._require(
                self._read_file_identity(before)
                == self._read_file_identity(after)
                == self._read_file_identity(after_open),
                "read_capture_outcome_unknown",
            )
            self._require(0 < len(ciphertext) <= _READ_CIPHER_LIMIT, "read_capture_invalid")
            plaintext = self.unprotect(ciphertext)
            self._require(
                type(plaintext) is bytes and 32 < len(plaintext) <= _READ_PLAIN_LIMIT,
                "read_capture_invalid",
            )
            expected = _READ_MAGIC + nonce.bytes + bytes((slot, _READ_PHASES.index(phase)))
            self._require(
                plaintext[:28] == expected
                and int.from_bytes(plaintext[28:32], "big") == len(plaintext) - 32,
                "read_capture_invalid",
            )
            self._require(
                self._read_file_identity(self._read_capture_file(path))
                == self._read_file_identity(before),
                "read_capture_outcome_unknown",
            )
            return plaintext[32:]
        except BaseException as exc:
            if isinstance(exc, NativePrivateStateError) or not isinstance(exc, Exception):
                raise
            raise NativePrivateStateError("read_capture_outcome_unknown") from None

    def remove(self, value: str) -> None:
        path = self._check_path(value)
        self._require(path.parent == self.private / "launches" and path.suffix == ".dpapi")
        self._require(str(UUID(path.stem)) == path.stem)
        if path.exists():
            self._check_acl(path)
            path.unlink()
