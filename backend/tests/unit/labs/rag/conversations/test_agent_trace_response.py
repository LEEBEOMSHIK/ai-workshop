"""Delegation content is shown only by the authorized current submit response."""

import json

from ai_workshop.labs.rag.executions.agent_trace import (
    AgentTraceCollector,
    capture_agent_trace,
    current_agent_trace,
)
from ai_workshop.labs.rag.search.schemas import SearchDiagnosticsResponse
from tests.unit.labs.rag.conversations.test_service import response, seed_conversation
from tests.unit.labs.rag.conversations.test_service import setup as setup


async def traced_response():
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        root = await collector.start_span(
            kind="agent", name="manager", input="synthetic trace body",
        )
        await collector.end_span(root, output="synthetic trace result")
        value = response()
        value.diagnostics = SearchDiagnosticsResponse(
            candidates=[], stages_ms={}, min_keyword_coverage=0.5, min_semantic_score=0.8,
            agent_trace=current_agent_trace(),
        )
        return value


async def test_live_response_has_delegation_body_but_saved_turn_and_replay_do_not(setup):
    service, repo, _, executor, actor, incoming = setup
    executor.execute.return_value = await traced_response()
    created = await seed_conversation(service, "domain", actor)
    live = await service.submit("domain", actor, created.id, incoming)
    assert "synthetic trace body" in live.model_dump_json()
    stored = repo.items[created.id].turns[0].response
    saved_input = stored["diagnostics"]["agent_trace"]["spans"][0]["input"]
    assert saved_input["text"] is None and saved_input["content_status"] == "not_retained"
    assert "synthetic trace" not in json.dumps(stored)
    replay = await service.submit("domain", actor, created.id, incoming)
    assert "synthetic trace" not in replay.model_dump_json()
    assert executor.execute.await_count == 1


async def test_current_acl_revocation_prevents_trace_body_overlay(setup):
    service, _, access, executor, actor, incoming = setup
    executor.execute.return_value = await traced_response()
    created = await seed_conversation(service, "domain", actor)
    access.visible.side_effect = lambda owner, turn, **kwargs: turn.status != "completed"
    live = await service.submit("domain", actor, created.id, incoming)
    assert live.turns[0].redacted and live.turns[0].response is None
    assert "synthetic trace" not in live.model_dump_json()
