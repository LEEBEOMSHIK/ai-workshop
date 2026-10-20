"""Transport bodies stay in the authorized current response, never saved turns."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.conversations.domain import Conversation, reserve_turn
from ai_workshop.labs.rag.conversations.schemas import ConversationDetail, ConversationTurnResponse
from ai_workshop.labs.rag.conversations.service import _stored_response, _with_request_input
from ai_workshop.labs.rag.domains.schemas import DomainSearchResponse
from ai_workshop.labs.rag.generation.input_inspection import (
    capture_generation_input,
    current_input_inspection,
    record_generation_input,
    record_generation_response,
)
from ai_workshop.labs.rag.search.schemas import SearchDiagnosticsResponse
from tests.unit.labs.rag.conversations.test_service import (
    response,
    seed_conversation,
)
from tests.unit.labs.rag.conversations.test_service import (
    setup as setup,
)


def inspected_response():
    with capture_generation_input(True):
        record_generation_input(
            {"model": "synthetic-model", "max_tokens": 128, "messages": [
                {"role": "system", "content": "Synthetic final instructions"},
                {"role": "user", "content": "Synthetic request-only evidence marker"},
            ]},
            provider="local_openai_compatible", dialect="ollama",
            model_name="Synthetic display model", model_version=1,
            prompt_ref="rag-answer-v3", profile_version=3, evidence_budget=None,
        )
        record_generation_response()
        inspection = current_input_inspection()
    assert inspection is not None
    value = response()
    value.diagnostics = SearchDiagnosticsResponse(
        candidates=[], stages_ms={"generation": 1.0}, min_keyword_coverage=0.5,
        min_semantic_score=0.8, generation_input=inspection,
    )
    return value


def test_storage_excludes_capture_without_mutating_response_or_other_diagnostics():
    value = inspected_response()
    stored = _stored_response(value)
    assert "generation_input" not in stored["diagnostics"]
    assert stored["diagnostics"]["stages_ms"] == {"generation": 1.0}
    assert "Synthetic request-only evidence marker" not in json.dumps(stored)
    assert value.diagnostics.generation_input.request_json is not None
    assert _stored_response(response())["diagnostics"] is None


@pytest.mark.asyncio
async def test_current_submit_has_capture_but_storage_detail_and_replay_do_not(setup):
    service, repo, _, executor, actor, incoming = setup
    value = inspected_response()
    executor.execute.return_value = value
    created = await seed_conversation(service, "domain", actor)
    current = await service.submit("domain", actor, created.id, incoming)
    assert (
        current.turns[0].response.diagnostics.generation_input == value.diagnostics.generation_input
    )
    saved = repo.items[created.id].turns[0].response
    assert "generation_input" not in saved["diagnostics"]
    assert "Synthetic request-only evidence marker" not in json.dumps(saved)
    detail = await service.detail("domain", actor, created.id)
    replay = await service.submit("domain", actor, created.id, incoming)
    assert detail.turns[0].response.diagnostics.generation_input is None
    assert replay.turns[0].response.diagnostics.generation_input is None
    assert executor.execute.await_count == 1


@pytest.mark.asyncio
async def test_capture_is_not_reintroduced_after_fresh_view_revokes_source(setup):
    service, repo, access, executor, actor, incoming = setup
    executor.execute.return_value = inspected_response()
    created = await seed_conversation(service, "domain", actor)
    # History inspects the reserved running turn before final authority checks
    # its response candidate. Revoke only when the fresh view reads completion;
    # a call-count list would deny the candidate and exhaust before that view.
    visibility_checks = []

    def source_visible(owner, turn, **kwargs):
        visibility_checks.append((owner, turn.status, turn.response is not None))
        return turn.status != "completed"

    access.visible.side_effect = source_visible
    current = await service.submit("domain", actor, created.id, incoming)
    assert current.turns[0].redacted and current.turns[0].response is None
    assert current.turns[0].status == "completed"
    assert current.turns[0].query == "" and current.turns[0].request_scope is None
    assert (actor, "running", True) in visibility_checks
    assert (actor, "completed", True) in visibility_checks
    assert all(owner == actor for owner, _, _ in visibility_checks)
    assert "Synthetic request-only evidence marker" not in current.model_dump_json()
    assert "generation_input" not in repo.items[created.id].turns[0].response["diagnostics"]


def test_overlay_requires_same_completed_visible_turn_and_retains_saved_object():
    value = inspected_response()
    now = datetime.now(UTC)
    detail = ConversationDetail(
        id=uuid4(), title="Synthetic title", revision=1, created_at=now, updated_at=now,
        turns=[ConversationTurnResponse(
            id=uuid4(), request_id=uuid4(), sequence=1, status="completed", query="Question?",
            response=DomainSearchResponse.model_validate(_stored_response(value)),
            request_scope=None, segment=1, error_code=None, redacted=False,
            created_at=now, updated_at=now, execution_terminated=True,
        )],
    )
    turn = detail.turns[0]
    assert _with_request_input(detail, uuid4(), value) == detail
    assert _with_request_input(detail, turn.id, None) == detail
    assert _with_request_input(detail, turn.id, response()) == detail
    for update in (
        {"status": "running"}, {"status": "failed"}, {"status": "cancelled"},
        {"status": "interrupted"}, {"redacted": True}, {"response": None},
        {"response": turn.response.model_copy(update={"diagnostics": None})},
    ):
        hidden = detail.model_copy(update={"turns": [turn.model_copy(update=update)]})
        assert _with_request_input(hidden, turn.id, value) == hidden
    attached = _with_request_input(detail, turn.id, value)
    assert attached.turns[0].response.diagnostics.generation_input is not None
    assert detail.turns[0].response.diagnostics.generation_input is None


def complete_without_io(coroutine):
    """Only drive coroutines whose awaited in-memory mocks complete immediately."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    finally:
        coroutine.close()
    pytest.fail("The no-I/O boundary unexpectedly suspended")


