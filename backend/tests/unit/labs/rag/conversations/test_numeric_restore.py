from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.conversations.test_service import seed_conversation
from tests.unit.labs.rag.conversations.test_service import setup as setup


async def test_numeric_tampering_or_revocation_hides_restored_turn_and_uses_server_execution(setup):
    service, repo, _, _, actor, incoming = setup
    conversation = await seed_conversation(service, "demo", actor)
    completed = await service.submit("demo", actor, conversation.id, incoming)
    execution_id = uuid4()
    repo.items[completed.id].turns[0].execution_id = execution_id
    service.numeric_verifier = AsyncMock(
        side_effect=AppError("numeric_validation_binding_invalid", "Safe refusal", 409)
    )
    restored = await service.detail("demo", actor, completed.id)
    assert restored.turns[0].redacted and restored.turns[0].response is None
    assert restored.turns[0].query == "" and restored.turns[0].execution_id is None
    assert service.numeric_verifier.call_args.args[:2] == (actor, execution_id)


async def test_storage_verification_failure_exposes_only_safe_rejection():
    from types import SimpleNamespace

    from ai_workshop.labs.rag.generation.numeric_restore import verify_numeric_views

    repository = SimpleNamespace(
        expected_context_for_execution=AsyncMock(side_effect=RuntimeError("synthetic driver error"))
    )
    with pytest.raises(AppError) as raised:
        await verify_numeric_views(
            repository,
            actor_id=uuid4(),
            execution_id=uuid4(),
            status="answered",
            answer=None,
            claims=(),
            binding=None,
        )
    assert raised.value.code == "numeric_validation_binding_invalid"
