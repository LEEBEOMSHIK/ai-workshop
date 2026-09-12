import importlib.util
from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.codex_authorization import (
    CodexCallOperation,
    EvidenceClassification,
)


def _context(**changes):
    assert importlib.util.find_spec("ai_workshop.labs.rag.generation.codex_request") is not None
    from ai_workshop.labs.rag.generation.codex_request import CodexRequestContext

    return CodexRequestContext(
        **{
            "actor_id": UUID(int=1),
            "request_id": UUID(int=2),
            "operation": CodexCallOperation.SEARCH,
            "configuration_version_id": UUID(int=3),
            "workspace_ids": (UUID(int=5), UUID(int=4)),
            "input_classification": EvidenceClassification.SYNTHETIC,
            "consented": True,
            "disclosure_version": "generation-external-v1",
            **changes,
        }
    )


def test_context_is_immutable_canonical_and_body_free():
    context = _context()
    assert context.workspace_ids == (UUID(int=4), UUID(int=5))
    with pytest.raises(FrozenInstanceError):
        context.consented = False


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_id": "private"},
        {"operation": "search"},
        {"consented": False},
        {"consented": 1},
        {"input_classification": EvidenceClassification.PRIVATE},
        {"input_classification": "synthetic"},
        {"disclosure_version": ""},
        {"disclosure_version": "private" * 50},
        {"workspace_ids": (UUID(int=4), UUID(int=4))},
        {"workspace_ids": tuple(UUID(int=i) for i in range(129))},
    ],
)
def test_invalid_or_unbounded_context_is_rejected_safely(changes):
    with pytest.raises(ValueError, match="^codex_request_invalid$") as caught:
        _context(**changes)
    assert caught.value.__context__ is None
