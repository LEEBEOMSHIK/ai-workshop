"""Real AsyncSession transaction scopes with in-memory SQLite, no external services."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import Column, Integer, String, create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base
from starlette.requests import Request

from ai_workshop.config import Settings
from ai_workshop.labs.rag.evaluation import generative_api as api
from ai_workshop.labs.rag.evaluation.generative import ExpectedAnswerRule
from ai_workshop.labs.rag.evaluation.generative_schemas import (
    GenerativeReviewRequest,
    GenerativeRunCreate,
    GenerativeRunView,
)

Base = declarative_base()


class Mutation(Base):
    __tablename__ = "synthetic_mutation"
    id = Column(Integer, primary_key=True)
    value = Column(String, nullable=False)


@pytest.mark.parametrize("operation", ["submit", "retry", "judge"])
async def test_mutation_materializes_response_before_committing_dependency_transaction(
    monkeypatch, operation
):
    # Bind the synchronous facade only: AsyncSession's real transaction context, flush,
    # commit and execute paths run without requiring an asynchronous SQLite driver.
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    actor = SimpleNamespace(id=uuid4())
    run_id, case_id, attempt_id, dataset_id, policy_id = [uuid4() for _ in range(5)]
    rule = ExpectedAnswerRule(version=1, expected_answer_status="insufficient_evidence")
    run = SimpleNamespace(
        id=run_id, input_approval=None, expected_rules={str(case_id): rule.model_dump()}
    )
    attempt = SimpleNamespace(
        id=attempt_id, run_id=run_id, case_id=case_id, result_digest="a" * 64, status="completed"
    )
    try:
        async with AsyncSession(expire_on_commit=False, autoflush=False) as session:
            session.sync_session.bind = engine
            original_add = session.add
            monkeypatch.setattr(
                session,
                "get",
                AsyncMock(side_effect=lambda model, key: run if key == run_id else attempt),
            )
            if operation == "judge":
                monkeypatch.setattr(
                    session, "add", lambda value: original_add(Mutation(value="judge"))
                )

            async def mutate(*args, **kwargs):
                original_add(Mutation(value=operation))
                return run

            async def detail(actual_session, actual_actor, actual_run):
                assert (
                    actual_session is session and actual_actor == actor.id and actual_run == run_id
                )
                value = await session.scalar(select(Mutation.value))
                return GenerativeRunView(
                    id=run_id,
                    dataset_snapshot_id=dataset_id,
                    policy_id=policy_id,
                    rules_digest="b" * 64,
                    status=value or "before",
                    created_at=datetime.now(UTC),
                    repetition_count=2,
                    attempts=[],
                )

            monkeypatch.setattr(api, "run_detail", detail)
            monkeypatch.setattr(api.GenerativeRepository, "submit", mutate)
            monkeypatch.setattr(api.GenerativeRepository, "retry_failed", mutate)
            request = Request({"type": "http", "headers": []})
            async with session.begin():
                if operation == "submit":
                    body = GenerativeRunCreate(
                        request_id=uuid4(),
                        dataset_snapshot_id=dataset_id,
                        configuration_version_ids=[uuid4()],
                        policy_id=policy_id,
                        expected_rules={case_id: rule},
                    )
                    result = await api.submit(
                        body,
                        request,
                        actor,
                        session,
                        Settings(
                            _env_file=None, secret_key="synthetic-transaction-test-secret-key-2026"
                        ),
                        SimpleNamespace(find_dataset_visible=AsyncMock(return_value=object())),
                    )
                elif operation == "retry":
                    result = await api.retry(
                        run_id,
                        actor,
                        session,
                        request,
                        Settings(
                            _env_file=None, secret_key="synthetic-transaction-test-secret-key-2026"
                        ),
                    )
                else:
                    result = await api.judge(
                        run_id,
                        attempt_id,
                        GenerativeReviewRequest(
                            result_digest="a" * 64, status="passed", reason="Synthetic review"
                        ),
                        actor,
                        session,
                    )
                assert result.status == operation
                assert not session.in_transaction()
            assert await session.scalar(select(Mutation.value)) == operation
    finally:
        engine.dispose()
