"""Fast adversarial memory seals, with real native classes and fake WinDLL only."""

import ctypes
from types import SimpleNamespace
from uuid import UUID

import pytest

from ai_workshop.infrastructure.local.control_process_windows import (
    NativeWindowsProcess,
    WindowsControlProcess,
)
from ai_workshop.labs.rag.indexing.access_epoch_fresh_secured_read import _process_signature
from ai_workshop.labs.rag.indexing.access_epoch_secured_read import _freeze
from tests.unit.infrastructure.local.test_control_process_windows import Win32
from tests.unit.labs.rag.indexing.test_access_epoch_secured_read_assembly import Function


class IntegerSubtype(int):
    pass


@pytest.fixture
def native(monkeypatch):
    kernel = Win32()

    def dll(name, **_options):
        assert name in {"kernel32", "advapi32"}
        library = SimpleNamespace(_name=name, _handle=1 if name == "kernel32" else 2)
        for method, function in vars(kernel).items():
            if callable(function):
                setattr(library, method, Function(function))
        return library

    monkeypatch.setattr(ctypes, "WinDLL", dll)
    result = WindowsControlProcess(max_output_bytes=2097152, max_wait_ms=10000)
    assert _process_signature(result)
    assert not kernel.created and not kernel.open
    return result


@pytest.mark.parametrize("target", ["wait", "create"])
def test_native_instance_method_shadow_is_rejected_by_process_seal(native, target):
    # Deliberate ordinary instance attack, not a replacement of the product guard.
    if target == "wait":
        native.wait = lambda *_args: None
    else:
        native._native.create = lambda *_args: None
    with pytest.raises(ValueError):
        _process_signature(native)


@pytest.mark.parametrize(
    "replacement",
    [IntegerSubtype(1), True, -1, 1 << 128],
    ids=["int-subtype", "bool", "negative", "overflow"],
)
def test_uuid_internal_integer_must_be_exact_bounded_int(replacement):
    value = UUID(int=1)
    assert _freeze(value)
    object.__setattr__(value, "int", replacement)
    with pytest.raises(ValueError):
        _freeze(value)


@pytest.mark.parametrize("target", ["positional", "keyword"])
def test_native_constructor_mutable_defaults_are_part_of_process_seal(native, monkeypatch, target):
    assert _process_signature(native)
    if target == "positional":
        monkeypatch.setattr(WindowsControlProcess.__init__, "__defaults__", ("synthetic-shadow",))
    else:
        # Mutate the existing dictionary in place: retaining its reference is
        # insufficient. The seal must have kept an independent typed snapshot.
        monkeypatch.setitem(
            NativeWindowsProcess.__init__.__kwdefaults__, "kernel", "synthetic-shadow"
        )
    with pytest.raises(ValueError):
        _process_signature(native)
