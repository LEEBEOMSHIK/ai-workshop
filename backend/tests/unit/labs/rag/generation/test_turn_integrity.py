from uuid import uuid4

from ai_workshop.labs.rag.generation.domain import ConversationRole, ConversationTurn
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner


def test_assistant_turn_signature_is_bound_to_text_actor_turn_and_configuration() -> None:
    signer = ConversationTurnSigner(b"a" * 32)
    actor_id = uuid4()
    configuration_version_id = uuid4()
    turn_id = uuid4()
    content = "검증된 이전 답변"
    token = signer.sign(
        content=content,
        actor_id=actor_id,
        turn_id=turn_id,
        configuration_version_id=configuration_version_id,
    )
    turn = ConversationTurn(
        role=ConversationRole.ASSISTANT,
        content=content,
        turn_id=turn_id,
        validation_token=token,
    )

    assert signer.verify(
        turn,
        actor_id=actor_id,
        configuration_version_id=configuration_version_id,
    )
    assert not signer.verify(
        turn,
        actor_id=uuid4(),
        configuration_version_id=configuration_version_id,
    )
    assert not signer.verify(
        turn,
        actor_id=actor_id,
        configuration_version_id=uuid4(),
    )
    assert not signer.verify(
        ConversationTurn(
            role=ConversationRole.ASSISTANT,
            content="변조된 답변",
            turn_id=turn_id,
            validation_token=token,
        ),
        actor_id=actor_id,
        configuration_version_id=configuration_version_id,
    )


def test_user_turn_is_not_accepted_as_server_validated_assistant_turn() -> None:
    signer = ConversationTurnSigner(b"b" * 32)

    assert not signer.verify(
        ConversationTurn(role=ConversationRole.USER, content="사용자 질문"),
        actor_id=uuid4(),
        configuration_version_id=uuid4(),
    )
