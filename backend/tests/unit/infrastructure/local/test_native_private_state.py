"""Feed native ACL inspection actual byte structures, without changing host ACLs."""

import asyncio
import ctypes
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from ai_workshop.infrastructure.local.windows_private_state import (
    Acl,
    NativePrivateStateError,
    NativeWindowsPrivateState,
)


def native_acl(
    *,
    sids: tuple[str, ...] = ("owner", "S-1-5-18"),
    flags: int = 0,
    protected: bool = True,
    owner: str = "owner",
) -> NativeWindowsPrivateState:
    api: Any = object.__new__(NativeWindowsPrivateState)
    api.owner = "owner"
    acl = Acl(2, 0, 8, len(sids), 0)
    buffers = [
        ctypes.create_string_buffer(
            bytes([0, flags, 12, 0]) + (0x1F01FF).to_bytes(4, "little") + b"xxxx"
        )
        for _ in sids
    ]
    sid_by_pointer = {
        100: owner,
        **{ctypes.addressof(buf) + 8: sid for buf, sid in zip(buffers, sids, strict=True)},
    }
    api._sid_text = lambda sid: sid_by_pointer[sid.value]

    def get_info(
        _path: Any,
        _kind: Any,
        _parts: Any,
        owner_ptr: Any,
        _group: Any,
        dacl_ptr: Any,
        _sacl: Any,
        descriptor_ptr: Any,
    ) -> int:
        owner_ptr._obj.value = 100
        dacl_ptr._obj.value = ctypes.addressof(acl)
        descriptor_ptr._obj.value = 500
        return 0

    def get_control(_descriptor: Any, control: Any, _revision: Any) -> bool:
        control._obj.value = 0x1000 if protected else 0
        return True

    def get_ace(_acl: Any, index: int, output: Any) -> bool:
        output._obj.value = ctypes.addressof(buffers[index])
        return True

    api.advapi = SimpleNamespace(
        GetNamedSecurityInfoW=get_info, GetSecurityDescriptorControl=get_control, GetAce=get_ace
    )
    api.kernel = SimpleNamespace(LocalFree=lambda _pointer: None)
    return cast(NativeWindowsPrivateState, api)


def test_only_protected_owner_and_system_full_access_is_accepted() -> None:
    native_acl()._check_acl(Path("synthetic"))


@pytest.mark.parametrize(
    "changes",
    [
        {"sids": ("owner", "Everyone")},
        {"sids": ()},
        {"sids": ("owner",)},
        {"sids": ("owner", "S-1-5-18", "owner")},
        {"owner": "different-owner"},
        {"flags": 0x10},
        {"protected": False},
    ],
)
def test_broad_inherited_missing_or_wrong_owner_acl_is_denied(changes: dict[str, Any]) -> None:
    with pytest.raises(OSError, match="native_private_state_denied"):
        native_acl(**changes)._check_acl(Path("synthetic"))


def acl_setter(
    *, owner_matches: bool = True, result: int = 0
) -> tuple[NativeWindowsPrivateState, list[tuple[int, Any, Any, Any]]]:
    api: Any = object.__new__(NativeWindowsPrivateState)
    api.owner = "synthetic-owner"
    api._sid_text = lambda _sid: api.owner if owner_matches else "synthetic-other"
    calls: list[tuple[int, Any, Any, Any]] = []

    def get_owner(
        _path: Any,
        _kind: Any,
        parts: int,
        owner: Any,
        _group: Any,
        _dacl: Any,
        _sacl: Any,
        descriptor: Any,
    ) -> int:
        assert parts == 1
        owner._obj.value = 100
        descriptor._obj.value = 600
        return 0

    def convert(_sddl: Any, _revision: Any, descriptor: Any, _size: Any) -> bool:
        descriptor._obj.value = 500
        return True

    def descriptor_owner(_descriptor: Any, owner: Any, _default: Any) -> bool:
        owner._obj.value = 100
        return True

    def descriptor_dacl(_descriptor: Any, present: Any, dacl: Any, _default: Any) -> bool:
        present._obj.value = 1
        dacl._obj.value = 300
        return True

    def set_info(
        path: Any, kind: Any, parts: int, owner: Any, group: Any, dacl: Any, sacl: Any
    ) -> int:
        calls.append((parts, owner, group, sacl))
        return 5 if parts & 1 else result  # Owner has WRITE_DAC, not WRITE_OWNER.

    api.advapi = SimpleNamespace(
        GetNamedSecurityInfoW=get_owner,
        ConvertStringSecurityDescriptorToSecurityDescriptorW=convert,
        GetSecurityDescriptorOwner=descriptor_owner,
        GetSecurityDescriptorDacl=descriptor_dacl,
        SetNamedSecurityInfoW=set_info,
    )
    api.kernel = SimpleNamespace(LocalFree=lambda _pointer: None)
    return cast(NativeWindowsPrivateState, api), calls


