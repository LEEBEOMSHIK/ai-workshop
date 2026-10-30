"""Final policy selection metadata; identities enter only from server conversation scope."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_workshop.labs.rag.generation.domain import ContextPolicy, ConversationTurn


class HistoryMessageObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    position: int = Field(ge=0, lt=20, strict=True)
    conversation_turn_id: UUID | None = None
    role: Literal["user", "assistant"]
    selected: bool
    reason: Literal["selected", "message_limit", "token_limit", "older_than_token_limit"]


class HistorySelectionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_history_messages: int = Field(gt=0, strict=True)
    max_history_tokens: int = Field(gt=0, strict=True)
    input_message_count: int = Field(ge=0, le=20, strict=True)
    selected_message_count: int = Field(ge=0, le=20, strict=True)
    messages: tuple[HistoryMessageObservation, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def consistent_selection(self) -> Self:
        if self.input_message_count != len(self.messages):
            raise ValueError("History input count is inconsistent")
        start = self.input_message_count - self.selected_message_count
        window = max(0, self.input_message_count - self.max_history_messages)
        if start < window:
            raise ValueError("Selected history exceeds message limit")
        for index, message in enumerate(self.messages):
            expected = (
                "selected" if index >= start else "message_limit" if index < window
                else "token_limit" if index == start - 1 else "older_than_token_limit"
            )
            if (message.position != index or message.selected != (index >= start)
                    or message.reason != expected):
                raise ValueError("History selection order is inconsistent")
        return self


_provenance: ContextVar[tuple[UUID, ...] | None] = ContextVar(
    "rag_history_provenance", default=None,
)


@contextmanager
def bind_history_provenance(dependencies: tuple[UUID, ...]) -> Iterator[None]:
    token = _provenance.set(dependencies)
    try:
        yield
    finally:
        _provenance.reset(token)


def history_selection(
    history: tuple[ConversationTurn, ...], selected: tuple[ConversationTurn, ...],
    policy: ContextPolicy,
) -> HistorySelectionObservation:
    # ContextPolicy returns the exact suffix objects. No text matching/token recounting.
    start = len(history) - len(selected)
    if start < 0 or any(a is not b for a, b in zip(history[start:], selected, strict=True)):
        raise ValueError("Policy selection is not the original history suffix")
    dependencies = _provenance.get()
    mapped = dependencies is not None and len(history) == 2 * len(dependencies) and all(
        turn.role.value == ("user" if index % 2 == 0 else "assistant")
        for index, turn in enumerate(history)
    )
    window = max(0, len(history) - policy.max_history_turns)
    return HistorySelectionObservation(
        max_history_messages=policy.max_history_turns, max_history_tokens=policy.max_history_tokens,
        input_message_count=len(history), selected_message_count=len(selected),
        messages=tuple(HistoryMessageObservation(
            position=index,
            conversation_turn_id=dependencies[index // 2] if mapped and dependencies else None,
            role=turn.role.value, selected=index >= start,
            reason=("selected" if index >= start else "message_limit" if index < window
                    else "token_limit" if index == start - 1 else "older_than_token_limit"),
        ) for index, turn in enumerate(history)),
    )


def validate_history_binding(
    selection: HistorySelectionObservation | None, dependencies: tuple[UUID, ...],
) -> None:
    if selection is None or not any(m.conversation_turn_id for m in selection.messages):
        return
    if len(selection.messages) != 2 * len(dependencies) or any(
        message.conversation_turn_id != dependencies[index // 2]
        or message.role != ("user" if index % 2 == 0 else "assistant")
        for index, message in enumerate(selection.messages)
    ):
        raise ValueError("History identities differ from execution dependencies")
