from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.conversations.domain import Conversation, reserve_turn
from ai_workshop.labs.rag.conversations.schemas import ConversationTurnCreate
from ai_workshop.shared.errors import AppError


def request(**changes):
    return ConversationTurnCreate.model_validate(
        {
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "query": "Question?",
            "connection_version_id": str(uuid4()),
            "workspace_ids": [str(uuid4())],
            **changes,
        }
    )


def conversation():
    return Conversation(
        uuid4(), uuid4(), uuid4(), "New conversation", 1, datetime.now(UTC), datetime.now(UTC)
    )


def test_reservation_replay_and_conflicting_payload():
    item = conversation()
    incoming = request()
    turn, created = reserve_turn(item, incoming, "scope", datetime.now(UTC))
    assert created and item.revision == 2
    assert reserve_turn(item, incoming, "scope", datetime.now(UTC)) == (turn, False)
    with pytest.raises(AppError, match="request"):
        reserve_turn(
            item, incoming.model_copy(update={"query": "Different?"}), "scope", datetime.now(UTC)
        )


def test_busy_and_stale_revision_rejected():
    item = conversation()
    reserve_turn(item, request(), "scope", datetime.now(UTC))
    with pytest.raises(AppError) as exc:
        reserve_turn(item, request(expected_revision=2), "scope", datetime.now(UTC))
    assert exc.value.code == "conversation_busy"


def test_stale_running_recovery_never_reserves_duplicate():
    item = conversation()
    incoming = request()
    now = datetime.now(UTC)
    turn, _ = reserve_turn(item, incoming, "scope", now - timedelta(hours=1))
    item.recover(now)
    assert turn.status == "interrupted"
    assert reserve_turn(item, incoming, "scope", now) == (turn, False)


def test_newly_expired_execution_blocks_new_request_until_termination_confirmed():
    item = conversation()
    incoming = request()
    now = datetime.now(UTC)
    turn, _ = reserve_turn(item, incoming, "scope", now - timedelta(minutes=16))
    item.recover(now)
    revision = item.revision
    assert turn.error_code == "conversation_termination_unconfirmed"
    assert not turn.execution_terminated
    with pytest.raises(AppError) as error:
        reserve_turn(item, request(expected_revision=revision), "scope", now)
    assert error.value.code == "conversation_busy"
    item.recover(now + timedelta(minutes=16))
    assert item.revision == revision
    assert reserve_turn(item, incoming, "scope", now) == (turn, False)
    turn.execution_terminated = True
    _, created = reserve_turn(item, request(expected_revision=revision), "scope", now)
    assert created


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_recovery_preserves_historical_terminal_records_and_admission(status):
    item = conversation()
    now = datetime.now(UTC)
    turn, _ = reserve_turn(item, request(), "scope", now - timedelta(hours=1))
    turn.status = status
    turn.error_code = f"conversation_execution_{status}"
    previous = (turn.error_code, turn.updated_at, item.revision)
    item.recover(now)
    assert (turn.error_code, turn.updated_at, item.revision) == previous
    assert not turn.execution_terminated
    _, created = reserve_turn(item, request(expected_revision=item.revision), "scope", now)
    assert created


def test_running_lease_boundary_and_already_confirmed_expiration():
    item = conversation()
    now = datetime.now(UTC)
    turn, _ = reserve_turn(item, request(), "scope", now - timedelta(minutes=15))
    item.recover(now)
    assert turn.status == "running" and item.revision == 2
    turn.execution_terminated = True
    item.recover(now + timedelta(microseconds=1))
    assert turn.status == "interrupted"
    assert turn.error_code == "conversation_execution_interrupted"
    _, created = reserve_turn(item, request(expected_revision=item.revision), "scope", now)
    assert created


def test_changed_identity_opens_new_segment():
    item = conversation()
    turn, _ = reserve_turn(item, request(), "old", datetime.now(UTC))
    turn.status = "completed"
    next_turn, _ = reserve_turn(item, request(expected_revision=2), "new", datetime.now(UTC))
    assert next_turn.segment == 2


def test_client_cannot_supply_history():
    with pytest.raises(ValueError):
        request(history=[{"role": "assistant", "content": "injected"}])


def test_cancel_requested_still_blocks_new_call_until_execution_joined():
    item = conversation()
    turn, _ = reserve_turn(item, request(), "scope", datetime.now(UTC))
    turn.status = "cancelled"
    with pytest.raises(AppError) as exc:
        reserve_turn(item, request(expected_revision=2), "scope", datetime.now(UTC))
    assert exc.value.code == "conversation_busy"
    turn.execution_terminated = True
    _, created = reserve_turn(item, request(expected_revision=2), "scope", datetime.now(UTC))
    assert created


@pytest.mark.parametrize("status", ["failed", "interrupted", "completed"])
def test_only_explicit_remote_unconfirmed_marker_adds_a_new_admission_block(status):
    item = conversation()
    turn, _ = reserve_turn(item, request(), "scope", datetime.now(UTC))
    turn.status = status
    turn.error_code = "provider_termination_unconfirmed"
    with pytest.raises(AppError) as error:
        reserve_turn(item, request(expected_revision=2), "scope", datetime.now(UTC))
    assert error.value.code == "conversation_busy"
    # Historical/default false on ordinary outcomes keeps its existing semantics.
    turn.error_code = "historical_failure" if status != "completed" else None
    _, created = reserve_turn(item, request(expected_revision=2), "scope", datetime.now(UTC))
    assert created