@pytest.mark.parametrize("predecessor_allowed,current_allowed", [
    (True, True), (False, True), (True, False),
])
def test_fresh_view_acl_dependency_closure_blocks_input_overlay_without_io(
    setup, predecessor_allowed, current_allowed,
):
    service, _, access, _, actor, incoming = setup
    value = inspected_response()
    now = datetime.now(UTC)
    item = Conversation(uuid4(), actor, uuid4(), "Synthetic title", 1, now, now)
    predecessor, _ = reserve_turn(item, incoming, "synthetic-scope", now)
    predecessor.status = "completed"
    predecessor.response = _stored_response(value)
    predecessor.execution_terminated = True
    following = incoming.model_copy(update={
        "request_id": uuid4(), "expected_revision": item.revision,
    })
    current, _ = reserve_turn(item, following, "synthetic-scope", now)
    current.status = "completed"
    current.response = _stored_response(value)
    current.execution_terminated = True
    current.dependencies = [predecessor.id]
    access.visible.side_effect = lambda owner, turn, **kwargs: (
        predecessor_allowed if turn.id == predecessor.id else current_allowed
    )

    detail = complete_without_io(service._view(item))
    shown = _with_request_input(detail, current.id, value)

    assert shown.turns[0].redacted is not predecessor_allowed
    assert shown.turns[1].redacted is not (predecessor_allowed and current_allowed)
    assert access.visible.await_count == (2 if predecessor_allowed else 1)
    assert all(call.args[0] == actor for call in access.visible.await_args_list)
    if predecessor_allowed and current_allowed:
        assert shown.turns[1].response.diagnostics.generation_input is not None
        assert shown.turns[0].response.diagnostics.generation_input is None
    else:
        assert shown.turns[1].response is None
        assert shown.turns[1].query == "" and shown.turns[1].request_scope is None
        assert shown.turns[1].error_code == "conversation_source_unavailable"
        assert "Synthetic request-only evidence marker" not in shown.model_dump_json()
        if not predecessor_allowed:
            assert shown.turns[0].response is None
            assert shown.title != item.title
    assert all("generation_input" not in turn.response["diagnostics"] for turn in item.turns)
