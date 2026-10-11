from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.evaluation import generative_repository as module
from ai_workshop.labs.rag.evaluation.generative import (
    GenerativeObservation,
    PrivateGenerativeResult,
)
from ai_workshop.shared.errors import AppError


async def test_success_persistence_verifies_server_execution_before_writing(monkeypatch):
    token, execution, config, profile, actor = (uuid4() for _ in range(5))
    row = SimpleNamespace(
        execution_id=execution,
        configuration_version_id=config,
        run_id=uuid4(),
        status="running",
        claim_token=token,
        result=None,
    )
    run = SimpleNamespace(
        owner_id=actor,
        status="running",
        claim_token=token,
        snapshot={
            "candidates": [
                {
                    "configuration_version_id": str(config),
                    "component_snapshot": {
                        "profiles": [{"kind": "generation", "id": str(profile)}]
                    },
                }
            ]
        },
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=row),
        scalar=AsyncMock(return_value=run),
        refresh=AsyncMock(),
    )

    @asynccontextmanager
    async def begin():
        yield session

    verifier = AsyncMock(side_effect=AppError("numeric_validation_binding_invalid", "Safe.", 409))
    from ai_workshop.labs.rag.generation import numeric_restore

    monkeypatch.setattr(numeric_restore, "verify_numeric_views", verifier)
    repository = module.GenerativeRepository(SimpleNamespace(begin=begin))
    result = PrivateGenerativeResult(
        observation=GenerativeObservation(execution_id=execution, generation_status="answered"),
        answer="Synthetic answer.",
    )
    with pytest.raises(AppError):
        await repository.complete_attempt(uuid4(), token, result)
    assert row.result is None and row.status == "running"
    assert verifier.await_args.kwargs["execution_id"] == execution
    assert verifier.await_args.kwargs["configuration_version_id"] == config
    assert verifier.await_args.kwargs["generation_profile_id"] == profile
    assert verifier.await_args.kwargs["actor_id"] == actor
