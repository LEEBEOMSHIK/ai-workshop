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