def test_hardening_existing_current_owner_never_requests_write_owner() -> None:
    api, calls = acl_setter()
    api._set_acl(Path("synthetic"))
    assert calls == [(0x80000004, None, None, None)]


def test_hardening_foreign_owner_does_not_attempt_acl_or_ownership_change() -> None:
    api, calls = acl_setter(owner_matches=False)
    with pytest.raises(NativePrivateStateError) as error:
        api._set_acl(Path("synthetic"))
    assert calls == []
    assert error.value.reason_code == "owner_mismatch"


def test_acl_api_failure_keeps_direct_win32_code_and_sanitized_reason() -> None:
    api, _ = acl_setter(result=5)
    with pytest.raises(NativePrivateStateError) as error:
        api._set_acl(Path("synthetic"))
    assert str(error.value) == "native_private_state_denied"
    assert error.value.reason_code == "dacl_set_failed"
    assert error.value.native_error_code == 5


def test_unprotected_acl_has_fixed_reason_without_stale_last_error() -> None:
    with pytest.raises(NativePrivateStateError) as error:
        native_acl(protected=False)._check_acl(Path("synthetic"))
    assert error.value.reason_code == "dacl_not_protected"
    assert error.value.native_error_code is None


def test_owner_query_failure_never_attempts_dacl_change() -> None:
    api, calls = acl_setter()
    cast(Any, api.advapi).GetNamedSecurityInfoW = lambda *_args: 5
    with pytest.raises(NativePrivateStateError) as error:
        api._set_acl(Path("synthetic"))
    assert calls == []
    assert error.value.reason_code == "owner_query_failed"
    assert error.value.native_error_code == 5


def test_owner_change_after_dacl_call_is_denied_without_taking_ownership() -> None:
    api, calls = acl_setter()
    original = cast(Any, api.advapi).SetNamedSecurityInfoW

    def change_owner(*args: Any) -> int:
        result = original(*args)
        cast(Any, api)._sid_text = lambda _sid: "synthetic-other"
        return int(result)

    cast(Any, api.advapi).SetNamedSecurityInfoW = change_owner
    with pytest.raises(NativePrivateStateError) as error:
        api._set_acl(Path("synthetic"))
    assert error.value.reason_code == "owner_mismatch"
    assert calls == [(0x80000004, None, None, None)]


