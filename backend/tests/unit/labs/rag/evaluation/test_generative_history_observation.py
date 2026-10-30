"""Frozen evaluation history observation must precede terminal attempt persistence."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.config import Settings
from ai_workshop.labs.rag.evaluation import generative_workflow as module
from ai_workshop.labs.rag.generation.domain import GenerationOutcome, GenerationStatus
from ai_workshop.labs.rag.generation.execution import track_local_http_attempt
from ai_workshop.shared.errors import AppError


def workflow_fixture(monkeypatch, *, history=(), mode="success", history_write_failure=False):
    run_id, token, case_id = uuid4(), uuid4(), uuid4()
    run = SimpleNamespace(owner_id=uuid4(), dataset_snapshot_id=uuid4(), input_approval=None)
    attempt = SimpleNamespace(id=uuid4(), execution_id=uuid4(), case_id=case_id,
                              configuration_version_id=uuid4())
    prepared = SimpleNamespace(configuration=SimpleNamespace(generation_profile=None),
                               request=SimpleNamespace(history=deepcopy(history)))
    events, saved, received = [], [], []

    class TerminalRecorder:
        def __init__(self):
            self.rows, self.rejected = [], []
            self.terminal = False
            self.outcome = None
            self.persistence_start = None

        async def start(self, identity):
            assert identity.execution_id == attempt.execution_id

        async def record(self, execution_id, observation):
            assert execution_id == attempt.execution_id
            if observation.stage == "persistence" and observation.state == "running":
                self.persistence_start = observation.started_at
            persistence_completion = (
                observation.stage == "persistence" and observation.state == "completed"
                and observation.started_at == self.persistence_start
            )
            if ((self.terminal and not persistence_completion)
                    or (history_write_failure and observation.stage == "history")):
                self.rejected.append(observation)
                raise ValueError("Synthetic rejected stage observation")
            self.rows.append(observation)
            events.append((observation.stage, observation.state))

        async def finish(self, execution_id, outcome):
            assert self.terminal
            self.outcome = outcome

    recorder = TerminalRecorder()

    class Session:
        async def get(self, model, id):
            return run if id == run_id else SimpleNamespace(fixture_bytes=b"synthetic")

        async def scalars(self, statement):
            return SimpleNamespace(all=lambda: [attempt.id])

    @asynccontextmanager
    async def sessions():
        yield Session()

    @asynccontextmanager
    async def codex(settings):
        yield None

    class Repository:
        async def claim_attempt(self, id, claim):
            assert (id, claim) == (attempt.id, token)
            return attempt

        async def complete_attempt(self, id, claim, result, *, error_code):
            saved.append((result, error_code))
            recorder.terminal = True
            events.append(("attempt", "terminal"))

        async def finish_run(self, id, claim):
            events.append(("run", "finished"))

    class Frozen:
        def __init__(self, settings):
            pass

        async def close(self):
            pass

    class Adapter:
        def __init__(self, *args, **kwargs):
            pass

        async def prepare(self, *args):
            events.append(("prepare", "started"))
            if mode == "prepare_failure":
                raise AppError("configuration_not_ready", "Synthetic failure", 409)
            return prepared

    async def interrupted():
        raise asyncio.CancelledError

    class Pipeline:
        async def execute(self, value, *, observer):
            received.append(value)
            await observer.end("request")
            for stage in ("contextualization", "retrieval", "selection", "generation",
                          "citation_validation"):
                await observer.begin(stage)
                if stage == "generation":
                    if mode == "cancel":
                        raise asyncio.CancelledError
                    if mode == "cancel_pending":
                        await track_local_http_attempt(interrupted())
                await observer.end(stage)
            return SimpleNamespace(
                retrieved_evidence_ids=(), grounding_evidence=(),
                generation=GenerationOutcome(status=GenerationStatus.INSUFFICIENT_EVIDENCE),
            )

    async def search_service(*args):
        yield Pipeline()

    case = SimpleNamespace(id=case_id,
                           permission_scenario=SimpleNamespace(authorized_source_ids=frozenset()))
    monkeypatch.setattr(module, "load_evaluation_dataset", lambda _: SimpleNamespace(cases=[case]))
    monkeypatch.setattr(module, "candidate_input", lambda *args: None)
    monkeypatch.setattr(module, "ProductionEvaluationSearch", Frozen)
    monkeypatch.setattr(module, "codex_services", codex)
    monkeypatch.setattr(module, "FrozenGenerativeAdapter", Adapter)
    monkeypatch.setattr(module, "SqlAlchemyExecutionRecorder", lambda _: recorder)
    monkeypatch.setattr(module, "get_search_service", search_service)
    monkeypatch.setattr(module, "get_search_configuration_resolver", lambda *args: None)
    monkeypatch.setattr(module.SearchResponse, "from_domain",
                        lambda _: SimpleNamespace(grounding_evidence=[]))
    workflow = module.GenerativeWorkflow(sessions, Settings(
        _env_file=None, environment="test", secret_key="synthetic-unit-test-secret-key-only",
    ))
    workflow.repository = Repository()
    return SimpleNamespace(workflow=workflow, run_id=run_id, token=token, recorder=recorder,
                           prepared=prepared, received=received, saved=saved, events=events)


@pytest.mark.parametrize("history", [[], [{"role": "user", "content": "Synthetic prior turn"}]])
async def test_history_skipped_before_terminal_attempt_preserves_complete_and_frozen_input(
    monkeypatch, history,
):
    env = workflow_fixture(monkeypatch, history=history)
    await env.workflow._execute_claimed(env.run_id, env.token)
    assert env.recorder.outcome.complete is True
    assert env.recorder.rejected == []
    rows = [row for row in env.recorder.rows if row.stage == "history"]
    assert len(rows) == 1 and rows[0].state == "skipped" and rows[0].reason == "not_executed"
    assert rows[0].started_at is None and rows[0].history_selection is None
    assert env.events.index(("history", "skipped")) < env.events.index(("prepare", "started"))
    assert env.events.index(("history", "skipped")) < env.events.index(("attempt", "terminal"))
    assert env.received == [env.prepared] and env.received[0] is env.prepared
    assert env.prepared.request.history == history


async def test_failed_history_observation_does_not_force_complete(monkeypatch):
    env = workflow_fixture(monkeypatch, history_write_failure=True)
    await env.workflow._execute_claimed(env.run_id, env.token)
    assert env.recorder.outcome.complete is False
    assert [row.stage for row in env.recorder.rejected] == ["history"]
    assert env.recorder.outcome.state == "completed"


@pytest.mark.parametrize("mode", ["prepare_failure", "cancel_pending"])
async def test_early_history_skip_does_not_infer_unobserved_stages_on_failure(monkeypatch, mode):
    env = workflow_fixture(monkeypatch, mode=mode)
    if mode == "cancel_pending":
        with pytest.raises(asyncio.CancelledError):
            await env.workflow._execute_claimed(env.run_id, env.token)
    else:
        await env.workflow._execute_claimed(env.run_id, env.token)
    assert any(row.stage == "history" and row.state == "skipped" for row in env.recorder.rows)
    assert env.recorder.outcome.state == "failed" and env.recorder.outcome.complete is False
    assert all(row.stage != "history" for row in env.recorder.rejected)
    assert env.recorder.rejected  # Other terminal observations remain denied.
    assert not any(row.stage == "citation_validation" for row in env.recorder.rows)


async def test_early_history_skip_does_not_settle_predispatch_cancellation(monkeypatch):
    env = workflow_fixture(monkeypatch, mode="cancel")
    with pytest.raises(asyncio.CancelledError):
        await env.workflow._execute_claimed(env.run_id, env.token)
    assert any(row.stage == "history" and row.state == "skipped" for row in env.recorder.rows)
    assert not env.recorder.terminal and env.recorder.outcome is None
    assert env.saved == []
