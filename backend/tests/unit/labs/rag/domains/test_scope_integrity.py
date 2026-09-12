from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.generation.domain import ConversationRole, ConversationTurn
from ai_workshop.labs.rag.generation.integrity import (
    ConversationScopeBinding,
    ConversationTurnSigner,
)
from ai_workshop.labs.rag.search.schemas import ConversationTurnRequest, SearchRequest
from ai_workshop.labs.rag.search.service import SearchApplicationService
from ai_workshop.shared.errors import AppError


def test_scoped_signature_rejects_other_domain_connection_folder_actor_and_legacy() -> None:
    signer = ConversationTurnSigner(b"d" * 32)
    actor_id = uuid4()
    configuration_version_id = uuid4()
    turn_id = uuid4()
    content = "범위에 결합된 답변"
    scope = ConversationScopeBinding(
        domain_id=uuid4(),
        connection_version_id=uuid4(),
        workspace_ids=(uuid4(), uuid4()),
        folder_ids=(uuid4(),),
    )
    token = signer.sign_scoped(
        content=content,
        actor_id=actor_id,
        turn_id=turn_id,
        configuration_version_id=configuration_version_id,
        scope=scope,
    )
    turn = ConversationTurn(
        role=ConversationRole.ASSISTANT,
        content=content,
        turn_id=turn_id,
        validation_token=token,
    )

    assert signer.verify_scoped(
        turn,
        actor_id=actor_id,
        configuration_version_id=configuration_version_id,
        scope=ConversationScopeBinding(
            domain_id=scope.domain_id,
            connection_version_id=scope.connection_version_id,
            workspace_ids=tuple(reversed(scope.workspace_ids)),
            folder_ids=scope.folder_ids,
        ),
    )
    assert not signer.verify_scoped(
        turn,
        actor_id=uuid4(),
        configuration_version_id=configuration_version_id,
        scope=scope,
    )
    assert not signer.verify_scoped(
        turn,
        actor_id=actor_id,
        configuration_version_id=uuid4(),
        scope=scope,
    )
    assert not signer.verify_scoped(
        turn,
        actor_id=actor_id,
        configuration_version_id=configuration_version_id,
        scope=ConversationScopeBinding(
            domain_id=uuid4(),
            connection_version_id=scope.connection_version_id,
            workspace_ids=scope.workspace_ids,
            folder_ids=scope.folder_ids,
        ),
    )
    assert not signer.verify_scoped(
        turn,
        actor_id=actor_id,
        configuration_version_id=configuration_version_id,
        scope=ConversationScopeBinding(
            domain_id=scope.domain_id,
            connection_version_id=uuid4(),
            workspace_ids=scope.workspace_ids,
            folder_ids=scope.folder_ids,
        ),
    )
    assert not signer.verify_scoped(
        turn,
        actor_id=actor_id,
        configuration_version_id=configuration_version_id,
        scope=ConversationScopeBinding(
            domain_id=scope.domain_id,
            connection_version_id=scope.connection_version_id,
            workspace_ids=scope.workspace_ids,
            folder_ids=(uuid4(),),
        ),
    )

    legacy_token = signer.sign(
        content=content,
        actor_id=actor_id,
        turn_id=turn_id,
        configuration_version_id=configuration_version_id,
    )
    assert not signer.verify_scoped(
        ConversationTurn(
            role=ConversationRole.ASSISTANT,
            content=content,
            turn_id=turn_id,
            validation_token=legacy_token,
        ),
        actor_id=actor_id,
        configuration_version_id=configuration_version_id,
        scope=scope,
    )


def test_search_history_uses_scoped_v3_token_and_rejects_unscoped_replay() -> None:
    signer = ConversationTurnSigner(b"e" * 32)
    actor_id = uuid4()
    configuration_version_id = uuid4()
    configuration_id = uuid4()
    turn_id = uuid4()
    content = "이전 답변"
    scope = ConversationScopeBinding(
        domain_id=uuid4(),
        connection_version_id=uuid4(),
        workspace_ids=(uuid4(),),
        folder_ids=(),
    )
    service = SearchApplicationService(
        configuration_resolver=object(),  # type: ignore[arg-type]
        scope_resolver=object(),  # type: ignore[arg-type]
        sparse_retriever=object(),  # type: ignore[arg-type]
        dense_retriever=object(),  # type: ignore[arg-type]
        source_resolver=object(),  # type: ignore[arg-type]
        turn_signer=signer,
    )

    def request(token: str) -> SearchRequest:
        return SearchRequest(
            query="후속 질문",
            configuration_id=configuration_id,
            workspace_ids=list(scope.workspace_ids),
            history=[
                ConversationTurnRequest(
                    role="assistant",
                    content=content,
                    turn_id=turn_id,
                    validation_token=token,
                )
            ],
        )

    scoped_token = signer.sign_scoped(
        content=content,
        actor_id=actor_id,
        turn_id=turn_id,
        configuration_version_id=configuration_version_id,
        scope=scope,
    )
    configuration = type(
        "Configuration",
        (),
        {"configuration_version_id": configuration_version_id},
    )()

    assert len(
        service._validated_history(  # noqa: SLF001
            request=request(scoped_token),
            actor_id=actor_id,
            configuration=configuration,
            conversation_scope=scope,
        )
    ) == 1

    legacy_token = signer.sign(
        content=content,
        actor_id=actor_id,
        turn_id=turn_id,
        configuration_version_id=configuration_version_id,
    )
    with pytest.raises(AppError) as caught:
        service._validated_history(  # noqa: SLF001
            request=request(legacy_token),
            actor_id=actor_id,
            configuration=configuration,
            conversation_scope=scope,
        )
    assert caught.value.code == "conversation_history_invalid"


def test_unrestricted_scope_accepts_v2_but_selected_scope_rejects_it() -> None:
    signer = ConversationTurnSigner(b"f" * 32)
    actor_id = UUID("10000000-0000-0000-0000-000000000001")
    configuration_version_id = UUID("20000000-0000-0000-0000-000000000001")
    turn_id = UUID("30000000-0000-0000-0000-000000000001")
    content = "v2 compatibility answer"
    unrestricted = ConversationScopeBinding(
        domain_id=UUID("40000000-0000-0000-0000-000000000001"),
        connection_version_id=UUID("50000000-0000-0000-0000-000000000001"),
        workspace_ids=(UUID("60000000-0000-0000-0000-000000000001"),),
        folder_ids=(),
    )
    token = "MyleYrl3EveNy8XWUK0okUkFm_QbhVouYt0jZxQCsmY"
    turn = ConversationTurn(
        role=ConversationRole.ASSISTANT,
        content=content,
        turn_id=turn_id,
        validation_token=token,
    )

    assert signer.verify_scoped(
        turn,
        actor_id=actor_id,
        configuration_version_id=configuration_version_id,
        scope=unrestricted,
    )
    assert not signer.verify_scoped(
        turn,
        actor_id=actor_id,
        configuration_version_id=configuration_version_id,
        scope=ConversationScopeBinding(
            domain_id=unrestricted.domain_id,
            connection_version_id=unrestricted.connection_version_id,
            workspace_ids=unrestricted.workspace_ids,
            folder_ids=unrestricted.folder_ids,
            document_ids=(uuid4(),),
            scope_fingerprint="a" * 64,
        ),
    )