def capture_adapter(tmp_path: Path) -> tuple[NativeWindowsPrivateState, SimpleNamespace]:
    """Actual adapter with external Win32 ACL, DPAPI and rename boundaries only."""
    api = native_acl()
    external = cast(Any, api)
    # Keep the owned test root below Win32 MAX_PATH including the capture suffix.
    api.root = tmp_path.parent / f"c-{uuid4().hex[:8]}"
    api.root.mkdir()
    api.private = api.root / ".local-data/access-epoch/private"
    state = SimpleNamespace(
        buffers=[], renamed=[], race=None, decrypt_failure=False, encrypted=None, decrypted=None
    )
    acl = Acl(2, 0, 8, 2, 0)
    existing = external.advapi.GetNamedSecurityInfoW

    def info(
        path: Any,
        kind: Any,
        parts: Any,
        owner: Any,
        group: Any,
        dacl: Any,
        sacl: Any,
        descriptor: Any,
    ) -> int:
        if dacl is not None:
            return int(existing(path, kind, parts, owner, group, dacl, sacl, descriptor))
        owner._obj.value = 100
        descriptor._obj.value = 500
        return 0

    def convert(sddl: Any, revision: Any, descriptor: Any, size: Any) -> bool:
        descriptor._obj.value = 500
        return True

    def descriptor_dacl(descriptor: Any, present: Any, dacl: Any, default: Any) -> bool:
        present._obj.value = 1
        dacl._obj.value = ctypes.addressof(acl)
        return True

    def transform(
        incoming: Any,
        description: Any,
        entropy: Any,
        reserved: Any,
        prompt: Any,
        flags: Any,
        outgoing: Any,
        *,
        decrypt: bool,
    ) -> bool:
        assert flags == 1 and entropy is None  # CurrentUser/UI-forbidden DPAPI boundary.
        value = ctypes.string_at(incoming._obj.data, incoming._obj.length)
        if decrypt:
            if state.decrypt_failure or not value.startswith(b"sealed:"):
                return False
            value = bytes(byte ^ 0xA5 for byte in value[7:])
            if state.decrypted is not None:
                value = state.decrypted
        else:
            value = b"sealed:" + bytes(byte ^ 0xA5 for byte in value)
            if state.encrypted is not None:
                value = state.encrypted
        buffer = ctypes.create_string_buffer(value)
        state.buffers.append(buffer)
        outgoing._obj.length = len(value)
        outgoing._obj.data = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        return True

    def rename(source: str, target: str, flags: int) -> bool:
        assert flags == 8  # Write-through, no replacement flag.
        state.renamed.append((source, target))
        if state.race is not None:
            state.race(Path(target))
        try:
            os.rename(source, target)
        except OSError:
            ctypes.set_last_error(183)
            return False
        return True

    external.advapi.GetNamedSecurityInfoW = info
    external.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW = convert
    external.advapi.GetSecurityDescriptorDacl = descriptor_dacl
    external.advapi.SetNamedSecurityInfoW = lambda *args: 0
    external.crypt = SimpleNamespace(
        CryptProtectData=lambda *args: transform(*args, decrypt=False),
        CryptUnprotectData=lambda *args: transform(*args, decrypt=True),
    )
    external.kernel.MoveFileExW = rename
    return api, state


def test_capture_is_encrypted_create_once_and_selector_bound(tmp_path: Path) -> None:
    api, _ = capture_adapter(tmp_path)
    nonce = UUID(int=123)
    data = b"synthetic private observation"
    api.create_read_capture(nonce, 2, "capture", data)
    path = api.private / "read-checks/00000000-0000-0000-0000-00000000007b/2-capture.dpapi"
    assert path.is_file() and data not in path.read_bytes()
    assert api.read_read_capture(nonce, 2, "capture") == data
    assert api.read_read_capture(nonce, 2, "terminal") is None
    for replacement in (data, b"different"):
        before = path.read_bytes()
        with pytest.raises(OSError, match="^native_private_state_denied$"):
            api.create_read_capture(nonce, 2, "capture", replacement)
        assert path.read_bytes() == before
    other = api.private / "read-checks/00000000-0000-0000-0000-00000000007c/2-capture.dpapi"
    other.parent.mkdir()
    other.write_bytes(path.read_bytes())
    with pytest.raises(OSError, match="^native_private_state_denied$"):
        api.read_read_capture(UUID(int=124), 2, "capture")


@pytest.mark.parametrize(
    "changes",
    [
        (UUID(int=0), 0, "intent", b"x"),
        ("invalid", 0, "intent", b"x"),
        (UUID(int=1), True, "intent", b"x"),
        (UUID(int=1), -1, "intent", b"x"),
        (UUID(int=1), 5, "intent", b"x"),
        (UUID(int=1), 0, "unknown", b"x"),
        (UUID(int=1), 0, "intent", bytearray(b"x")),
        (UUID(int=1), 0, "intent", b""),
        (UUID(int=1), 0, "intent", b"x" * 4_194_305),
    ],
)
def test_capture_invalid_inputs_never_persist(tmp_path: Path, changes: tuple[Any, ...]) -> None:
    api, _ = capture_adapter(tmp_path)
    with pytest.raises(OSError, match="^native_private_state_denied$"):
        api.create_read_capture(*changes)
    assert not api.private.exists()


