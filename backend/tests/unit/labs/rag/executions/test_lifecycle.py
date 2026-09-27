from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.executions.domain import (
    ExecutionIdentity,
    StageObservation,
    terminal_transition,
)


def test_terminal_state_cannot_reverse():
    assert terminal_transition("cancelled", "completed") == "cancelled"
    assert terminal_transition("failed", "completed") == "failed"
    assert terminal_transition("running", "completed") == "completed"


def test_correlation_is_not_identity():
    actor = uuid4()
    a = ExecutionIdentity(actor_id=actor, turn_id=uuid4())
    b = ExecutionIdentity(actor_id=actor, turn_id=uuid4())
    assert a.execution_id != b.execution_id
    with pytest.raises(ValidationError):
        ExecutionIdentity(actor_id=actor)
    with pytest.raises(ValidationError):
        ExecutionIdentity(actor_id=actor, turn_id=uuid4(), evaluation_attempt_id=uuid4())


@pytest.mark.parametrize("duration", [-1, float("inf"), float("nan")])
def test_rejects_nonfinite_or_negative_duration(duration):
    with pytest.raises(ValidationError):
        StageObservation(stage="retrieval", state="completed", duration_ms=duration)


def test_missing_duration_is_not_zero():
    assert StageObservation(stage="retrieval", state="unrecorded").duration_ms is None
