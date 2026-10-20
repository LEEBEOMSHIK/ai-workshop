"""Cancellation behavior without providers, a worker, or external databases."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.evaluation.generative_repository import GenerativeRepository
from ai_workshop.labs.rag.evaluation.generative_workflow import GenerativeWorkflow
from ai_workshop.shared.errors import AppError


def pending_records():
    actor = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        owner_id=actor,
        status="pending",
        claim_token=None,
        claimed_at=None,
        finished_at=None,
        cancelled_by=None,
        cancelled_at=None,
        cancellation_reason=None,
        runtime_environment=None,
        snapshot={"synthetic": True},
        expected_rules={"synthetic": ["required"]},
        rules_digest="a" * 64,
    )
    attempts = [
        SimpleNamespace(
            id=uuid4(),
            execution_id=uuid4(),
            status="pending",
            claim_token=None,
            result=None,
            result_bytes=None,
            result_digest=None,
            finished_at=None,
            error_code=None,
        )
        for _ in range(4)
    ]
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[run, None, None]),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: attempts)),
        flush=AsyncMock(),
    )
    return actor, run, attempts, session


async def test_pending_cancel_preserves_inputs_and_records_actor_once():
    actor, run, attempts, session = pending_records()
    frozen = deepcopy((run.snapshot, run.expected_rules, run.rules_digest))
    await GenerativeRepository.cancel_pending(session, actor, run.id, "user_requested")
    assert run.status == "cancelled"
    assert run.cancelled_by == actor
    assert run.cancellation_reason == "user_requested"
    assert run.finished_at == run.cancelled_at is not None
    assert all(a.status == "cancelled" and a.finished_at == run.cancelled_at for a in attempts)
    assert all(a.result is None and a.claim_token is None for a in attempts)
    assert (run.snapshot, run.expected_rules, run.rules_digest) == frozen
    first = (run.cancelled_by, run.cancelled_at, run.cancellation_reason)
    session.scalar = AsyncMock(return_value=run)
    await GenerativeRepository.cancel_pending(session, actor, run.id, "user_requested")
    assert (run.cancelled_by, run.cancelled_at, run.cancellation_reason) == first


@pytest.mark.parametrize("status", ["running", "completed", "failed"])
async def test_started_or_terminal_run_cannot_be_cancelled(status):
    actor, run, attempts, session = pending_records()
    run.status = status
    with pytest.raises(AppError) as error:
        await GenerativeRepository.cancel_pending(session, actor, run.id, "user_requested")
    assert error.value.status_code == 409
    assert run.status == status
    assert all(a.status == "pending" for a in attempts)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "running"),
        ("status", "failed"),
        ("claim_token", uuid4()),
        ("result", {}),
        ("result_bytes", b"{}"),
        ("result_digest", "a" * 64),
        ("finished_at", "already-finished"),
        ("error_code", "already_failed"),
    ],
)
async def test_attempt_with_execution_evidence_blocks_cancellation(field, value):
    actor, run, attempts, session = pending_records()
    setattr(attempts[0], field, value)
    with pytest.raises(AppError):
        await GenerativeRepository.cancel_pending(session, actor, run.id, "user_requested")
    assert run.status == "pending" and run.cancelled_at is None


@pytest.mark.parametrize("evidence", ["execution", "audit"])
async def test_persisted_execution_or_audit_blocks_cancellation(evidence):
    actor, run, _, session = pending_records()
    session.scalar = AsyncMock(
        side_effect=[run, uuid4() if evidence == "execution" else None, uuid4()]
    )
    with pytest.raises(AppError):
        await GenerativeRepository.cancel_pending(session, actor, run.id, "user_requested")
    assert run.status == "pending"


async def test_unknown_or_other_owner_run_is_not_disclosed():
    actor, run, _, session = pending_records()
    session.scalar = AsyncMock(return_value=None)
    with pytest.raises(AppError) as error:
        await GenerativeRepository.cancel_pending(session, actor, run.id, "user_requested")
    assert error.value.status_code == 404


async def test_late_queue_delivery_never_enters_execution_after_cancel(monkeypatch):
    monkeypatch.setattr(
        "ai_workshop.labs.rag.evaluation.generative_workflow.capture_worker_runtime",
        lambda **kwargs: {},
    )
    workflow = object.__new__(GenerativeWorkflow)
    workflow.settings = SimpleNamespace(environment="test")
    workflow.repository = SimpleNamespace(claim_run=AsyncMock(return_value=None))
    workflow._execute_claimed = AsyncMock(side_effect=AssertionError("must not execute"))
    await workflow.run(uuid4())