def test_capture_destination_race_never_overwrites_or_removes_winner(tmp_path: Path) -> None:
    api, state = capture_adapter(tmp_path)
    state.race = lambda path: path.write_bytes(b"other recorded ciphertext")
    with pytest.raises(OSError, match="^native_private_state_denied$"):
        api.create_read_capture(UUID(int=1), 0, "intent", b"new")
    destination = api.private / "read-checks/00000000-0000-0000-0000-000000000001/0-intent.dpapi"
    assert destination.read_bytes() == b"other recorded ciphertext"
    assert list(destination.parent.glob("*.pending")) == []


def test_capture_cancel_during_flush_preserves_primary_and_cleans_owned_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, _ = capture_adapter(tmp_path)

    def cancel(fd: int) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(os, "fsync", cancel)
    with pytest.raises(asyncio.CancelledError):
        api.create_read_capture(UUID(int=1), 0, "intent", b"synthetic")
    assert list(api.private.rglob("*.dpapi")) == []
    assert list(api.private.rglob("*.pending")) == []


@pytest.mark.parametrize(
    "phase", ["intent", "child", "resume_intent", "terminal", "capture", "cleanup"]
)
def test_capture_each_closed_phase_and_slot_is_isolated(tmp_path: Path, phase: Any) -> None:
    api, _ = capture_adapter(tmp_path)
    for slot in (0, 4):
        api.create_read_capture(UUID(int=1), slot, phase, b"phase observation")
        assert api.read_read_capture(UUID(int=1), slot, phase) == b"phase observation"


def test_capture_plaintext_and_ciphertext_limits_are_checked_before_disk(tmp_path: Path) -> None:
    api, state = capture_adapter(tmp_path)
    data = b"x" * (4_194_304 - 32)
    api.create_read_capture(UUID(int=1), 0, "capture", data)
    assert api.read_read_capture(UUID(int=1), 0, "capture") == data
    state.encrypted = b"x" * (4_194_304 + 65_537)
    with pytest.raises(OSError):
        api.create_read_capture(UUID(int=2), 0, "capture", b"synthetic")
    assert not (api.private / "read-checks" / str(UUID(int=2))).exists()


def test_capture_corrupt_decrypted_envelope_never_returns_a_partial_record(tmp_path: Path) -> None:
    api, state = capture_adapter(tmp_path)
    api.create_read_capture(UUID(int=1), 0, "capture", b"synthetic")
    for malformed in (b"x", b"x" * 4_194_305, b"AIWRREAD01" + b"\0" * 64):
        state.decrypted = malformed
        with pytest.raises(OSError):
            api.read_read_capture(UUID(int=1), 0, "capture")


def test_capture_missing_path_under_unprotected_parent_is_denied(tmp_path: Path) -> None:
    api, _ = capture_adapter(tmp_path)
    api.create_read_capture(UUID(int=1), 0, "intent", b"synthetic")
    cast(Any, api.advapi).GetSecurityDescriptorControl = lambda descriptor, control, revision: True
    with pytest.raises(OSError):
        api.read_read_capture(UUID(int=1), 1, "capture")


def test_capture_published_record_is_preserved_after_ack_loss(tmp_path: Path) -> None:
    api, _ = capture_adapter(tmp_path)
    original = cast(Any, api.kernel).MoveFileExW

    def lost_ack(source: str, target: str, flags: int) -> bool:
        assert original(source, target, flags)
        raise asyncio.CancelledError

    cast(Any, api.kernel).MoveFileExW = lost_ack
    with pytest.raises(asyncio.CancelledError):
        api.create_read_capture(UUID(int=1), 0, "capture", b"synthetic")
    assert api.read_read_capture(UUID(int=1), 0, "capture") == b"synthetic"
    with pytest.raises(OSError):
        api.create_read_capture(UUID(int=1), 0, "capture", b"synthetic")
    assert list(api.private.rglob("*.pending")) == []


