"""Exact UUID primitive seals required by the native control source graph."""

from uuid import UUID

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_control_native import _freeze


class _IntegerSubclass(int):
    pass


@pytest.mark.parametrize(
    "changed",
    [_IntegerSubclass(1), True, -1, 2**128],
    ids=["same-value-int-subclass", "boolean-one", "negative", "overflow"],
)
def test_native_control_uuid_internal_integer_must_be_exact_and_in_range(
    changed: object,
) -> None:
    value = UUID(int=1)
    original = value.int
    baseline = _freeze(value)
    try:
        object.__setattr__(value, "int", changed)
        with pytest.raises(ValueError, match="^native_control_denied$"):
            _freeze(value)
    finally:
        object.__setattr__(value, "int", original)
    assert _freeze(value) == baseline
