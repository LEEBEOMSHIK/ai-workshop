"""Exact-path publication for journaled originals; never adopts existing files."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import AsyncIterator
from contextlib import ExitStack, suppress
from pathlib import Path
from uuid import UUID

from ai_workshop.platform.assets.storage import StoredObject
from ai_workshop.platform.assets.upload_contracts import (
    OriginalFileObservation,
    OriginalStoreBinding,
    UploadClaim,
    UploadOwnershipError,
    validate_stored,
)

_MARKER = ".ai-workshop-original-store.json"
_REPARSE = 0x400
_Identity = tuple[int, int]
_Fingerprint = tuple[int, int, int, int, int]


class TrackedOriginalStore:
    def __init__(self, root: Path, binding: OriginalStoreBinding) -> None:
        if not isinstance(root, Path) or type(binding) is not OriginalStoreBinding:
            raise UploadOwnershipError("store_unavailable")
        self.root = root.absolute()
        self.binding = binding
        self._root_identity: _Identity | None = None
        # Only this live writer can roll back its publication. Observation grants
        # no deletion authority, including after a process restart.
        self._published: dict[UploadClaim, tuple[StoredObject, _Fingerprint]] = {}
        self._attempted: set[UUID] = set()

    def verify_binding(self) -> None:
        root_status = self._plain(self.root, directory=True)
        try:
            resolved = self.root.resolve(strict=True)
        except OSError:
            raise UploadOwnershipError("store_unavailable") from None
        if os.path.normcase(str(resolved)) != os.path.normcase(str(self.root)):
            raise UploadOwnershipError("unsafe_path")
        root_identity = self._identity(root_status)
        if self._root_identity is not None and root_identity != self._root_identity:
            raise UploadOwnershipError("binding_mismatch")
        marker = self._child(self.root, _MARKER)
        if marker is None:
            raise UploadOwnershipError("invalid_marker")
        status = self._plain(marker)
        try:
            with marker.open("rb") as stream:
                if self._fingerprint(os.fstat(stream.fileno())) != self._fingerprint(status):
                    raise UploadOwnershipError("unsafe_path")
                raw = stream.read(4097)
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise UploadOwnershipError("invalid_marker") from None
        if (
            len(raw) > 4096
            or type(value) is not dict
            or set(value) != {"schema_version", "store_id", "binding_id"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or type(value["store_id"]) is not str
            or type(value["binding_id"]) is not str
        ):
            raise UploadOwnershipError("invalid_marker")
        if value != {
            "schema_version": 1,
            "store_id": self.binding.store_id,
            "binding_id": str(self.binding.binding_id),
        }:
            raise UploadOwnershipError("binding_mismatch")
        if self._fingerprint(self._plain(marker)) != self._fingerprint(status):
            raise UploadOwnershipError("invalid_marker")
        self._root_identity = root_identity

    async def publish(self, claim: UploadClaim, source: AsyncIterator[bytes]) -> StoredObject:
        self._validate_claim(claim)
        self._require_safe_mutations()
        self.verify_binding()
        if claim.attempt_id in self._attempted:
            raise UploadOwnershipError("writer_unconfirmed")
        try:
            with ExitStack() as pins:
                self._pin_store(pins)
                self._pin_object_parents(claim, pins)
                self.verify_binding()
                return await self._publish_pinned(claim, source)
        except OSError:
            raise UploadOwnershipError("store_unavailable") from None

    async def _publish_pinned(
        self, claim: UploadClaim, source: AsyncIterator[bytes]
    ) -> StoredObject:
        canonical = self._path(claim.canonical_key)
        temporary = self._path(claim.temporary_key)
        if canonical is not None or temporary is not None:
            raise UploadOwnershipError("file_conflict")
        canonical = self.root / claim.canonical_key
        temporary = self.root / claim.temporary_key
        parent_identity = self._identity(self._plain(temporary.parent, directory=True))
        self._attempted.add(claim.attempt_id)
        try:
            target = temporary.open("xb")
        except FileExistsError:
            raise UploadOwnershipError("file_conflict") from None
        except OSError:
            raise UploadOwnershipError("store_unavailable") from None
        identity: _Identity | None = None
        linked = False
        digest = hashlib.sha256()
        size = 0
        try:
            with target:
                identity = self._identity(os.fstat(target.fileno()))
                async for chunk in source:
                    target.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                target.flush()
                os.fsync(target.fileno())
            self.verify_binding()
            if self._path(claim.temporary_key) != temporary:
                raise UploadOwnershipError("ownership_unconfirmed")
            if (
                self._identity(self._plain(temporary)) != identity
                or self._identity(self._plain(temporary.parent, directory=True)) != parent_identity
            ):
                raise UploadOwnershipError("ownership_unconfirmed")
            if self._path(claim.canonical_key) is not None:
                raise UploadOwnershipError("file_conflict")
            # The writer has closed. Acquire a read-only, no-delete-sharing
            # handle and verify it before any pathname-based publication.
            # A replacement during the close/open gap is rejected; once open,
            # Windows prevents replacing or rewriting the link source.
            with ExitStack() as source_pin:
                source_fd = self._windows_fd(temporary)
                source_pin.callback(os.close, source_fd)
                opened = os.fstat(source_fd)
                self._validate_status(opened)
                if self._identity(opened) != identity:
                    raise UploadOwnershipError("ownership_unconfirmed")
                try:
                    os.link(temporary, canonical)
                except FileExistsError:
                    raise UploadOwnershipError("file_conflict") from None
                linked = True
        except OSError:
            raise UploadOwnershipError("store_unavailable") from None
        finally:
            # Includes CancelledError. Never remove canonical in a writer error
            # path: a DB caller may not know the publication/commit outcome.
            if identity is not None:
                cleaned = self._remove_temporary(claim, identity, linked=linked)
            else:
                cleaned = False
        if not cleaned:
            raise UploadOwnershipError("ownership_unconfirmed")
        observation = self.observe(claim)
        expected = StoredObject(claim.canonical_key, size, digest.hexdigest())
        if observation.canonical != expected or observation.temporary_exists:
            raise UploadOwnershipError("content_mismatch")
        status = self._plain(canonical)
        if self._identity(status) != identity:
            raise UploadOwnershipError("ownership_unconfirmed")
        self._published[claim] = (expected, self._fingerprint(status))
        return expected

    def observe(self, claim: UploadClaim) -> OriginalFileObservation:
        self._validate_claim(claim)
        self.verify_binding()
        canonical = self._path(claim.canonical_key)
        temporary = self._path(claim.temporary_key)
        stored = self._describe(canonical, claim.canonical_key) if canonical is not None else None
        self.verify_binding()
        return OriginalFileObservation(stored, temporary is not None)

    def discard(self, claim: UploadClaim, expected: StoredObject) -> None:
        self._validate_claim(claim)
        self._require_safe_mutations()
        validate_stored(claim, expected)
        self.verify_binding()
        owned = self._published.get(claim)
        if owned is None or owned[0] != expected:
            raise UploadOwnershipError("ownership_unconfirmed")
        path = self._path(claim.canonical_key)
        if path is None:
            raise UploadOwnershipError("ownership_unconfirmed")
        if self._fingerprint(self._plain(path)) != owned[1]:
            raise UploadOwnershipError("ownership_unconfirmed")
        if self._describe(path, claim.canonical_key) != expected:
            raise UploadOwnershipError("content_mismatch")
        if self._path(claim.temporary_key) is not None:
            raise UploadOwnershipError("writer_unconfirmed")
        self.verify_binding()
        if self._path(claim.canonical_key) != path:
            raise UploadOwnershipError("ownership_unconfirmed")
        if self._fingerprint(self._plain(path)) != owned[1]:
            raise UploadOwnershipError("ownership_unconfirmed")
        self._delete_exact(path, owned[1][:2], fingerprint=owned[1], expected=expected)
        del self._published[claim]
        self.verify_binding()
        if self._path(claim.canonical_key) is not None:
            raise UploadOwnershipError("ownership_unconfirmed")

    def _validate_claim(self, claim: UploadClaim) -> None:
        if type(claim) is not UploadClaim:
            raise UploadOwnershipError("invalid_claim")
        try:
            claim.__post_init__()
            claim.source.__post_init__()
            claim.binding.__post_init__()
        except (ValueError, TypeError, AttributeError):
            raise UploadOwnershipError("invalid_claim") from None
        if claim.binding != self.binding:
            raise UploadOwnershipError("binding_mismatch")

    def _child(self, parent: Path, name: str) -> Path | None:
        try:
            with os.scandir(parent) as entries:
                names = [entry.name for entry in entries]
        except OSError:
            raise UploadOwnershipError("store_unavailable") from None
        if any(value.casefold() == name.casefold() and value != name for value in names):
            raise UploadOwnershipError("unsafe_path")
        return parent / name if name in names else None

    def _path(self, key: str, *, allowed_links: int = 1) -> Path | None:
        parts = key.split("/")
        if len(parts) != 3 or any(part in {"", ".", ".."} for part in parts):
            raise UploadOwnershipError("unsafe_path")
        if any("\\" in part or ":" in part for part in parts):
            raise UploadOwnershipError("unsafe_path")
        parent = self.root
        for part in parts[:-1]:
            child = self._child(parent, part)
            if child is None:
                return None
            self._plain(child, directory=True)
            parent = child
        child = self._child(parent, parts[-1])
        if child is not None:
            self._plain(child, allowed_links=allowed_links)
        return child

    @staticmethod
    def _plain(path: Path, *, directory: bool = False, allowed_links: int = 1) -> os.stat_result:
        try:
            status = path.lstat()
        except OSError:
            raise UploadOwnershipError("store_unavailable") from None
        if stat.S_ISLNK(status.st_mode) or getattr(status, "st_file_attributes", 0) & _REPARSE:
            raise UploadOwnershipError("unsafe_path")
        if directory:
            valid = stat.S_ISDIR(status.st_mode)
        else:
            valid = stat.S_ISREG(status.st_mode) and status.st_nlink == allowed_links
        if not valid:
            raise UploadOwnershipError("unsafe_path")
        return status

    def _describe(self, path: Path, key: str) -> StoredObject:
        status = self._plain(path)
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open("rb") as stream:
                if self._fingerprint(os.fstat(stream.fileno())) != self._fingerprint(status):
                    raise UploadOwnershipError("ownership_unconfirmed")
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                if self._fingerprint(os.fstat(stream.fileno())) != self._fingerprint(status):
                    raise UploadOwnershipError("content_mismatch")
        except OSError:
            raise UploadOwnershipError("store_unavailable") from None
        if self._fingerprint(self._plain(path)) != self._fingerprint(status):
            raise UploadOwnershipError("ownership_unconfirmed")
        return StoredObject(key, size, digest.hexdigest())

    def _remove_temporary(self, claim: UploadClaim, identity: _Identity, *, linked: bool) -> bool:
        try:
            self.verify_binding()
            links = 2 if linked else 1
            path = self._path(claim.temporary_key, allowed_links=links)
            if path is None or self._identity(self._plain(path, allowed_links=links)) != identity:
                return False
            if linked:
                canonical = self._path(claim.canonical_key, allowed_links=2)
                if (
                    canonical is None
                    or self._identity(self._plain(canonical, allowed_links=2)) != identity
                ):
                    return False
            self._delete_exact(path, identity, allowed_links=links)
            self.verify_binding()
            return self._path(claim.temporary_key) is None
        except (UploadOwnershipError, OSError):
            return False

    @staticmethod
    def _require_safe_mutations() -> None:
        # POSIX unlink cannot conditionally delete an inode. A Linux writer
        # needs fd-backed publication before automatic cleanup is safe.
        if os.name != "nt":
            raise UploadOwnershipError("store_unavailable")

    def _pin_directory(self, pins: ExitStack, path: Path) -> None:
        before = self._plain(path, directory=True)
        fd = self._windows_fd(path, directory=True)
        pins.callback(os.close, fd)
        opened = os.fstat(fd)
        self._validate_status(opened, directory=True)
        if self._identity(opened) != self._identity(before):
            raise UploadOwnershipError("ownership_unconfirmed")

    def _pin_store(self, pins: ExitStack) -> None:
        for parent in reversed((self.root, *self.root.parents)):
            self._pin_directory(pins, parent)
        marker_fd = self._windows_fd(self.root / _MARKER)
        pins.callback(os.close, marker_fd)
        self._validate_status(os.fstat(marker_fd))
        self.verify_binding()

    def _pin_object_parents(self, claim: UploadClaim, pins: ExitStack) -> None:
        parent = self.root
        for name in claim.canonical_key.split("/")[:-1]:
            child = self._child(parent, name)
            if child is None:
                with suppress(FileExistsError):
                    (parent / name).mkdir()
                child = self._child(parent, name)
                if child is None:
                    raise UploadOwnershipError("store_unavailable")
            # Parent is already pinned before creating/opening each child.
            self._pin_directory(pins, child)
            parent = child

    def _delete_exact(
        self,
        path: Path,
        identity: _Identity,
        *,
        allowed_links: int = 1,
        fingerprint: _Fingerprint | None = None,
        expected: StoredObject | None = None,
    ) -> None:
        """Delete the verified Windows handle, never a later pathname occupant.

        Parent handles omit FILE_SHARE_DELETE, preventing ancestor rename;
        the target additionally omits FILE_SHARE_WRITE, freezing its bytes.
        See Microsoft CreateFileW and SetFileInformationByHandle contracts.
        """
        self._require_safe_mutations()
        try:
            with ExitStack() as stack:
                # Pin the complete ancestor chain, not just the final parent.
                for parent in reversed(path.parents):
                    before = self._plain(parent, directory=True)
                    fd = self._windows_fd(parent, directory=True)
                    stack.callback(os.close, fd)
                    opened = os.fstat(fd)
                    self._validate_status(opened, directory=True)
                    if self._identity(opened) != self._identity(before):
                        raise UploadOwnershipError("ownership_unconfirmed")
                marker_fd = self._windows_fd(self.root / _MARKER)
                stack.callback(os.close, marker_fd)
                self._validate_status(os.fstat(marker_fd))
                self.verify_binding()
                fd = self._windows_fd(path, delete=True)
                stack.callback(os.close, fd)
                opened = os.fstat(fd)
                self._validate_status(opened, allowed_links=allowed_links)
                if self._identity(opened) != identity:
                    raise UploadOwnershipError("ownership_unconfirmed")
                if fingerprint is not None and self._fingerprint(opened) != fingerprint:
                    raise UploadOwnershipError("ownership_unconfirmed")
                if expected is not None:
                    digest = hashlib.sha256()
                    size = 0
                    while chunk := os.read(fd, 1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                    if size != expected.size or digest.hexdigest() != expected.sha256:
                        raise UploadOwnershipError("content_mismatch")
                # The open handles remain held through this OS operation.
                # A concurrent pathname or ancestor replacement cannot redirect it.
                self._mark_delete(fd)
        except OSError:
            raise UploadOwnershipError("ownership_unconfirmed") from None

    @staticmethod
    def _windows_fd(path: Path, *, directory: bool = False, delete: bool = False) -> int:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        # Attribute-only directory handles do not enforce the sharing fence
        # on empty directories. GENERIC_READ is required to block their rename.
        access = 0x80000000  # GENERIC_READ, including directories
        if delete:
            access |= 0x10000  # DELETE, needed by FileDispositionInfo
        sharing = 0x3 if directory else 0x1  # READ|WRITE / READ; never DELETE
        flags = 0x00200000 | (0x02000000 if directory else 0)  # reparse / backup semantics
        filename = str(path)
        if not filename.startswith("\\\\?\\"):
            filename = (
                "\\\\?\\UNC\\" + filename[2:]
                if filename.startswith("\\\\")
                else "\\\\?\\" + filename
            )
        handle = create(filename, access, sharing, None, 3, flags, None)  # OPEN_EXISTING
        if handle == ctypes.c_void_p(-1).value:
            raise OSError("Cannot acquire exact original file handle")
        try:
            return msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
        except BaseException:
            close(handle)
            raise

    @staticmethod
    def _mark_delete(fd: int) -> None:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        set_info = kernel.SetFileInformationByHandle
        set_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        set_info.restype = wintypes.BOOL
        disposition = ctypes.c_bool(True)  # FILE_DISPOSITION_INFO.DeleteFile (BOOLEAN)
        if not set_info(
            msvcrt.get_osfhandle(fd), 4, ctypes.byref(disposition), ctypes.sizeof(disposition)
        ):
            raise OSError("Cannot delete exact original file handle")

    @staticmethod
    def _validate_status(
        status: os.stat_result,
        *,
        directory: bool = False,
        allowed_links: int = 1,
    ) -> None:
        if stat.S_ISLNK(status.st_mode) or getattr(status, "st_file_attributes", 0) & _REPARSE:
            raise UploadOwnershipError("unsafe_path")
        valid = (
            stat.S_ISDIR(status.st_mode)
            if directory
            else (stat.S_ISREG(status.st_mode) and status.st_nlink == allowed_links)
        )
        if not valid:
            raise UploadOwnershipError("unsafe_path")

    @staticmethod
    def _identity(status: os.stat_result) -> _Identity:
        return status.st_dev, status.st_ino

    @staticmethod
    def _fingerprint(status: os.stat_result) -> _Fingerprint:
        # Windows lstat exposes legacy creation-time ctime whereas fstat can
        # expose change time; birthtime is consistent across both APIs.
        return (
            status.st_dev,
            status.st_ino,
            status.st_size,
            status.st_mtime_ns,
            getattr(status, "st_birthtime_ns", status.st_ctime_ns),
        )