def test_capture_primary_cancel_survives_cleanup_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, _ = capture_adapter(tmp_path)
    original = Path.unlink

    def cancel(fd: int) -> None:
        raise asyncio.CancelledError

    def failed_cleanup(path: Path, missing_ok: bool = False) -> None:
        if path.suffix == ".pending":
            raise OSError("synthetic cleanup failure")
        original(path, missing_ok=missing_ok)

    monkeypatch.setattr(os, "fsync", cancel)
    monkeypatch.setattr(Path, "unlink", failed_cleanup)
    with pytest.raises(asyncio.CancelledError) as caught:
        api.create_read_capture(UUID(int=1), 0, "capture", b"synthetic")
    assert caught.value.__notes__ == ["read_capture_temporary_cleanup_unverified"]
    assert list(api.private.rglob("*.dpapi")) == []


def test_capture_replaced_owned_temp_is_not_deleted_on_failure(tmp_path: Path) -> None:
    api, _ = capture_adapter(tmp_path)

    def replace_then_cancel(source: str, target: str, flags: int) -> bool:
        path = Path(source)
        path.rename(path.with_suffix(".saved"))
        path.write_bytes(b"another resource")
        raise asyncio.CancelledError

    cast(Any, api.kernel).MoveFileExW = replace_then_cancel
    with pytest.raises(asyncio.CancelledError):
        api.create_read_capture(UUID(int=1), 0, "capture", b"synthetic")
    assert next(api.private.rglob("*.pending")).read_bytes() == b"another resource"


def test_capture_same_bytes_source_replacement_before_move_is_not_an_owned_publication(
    tmp_path: Path,
) -> None:
    api, _ = capture_adapter(tmp_path)

    def replace_then_move(source: str, target: str, flags: int) -> bool:
        path = Path(source)
        data = path.read_bytes()
        path.rename(path.with_suffix(".saved"))
        path.write_bytes(data)
        os.rename(path, target)
        return True

    cast(Any, api.kernel).MoveFileExW = replace_then_move
    with pytest.raises(OSError):
        api.create_read_capture(UUID(int=1), 0, "capture", b"synthetic")
    assert len(list(api.private.rglob("*.dpapi"))) == 1  # Never delete a published file.


def test_capture_read_rejects_a_directory_record_and_oversize_ciphertext(tmp_path: Path) -> None:
    api, _ = capture_adapter(tmp_path)
    api.create_read_capture(UUID(int=1), 0, "capture", b"synthetic")
    record = api.private / "read-checks" / str(UUID(int=1)) / "0-capture.dpapi"
    record.write_bytes(b"x" * (4_194_304 + 65_537))
    with pytest.raises(OSError):
        api.read_read_capture(UUID(int=1), 0, "capture")
    record.unlink()
    record.mkdir()
    with pytest.raises(OSError):
        api.read_read_capture(UUID(int=1), 0, "capture")


def test_capture_reparse_parent_is_denied_before_decryption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, state = capture_adapter(tmp_path)
    api.create_read_capture(UUID(int=1), 0, "capture", b"synthetic")
    original = Path.stat
    parent = api.private / "read-checks"

    def changed(path: Path, *, follow_symlinks: bool = True) -> Any:
        value = original(path, follow_symlinks=follow_symlinks)
        if path == parent:
            return SimpleNamespace(st_file_attributes=value.st_file_attributes | 0x400)
        return value

    monkeypatch.setattr(Path, "stat", changed)
    before = len(state.buffers)
    with pytest.raises(OSError):
        api.read_read_capture(UUID(int=1), 0, "capture")
    assert len(state.buffers) == before


def test_capture_acl_drift_during_decryption_denies_publication(tmp_path: Path) -> None:
    api, _ = capture_adapter(tmp_path)
    api.create_read_capture(UUID(int=1), 0, "capture", b"synthetic")
    external = cast(Any, api)
    original = external.crypt.CryptUnprotectData

    def decrypt_then_drift(*args: Any) -> bool:
        result = original(*args)
        external.advapi.GetSecurityDescriptorControl = lambda descriptor, control, revision: True
        return bool(result)

    external.crypt.CryptUnprotectData = decrypt_then_drift
    with pytest.raises(NativePrivateStateError) as caught:
        api.read_read_capture(UUID(int=1), 0, "capture")
    assert caught.value.reason_code == "dacl_not_protected"
