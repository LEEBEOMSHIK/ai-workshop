"""Low WinDLL and fixed-prefix file transport. Native/Store methods stay real."""

import ctypes
import io
import os
from pathlib import Path
from typing import Any, cast

import pytest

from ai_workshop.infrastructure.local.windows_private_state import Acl, Blob
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from tests.unit.labs.rag.indexing.test_access_epoch_secured_read_assembly import win32


class MaterialTransport:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, temporary: Path) -> None:
        self.private = PROJECT_ROOT / ".local-data/access-epoch/private"
        self.temporary = temporary / "material"
        self.temporary.mkdir()
        self.owner_valid = self.acl_valid = True
        self.cancel_decrypt = False
        self.dpapi_reads = self.acl_reads = self.opens = 0
        self.retained: dict[int, Any] = {}
        self.acl = Acl(2, 0, 8, 2, 0)
        self.aces = [
            ctypes.create_string_buffer(
                bytes([0, 0, 12, 0]) + (0x1F01FF).to_bytes(4, "little") + b"xxxx"
            )
            for _ in range(2)
        ]
        self.sid_values = {
            42: "S-1-5-21-12345",
            100: "S-1-5-21-12345",
            ctypes.addressof(self.aces[0]) + 8: "S-1-5-21-12345",
            ctypes.addressof(self.aces[1]) + 8: "S-1-5-18",
        }
        self.ancestors: dict[Path, Path] = {}
        for index, ancestor in enumerate(self.private.parents):
            target = self.temporary / f"ancestor-{index}"
            target.mkdir()
            self.ancestors[ancestor] = target
        self.files = self.temporary / "private"
        self.files.mkdir()
        self._install_files(monkeypatch)
        self._install_dll(monkeypatch)

    def mapped(self, path: Any) -> Path | None:
        if not isinstance(path, str | Path):
            return None
        candidate = Path(path)
        if candidate in self.ancestors:
            return self.ancestors[candidate]
        if candidate.is_relative_to(self.private):
            if ".." in candidate.parts:
                raise AssertionError("synthetic_private_path_denied")
            return self.files / candidate.relative_to(self.private)
        return None

    def seed(self, fixed: str, ciphertext: bytes) -> None:
        path = self.mapped(fixed)
        assert path is not None and path.is_relative_to(self.files)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(ciphertext)

    def _install_files(self, monkeypatch: pytest.MonkeyPatch) -> None:
        previous_stat, previous_read, previous_open = Path.stat, Path.read_bytes, io.open

        def info(path: Path, *args: Any, **kwargs: Any) -> Any:
            return previous_stat(self.mapped(path) or path, *args, **kwargs)

        def read(path: Path) -> bytes:
            return previous_read(self.mapped(path) or path)

        def opened(path: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            mapped = self.mapped(path)
            if mapped is not None:
                if mode != "rb":
                    raise AssertionError("synthetic_private_write_denied")
                self.opens += 1
                return previous_open(mapped, mode, *args, **kwargs)
            return previous_open(path, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", info)
        monkeypatch.setattr(Path, "read_bytes", read)
        monkeypatch.setattr(io, "open", opened)

        # Read-only integration must never fall through to original mutations.
        def reject_path_mutation(method: Any) -> Any:
            def operation(path: Path, *args: Any, **kwargs: Any) -> Any:
                if self.mapped(path) is not None or any(
                    self.mapped(value) is not None
                    for value in args
                    if isinstance(value, str | Path)
                ):
                    raise AssertionError("synthetic_private_write_denied")
                return method(path, *args, **kwargs)

            return operation

        for name in ("mkdir", "unlink", "rename", "replace"):
            monkeypatch.setattr(Path, name, reject_path_mutation(getattr(Path, name)))
        original_replace = os.replace

        def replace(source: Any, target: Any, *args: Any, **kwargs: Any) -> None:
            if self.mapped(source) is not None or self.mapped(target) is not None:
                raise AssertionError("synthetic_private_write_denied")
            original_replace(source, target, *args, **kwargs)

        monkeypatch.setattr(os, "replace", replace)

    def _install_dll(self, monkeypatch: pytest.MonkeyPatch) -> None:
        win32(monkeypatch)
        base = ctypes.WinDLL

        def sid(pointer: Any, output: Any) -> bool:
            key = pointer.value if isinstance(pointer, ctypes.c_void_p) else pointer
            assert type(key) is int
            output._obj.value = self.sid_values[key] if self.owner_valid else "S-1-5-21-other"
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
            assert Path(path).is_relative_to(self.private)
            self.acl_reads += 1
            owner._obj.value = 100
            if dacl is not None:
                dacl._obj.value = ctypes.addressof(self.acl)
            descriptor._obj.value = 500
            return 0

        def control(_descriptor: object, output: Any, _revision: object) -> bool:
            output._obj.value = 0x1000 if self.acl_valid else 0
            return True

        def ace(_acl: object, index: int, output: Any) -> bool:
            output._obj.value = ctypes.addressof(self.aces[index])
            return True

        def transform(
            incoming: Any,
            _description: object,
            _entropy: object,
            _reserved: object,
            _prompt: object,
            flags: int,
            outgoing: Any,
            *,
            decrypt: bool,
        ) -> bool:
            assert flags == 1
            source = ctypes.cast(incoming, ctypes.POINTER(Blob)).contents
            raw = ctypes.string_at(source.data, source.length)
            if decrypt:
                import asyncio

                self.dpapi_reads += 1
                if self.cancel_decrypt:
                    raise asyncio.CancelledError()
                assert raw.startswith(b"synthetic:")
                data = bytes(value ^ 0xA5 for value in raw[10:])
            else:
                data = b"synthetic:" + bytes(value ^ 0xA5 for value in raw)
            buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
            self.retained[ctypes.addressof(buffer)] = buffer
            result = ctypes.cast(outgoing, ctypes.POINTER(Blob)).contents
            result.length = len(data)
            result.data = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
            return True

        def free(pointer: Any) -> None:
            address = pointer.value if isinstance(pointer, ctypes.c_void_p) else pointer
            if type(address) is int:
                self.retained.pop(address, None)

        def dll(name: str, **kwargs: Any) -> Any:
            result = cast(Any, base(name, **kwargs))
            if name == "kernel32":
                result.LocalFree.implementation = free
            elif name == "advapi32":
                for method, implementation in [
                    ("ConvertSidToStringSidW", sid),
                    ("GetNamedSecurityInfoW", info),
                    ("GetSecurityDescriptorControl", control),
                    ("GetAce", ace),
                ]:
                    getattr(result, method).implementation = implementation
            elif name == "crypt32":
                result.CryptProtectData.implementation = lambda *args: transform(
                    *args, decrypt=False
                )
                result.CryptUnprotectData.implementation = lambda *args: transform(
                    *args, decrypt=True
                )
            return result

        monkeypatch.setattr(ctypes, "WinDLL", dll)
