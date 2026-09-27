import asyncio
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.executions.domain import ExecutionIdentity
from ai_workshop.labs.rag.executions.observer import (
    ExecutionObserver,
    current_observer,
    observed_call,
)
from tests.unit.labs.rag.conversations.test_service import setup  # noqa: F401
from tests.unit.labs.rag.executions.test_observer import Recorder
from tests.unit.labs.rag.search.test_context_generation import (
    test_context_only_evidence_reaches_generation_and_every_citation_is_returned as context_search,
)


@pytest.mark.asyncio
async def test_replay_keeps_one_execution_and_one_provider_call(setup):  # noqa: F811
    service, _, _, executor, actor, request = setup
    recorder = Recorder()
    service.recorder = recorder
    conversation = await service.create("domain", actor, None)
    first = await service.submit("domain", actor, conversation.id, request)
    replay = await service.submit("domain", actor, conversation.id, request)
    assert first.turns[0].execution_id == replay.turns[0].execution_id
    assert first.turns[0].execution_id is not None
    assert executor.execute.await_count == 1
    assert recorder.outcome.state == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("diagnostics", [False, True])
async def test_selection_and_citation_recorded_with_diagnostics_disabled(diagnostics):
    recorder = Recorder()
    observer = ExecutionObserver(ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), recorder)
    await observer.start()
    await observed_call(context_search(diagnostics), observer)
    finished = {r.stage: r for r in recorder.rows if r.state == "completed"}
    assert {"retrieval", "selection", "generation", "citation_validation"} <= finished.keys()
    assert finished["selection"].selection.selected_count > 0
    assert finished["selection"].selection.candidates
    assert current_observer.get() is None


@pytest.mark.asyncio
async def test_parallel_server_contexts_are_isolated():
    async def read():
        await asyncio.sleep(0)
        return current_observer.get().identity.execution_id

    observers = [
        ExecutionObserver(ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), Recorder())
        for _ in range(2)
    ]
    ids = await asyncio.gather(*(observed_call(read(), o) for o in observers))
    assert ids == [o.identity.execution_id for o in observers]
    assert current_observer.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["persistence", "finish"])
async def test_late_observation_failure_is_incomplete_in_response(setup, failure):  # noqa: F811
    service, _, _, _, actor, request = setup

    class LateFailure(Recorder):
        async def record(self, id, observation):
            if (
                failure == "persistence"
                and observation.stage == "persistence"
                and observation.state == "completed"
            ):
                raise RuntimeError("synthetic failure")
            await super().record(id, observation)

        async def finish(self, id, outcome):
            if failure == "finish":
                raise RuntimeError("synthetic failure")
            await super().finish(id, outcome)

    service.recorder = LateFailure()
    conversation = await service.create("domain", actor, None)
    result = await service.submit("domain", actor, conversation.id, request)
    assert result.turns[0].status == "completed"
    assert result.turns[0].observation_complete is False
