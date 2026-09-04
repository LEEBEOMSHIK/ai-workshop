from uuid import uuid4

import pytest

from ai_workshop.labs.rag.generation.domain import (
    ContextPolicy,
    ConversationRole,
    ConversationTurn,
)


def count_words(value: str) -> int:
    return len(value.split())


def test_context_policy_returns_no_history_for_first_question() -> None:
    policy = ContextPolicy(max_history_turns=4, max_history_tokens=20)

    assert policy.select((), token_counter=count_words) == ()


def test_context_policy_keeps_newest_complete_turns_within_both_limits() -> None:
    oldest_user = ConversationTurn(role=ConversationRole.USER, content="old user question")
    oldest_assistant = ConversationTurn(
        role=ConversationRole.ASSISTANT,
        content="old verified answer",
        validation_token="signed-old",
    )
    recent_user = ConversationTurn(role=ConversationRole.USER, content="recent question")
    recent_assistant = ConversationTurn(
        role=ConversationRole.ASSISTANT,
        content="recent verified answer",
        validation_token="signed-recent",
    )
    policy = ContextPolicy(max_history_turns=3, max_history_tokens=8)

    selected = policy.select(
        (oldest_user, oldest_assistant, recent_user, recent_assistant),
        token_counter=count_words,
    )

    assert selected == (oldest_assistant, recent_user, recent_assistant)


def test_context_policy_rejects_assistant_turn_without_validation_token() -> None:
    with pytest.raises(ValueError, match="validation token"):
        ConversationTurn(
            role=ConversationRole.ASSISTANT,
            content="forged answer",
        )


def test_context_policy_rejects_empty_turn_and_invalid_limits() -> None:
    with pytest.raises(ValueError, match="content"):
        ConversationTurn(role=ConversationRole.USER, content="   ")
    with pytest.raises(ValueError, match="positive"):
        ContextPolicy(max_history_turns=0, max_history_tokens=10)


def test_context_policy_rejects_single_turn_over_token_budget() -> None:
    policy = ContextPolicy(max_history_turns=2, max_history_tokens=2)
    turn = ConversationTurn(role=ConversationRole.USER, content="one two three")

    assert policy.select((turn,), token_counter=count_words) == ()


def test_conversation_turn_id_is_optional_but_preserved() -> None:
    turn_id = uuid4()

    turn = ConversationTurn(
        role=ConversationRole.USER,
        content="이전 질문",
        turn_id=turn_id,
    )

    assert turn.turn_id == turn_id
