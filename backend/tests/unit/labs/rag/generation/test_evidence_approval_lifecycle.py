"""Generation CAS must prevent old approval authority from being revived."""

from importlib import import_module

import pytest


def test_reapproval_advances_generation_and_rejects_stale_state():
    try:
        lifecycle = import_module("ai_workshop.labs.rag.generation.evidence_approval_lifecycle")
    except ModuleNotFoundError:
        pytest.fail("Approval lifecycle is not implemented")
    assert lifecycle.next_generation(0, expected_generation=0) == 1
    assert lifecycle.next_generation(1, expected_generation=1) == 2
    assert lifecycle.next_generation(2, expected_generation=2) == 3
    with pytest.raises(lifecycle.ApprovalConflict):
        lifecycle.next_generation(3, expected_generation=1)


@pytest.mark.parametrize("value", [-1, True, 1.0, "1"])
def test_generation_is_a_nonnegative_strict_integer(value):
    try:
        lifecycle = import_module("ai_workshop.labs.rag.generation.evidence_approval_lifecycle")
    except ModuleNotFoundError:
        pytest.fail("Approval lifecycle is not implemented")
    with pytest.raises(lifecycle.ApprovalConflict):
        lifecycle.next_generation(value, expected_generation=value)
