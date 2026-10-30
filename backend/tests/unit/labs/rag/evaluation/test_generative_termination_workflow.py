import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ai_workshop.config import Settings
from ai_workshop.labs.rag.evaluation import generative_workflow as module
from ai_workshop.labs.rag.generation.domain import GenerationOutcome, GenerationStatus
from ai_workshop.labs.rag.generation.execution import track_local_http_attempt
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.executions.test_observer import Recorder


def workflow_fixture(monkeypatch, mode):
    run_id, token, case_id = uuid4(), uuid4(), uuid4()
    run = SimpleNamespace(owner_id=uuid4(), dataset_snapshot_id=uuid4(), input_approval=None)
    attempts = [SimpleNamespace(id=uuid4(), execution_id=uuid4(), case_id=case_id,
                                configuration_version_id=uuid4()) for _ in range(2)]
    claims, calls, results, finishes, recorders = [], [], [], [], []

    class Session:
        async def get(self, model, id):
            return run if id == run_id else SimpleNamespace(fixture_bytes=b"synthetic")

        async def scalars(self, statement):
            return SimpleNamespace(all=lambda: [a.id for a in attempts])

    @asynccontextmanager
    async def sessions():
        yield Session()

    @asynccontextmanager
    async def codex(settings):
        yield SimpleNamespace(runtime_factory=None)

    class Repository:
        async def claim_attempt(self, id, claim):
            assert claim == token
            claims.append(id)
            return next(a for a in attempts if a.id == id)

        async def complete_attempt(self, id, claim, result, *, error_code):
            assert claim == token
            results.append((id, result, error_code))

        async def finish_run(self, id, claim):
            finishes.append((id, claim))

    class Frozen:
        def __init__(self, settings):
            pass

        async def close(self):
            pass

    class Adapter:
        def __init__(self, *args, **kwargs):
            pass

        async def prepare(self, *args):
            return SimpleNamespace(configuration=SimpleNamespace(generation_profile=None))

    async def received():
        return None

    async def interrupted():
        if mode == "cancel_pending":
            raise asyncio.CancelledError
        raise TimeoutError("synthetic incomplete local HTTP response")

    class Pipeline:
        async def execute(self, prepared, *, observer):
            calls.append(True)
            await observer.begin("generation")
            if len(calls) == 1:
                if mode in {"pending_timeout", "pending_then_success", "cancel_pending"}:
                    try:
                        await track_local_http_attempt(interrupted())
                    except TimeoutError:
                        if mode != "pending_then_success":
                            raise AppError("provider_timeout", "Synthetic timeout", 504) from None
                    await track_local_http_attempt(received())
                if mode == "confirmed_validation":
                    await track_local_http_attempt(received())
                    raise AppError("citation_validation_failed", "Synthetic invalid citation", 502)
                if mode == "predispatch_timeout":
                    raise AppError("provider_timeout", "Synthetic predispatch deadline", 504)
                if mode == "cancel_predispatch":
                    raise asyncio.CancelledError
            await observer.end("generation")
            return SimpleNamespace(
                retrieved_evidence_ids=(), grounding_evidence=(),
                generation=GenerationOutcome(status=GenerationStatus.INSUFFICIENT_EVIDENCE),
            )

    async def search_service(*args):
        yield Pipeline()

    def recorder(_):
        result = Recorder()
        recorders.append(result)
        return result

    case = SimpleNamespace(id=case_id,
                           permission_scenario=SimpleNamespace(authorized_source_ids=frozenset()))
    monkeypatch.setattr(module, "load_evaluation_dataset", lambda _: SimpleNamespace(cases=[case]))
    monkeypatch.setattr(module, "candidate_input", lambda *args: None)
    monkeypatch.setattr(module, "ProductionEvaluationSearch", Frozen)
    monkeypatch.setattr(module, "codex_services", codex)
    monkeypatch.setattr(module, "FrozenGenerativeAdapter", Adapter)
    monkeypatch.setattr(module, "SqlAlchemyExecutionRecorder", recorder)
    monkeypatch.setattr(module, "get_search_service", search_service)
    monkeypatch.setattr(module, "get_search_configuration_resolver", lambda *args: None)
    monkeypatch.setattr(module.SearchResponse, "from_domain",
                        lambda _: SimpleNamespace(grounding_evidence=[]))
    workflow = module.GenerativeWorkflow(sessions, Settings(
        _env_file=None, environment="test", secret_key="synthetic-unit-test-secret-key-only",
    ))
    workflow.repository = Repository()
    return SimpleNamespace(workflow=workflow, run_id=run_id, token=token, attempts=attempts,
                           claims=claims, calls=calls, results=results, finishes=finishes,
                           recorders=recorders)


@pytest.mark.parametrize("mode", ["pending_timeout", "pending_then_success", "cancel_pending"])
async def test_unconfirmed_local_attempt_stops_before_second_repetition(monkeypatch, mode):
    env = workflow_fixture(monkeypatch, mode)
    if mode == "cancel_pending":
        with pytest.raises(asyncio.CancelledError):
            await env.workflow._execute_claimed(env.run_id, env.token)
    else:
        await env.workflow._execute_claimed(env.run_id, env.token)
    assert len(env.claims) == len(env.calls) == len(env.results) == 1
    assert env.results[0][2] == "provider_termination_unconfirmed"
    assert env.results[0][1].answer is None
    assert env.recorders[0].outcome.error_code == "provider_termination_unconfirmed"
    assert env.recorders[0].outcome.state == "failed"
    assert env.finishes == []  # The result/fence transaction already terminated this run.


@pytest.mark.parametrize("mode,error", [
    ("normal", None), ("confirmed_validation", "citation_validation_failed"),
    ("predispatch_timeout", "provider_timeout"),
])
async def test_confirmed_or_undispatched_failure_preserves_repetitions(monkeypatch, mode, error):
    env = workflow_fixture(monkeypatch, mode)
    await env.workflow._execute_claimed(env.run_id, env.token)
    assert len(env.claims) == len(env.calls) == len(env.results) == 2
    assert env.results[0][2] == error
    assert env.results[1][2] is None
    assert env.finishes == [(env.run_id, env.token)]


async def test_cancellation_before_dispatch_preserves_existing_behavior(monkeypatch):
    env = workflow_fixture(monkeypatch, "cancel_predispatch")
    with pytest.raises(asyncio.CancelledError):
        await env.workflow._execute_claimed(env.run_id, env.token)
    assert len(env.calls) == 1
    assert env.results == env.finishes == []


async def test_manual_retry_cannot_reopen_a_run_with_unconfirmed_termination():
    from ai_workshop.labs.rag.evaluation.generative_repository import GenerativeRepository

    run = SimpleNamespace(status="failed", claim_token=None)
    prior = SimpleNamespace(configuration_version_id=uuid4(), case_id=uuid4(), repetition=0,
                            attempt_number=1, status="failed",
                            error_code="provider_termination_unconfirmed")
    session = SimpleNamespace(scalar=AsyncMock(return_value=run),
                              scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [prior])),
                              flush=AsyncMock(), add=Mock())
    with pytest.raises(AppError) as caught:
        await GenerativeRepository.retry_failed(session, uuid4(), uuid4())
    assert caught.value.code == "evaluation_retry_unavailable"
    assert run.status == "failed"
    session.add.assert_not_called()
    session.flush.assert_not_awaited()
