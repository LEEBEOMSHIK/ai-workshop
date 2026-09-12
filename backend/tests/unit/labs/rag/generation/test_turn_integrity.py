from uuid import UUID, uuid4

from ai_workshop.labs.rag.generation.domain import ConversationRole, ConversationTurn
from ai_workshop.labs.rag.generation.integrity import (
    ConversationScopeBinding,
    ConversationTurnSigner,
)


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


def test_scoped_signature_changes_with_selected_documents_and_lifecycle() -> None:
    signer = ConversationTurnSigner(b"c" * 32)
    domain_id = uuid4()
    connection_version_id = uuid4()
    workspace_id = uuid4()
    document_a = uuid4()
    document_b = uuid4()
    selected_a = ConversationScopeBinding(
        domain_id=domain_id,
        connection_version_id=connection_version_id,
        workspace_ids=(workspace_id,),
        folder_ids=(),
        document_ids=(document_a,),
        scope_fingerprint="a" * 64,
    )
    selected_b = ConversationScopeBinding(
        domain_id=domain_id,
        connection_version_id=connection_version_id,
        workspace_ids=(workspace_id,),
        folder_ids=(),
        document_ids=(document_b,),
        scope_fingerprint="a" * 64,
    )
    selected_a_new_version = ConversationScopeBinding(
        domain_id=domain_id,
        connection_version_id=connection_version_id,
        workspace_ids=(workspace_id,),
        folder_ids=(),
        document_ids=(document_a,),
        scope_fingerprint="b" * 64,
    )
    content = "선택 범위에 결합된 답변"
    actor_id = uuid4()
    turn_id = uuid4()
    configuration_version_id = uuid4()

    def sign(scope: ConversationScopeBinding) -> str:
        return signer.sign_scoped(
            content=content,
            actor_id=actor_id,
            turn_id=turn_id,
            configuration_version_id=configuration_version_id,
            scope=scope,
        )

    selected_a_token = sign(selected_a)

    assert selected_a_token.startswith("v3.selected_documents.")
    assert selected_a_token != sign(selected_b)
    assert selected_a_token != sign(selected_a_new_version)


def test_selected_scope_binding_normalizes_document_ids() -> None:
    first = UUID("10000000-0000-0000-0000-000000000001")
    second = UUID("20000000-0000-0000-0000-000000000001")

    scope = ConversationScopeBinding(
        domain_id=uuid4(),
        connection_version_id=uuid4(),
        workspace_ids=(uuid4(),),
        folder_ids=(),
        document_ids=(second, first, second),
        scope_fingerprint="a" * 64,
    )

    assert scope.document_ids == (first, second)
