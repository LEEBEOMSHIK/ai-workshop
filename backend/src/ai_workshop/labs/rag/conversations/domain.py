from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from ai_workshop.labs.rag.conversations.schemas import ConversationTurnCreate
from ai_workshop.shared.errors import AppError

TurnStatus = Literal["running", "completed", "failed", "cancelled", "interrupted"]
RUNNING_LEASE = timedelta(minutes=15)


@dataclass
class Turn:
    id: UUID
    request_id: UUID
    sequence: int
    status: TurnStatus
    query: str
    request: dict[str, object]
    request_digest: str
    scope_identity: str
    segment: int
    created_at: datetime
    updated_at: datetime
    response: dict[str, object] | None = None
    error_code: str | None = None
    dependencies: list[UUID] = field(default_factory=list)
    execution_terminated: bool = False


@dataclass
class Conversation:
    id: UUID
    owner_id: UUID
    domain_id: UUID
    title: str
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    turns: list[Turn] = field(default_factory=list)

    def touch(self, now: datetime) -> None:
        self.revision += 1
        self.updated_at = now

    def require_revision(self, revision: int) -> None:
        if self.revision != revision:
            raise AppError(
                "conversation_revision_conflict", "Conversation changed. Reload it.", 409
            )

    def recover(self, now: datetime) -> None:
        recovered = False
        for turn in self.turns:
            if turn.status == "running" and now - turn.updated_at > RUNNING_LEASE:
                turn.status = "interrupted"
                turn.error_code = "conversation_execution_interrupted"
                turn.updated_at = now
                recovered = True
        if recovered:
            self.touch(now)


def reserve_turn(
    conversation: Conversation,
    request: ConversationTurnCreate,
    identity: str,
    now: datetime,
) -> tuple[Turn, bool]:
    payload = request.model_dump(mode="json", exclude={"expected_revision", "request_id"})
    import json

    digest = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    for turn in conversation.turns:
        if turn.request_id == request.request_id:
            if turn.request_digest != digest:
                raise AppError(
                    "conversation_request_conflict", "The request ID is already used.", 409
                )
            return turn, False
    conversation.require_revision(request.expected_revision)
    if any(
        turn.status == "running" or (turn.status == "cancelled" and not turn.execution_terminated)
        for turn in conversation.turns
    ):
        raise AppError("conversation_busy", "A conversation request is already running.", 409)
    previous = conversation.turns[-1] if conversation.turns else None
    segment = (previous.segment + (previous.scope_identity != identity)) if previous else 1
    turn = Turn(
        uuid4(),
        request.request_id,
        len(conversation.turns) + 1,
        "running",
        request.query,
        payload,
        digest,
        identity,
        segment,
        now,
        now,
    )
    conversation.turns.append(turn)
    conversation.touch(now)
    return turn, True
