"""Independent private-body and late authorization boundaries; synthetic data only."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.conversations.access import source_identities
from ai_workshop.labs.rag.conversations.service import _stored_response
from ai_workshop.labs.rag.executions.agent_trace import (
    MAX_CONTENT_CHARACTERS,
    TRACE_STORAGE_KEY,
    AgentContent,
    AgentEvidenceRef,
    AgentTraceCollector,
    capture_agent_trace,
    current_agent_trace,
    next_agent_trace,
    persisted_agent_trace,
    read_agent_trace,
    response_agent_trace,
)
from ai_workshop.labs.rag.executions.read_repository import SqlAlchemyMonitoringRepository
from ai_workshop.labs.rag.executions.schemas import ExecutionSearchRequest
from ai_workshop.labs.rag.executions.service import ExecutionReadService
from ai_workshop.labs.rag.search.schemas import SearchDiagnosticsResponse
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.conversations.test_service import response
from tests.unit.labs.rag.executions.test_generative_trace_authority import reader_fixture
from tests.unit.labs.rag.executions.test_read_service import entry


async def retained_trace():
    source = AgentEvidenceRef(
        document_id=uuid4(), asset_version_id=uuid4(), projection_id=uuid4(),
    )
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        root = await collector.start_span(
            kind="agent", name="synthetic_agent",
            instructions="Synthetic instruction, not a credential",
            input="Synthetic input retained only in execution", evidence_refs=(source,),
        )
        await collector.end_span(root, output="Synthetic observed unvalidated output")
        trace = current_agent_trace()
        masked = response_agent_trace(answer_validated=False)
        assert trace is not None and masked is not None
    return trace, masked, source


async def test_private_output_survives_while_current_response_and_conversation_copy_are_safe():
    trace, masked, source = await retained_trace()
    stored = next_agent_trace(None, trace)
    assert stored is not None
    reread = read_agent_trace({TRACE_STORAGE_KEY: stored})
    assert reread == trace
    assert reread.content_retention == "retained"
    assert reread.spans[0].output.text == "Synthetic observed unvalidated output"
    assert masked.spans[0].output.content_status == "omitted_validation_failure"
    assert "Synthetic observed unvalidated output" not in masked.model_dump_json()

    result = response()
    result.diagnostics = SearchDiagnosticsResponse(
        candidates=[], stages_ms={}, min_keyword_coverage=0.0,
        min_semantic_score=0.0, agent_trace=trace,
    )
    conversation_copy = _stored_response(result)
    metadata = conversation_copy["diagnostics"]["agent_trace"]
    assert metadata["content_retention"] == "metadata_only"
    assert "Synthetic" not in json.dumps(metadata)
    assert source_identities(metadata) == {
        (source.document_id, source.asset_version_id, source.projection_id),
    }
    assert result.diagnostics.agent_trace == trace
    assert persisted_agent_trace(trace).spans[0].input.text is None


@pytest.mark.parametrize("marker", [None, "metadata_only"])
async def test_legacy_payload_cannot_restore_a_body_without_retention_marker(marker):
    trace, _, _ = await retained_trace()
    raw = trace.model_dump(mode="json")
    if marker is None:
        raw.pop("content_retention")
    else:
        raw["content_retention"] = marker
    value = read_agent_trace({TRACE_STORAGE_KEY: raw})
    assert value is not None and value.content_retention == "metadata_only"
    assert "Synthetic" not in value.model_dump_json()
    assert value.spans[0].input.content_status == "not_retained"


@pytest.mark.parametrize("field,value", [
    ("characters", 0), ("sha256", "0" * 64), ("content_status", "not_applicable"),
])
async def test_write_boundary_revalidates_constructed_content_instead_of_trusting_typed_copy(
    field, value,
):
    trace, _, _ = await retained_trace()
    content = trace.spans[0].input.model_copy(update={field: value})
    span = trace.spans[0].model_copy(update={"input": content})
    forged = trace.model_copy(update={"spans": (span,)})
    with pytest.raises(ValueError):
        next_agent_trace(None, forged)


async def test_write_boundary_enforces_total_body_limit_even_with_valid_per_field_digests():
    trace, _, _ = await retained_trace()
    text = "x" * MAX_CONTENT_CHARACTERS
    content = AgentContent(
        content_status="complete", text=text, characters=len(text),
        sha256=hashlib.sha256(text.encode()).hexdigest(),
    )
    empty = AgentContent(content_status="not_applicable")
    root = trace.spans[0]
    spans = tuple(root.model_copy(update={
        "id": root.id if index == 0 else uuid4(),
        "parent_id": None if index == 0 else root.id,
        "sequence": index, "input": content, "instructions": empty, "output": empty,
    }) for index in range(5))
    forged = trace.model_copy(update={"spans": spans})
    with pytest.raises(ValueError):
        next_agent_trace(None, forged)


class SnapshotRepository:
    """Fresh copies model separate database reads, including a change during usage await."""

    def __init__(self, rows, change=None):
        self.rows = rows
        self.change = change
        self.usage_read = False

    async def entries(self, actor):
        for row in self.rows:
            if row.owner_id == actor:
                yield deepcopy(row)

    async def turn_ids(self, actor):
        async for row in self.entries(actor):
            yield row.turn.id

    async def find(self, actor, identity, *, legacy=False):
        return next((deepcopy(row) for row in self.rows
                     if row.owner_id == actor and (
                         row.turn.id == identity if legacy else
                         row.execution is not None and row.execution.id == identity
                     )), None)

    async def usage(self, actor, execution):
        self.usage_read = True
        if self.change is not None:
            self.change()
        return []


class CurrentAccess:
    def __init__(self):
        self.revoked_sources = set()
        self.revoked_turns = set()

    async def visible(self, actor, turn, **kwargs):
        return (turn.id not in self.revoked_turns and
                not source_identities(turn.response).intersection(self.revoked_sources))


async def conversation_fixture():
    actor = uuid4()
    row = entry(actor)
    trace, _, source = await retained_trace()
    now = datetime.now(UTC)
    row.execution = SimpleNamespace(
        id=uuid4(), actor_id=actor, turn_id=row.turn.id, evaluation_attempt_id=None,
        stages={TRACE_STORAGE_KEY: trace.model_dump(mode="json")},
        complete=True, created_at=now, ended_at=now,
    )
    return actor, row, source


async def test_authorized_detail_returns_retained_body_but_list_does_not():
    actor, row, _ = await conversation_fixture()
    service = ExecutionReadService(SnapshotRepository([row]), CurrentAccess())
    detail = await service.detail(actor, row.execution.id)
    assert detail.agent_trace is not None
    assert detail.agent_trace.spans[0].input.text == "Synthetic input retained only in execution"
    listing = await service.search(actor, ExecutionSearchRequest())
    assert listing.total == 1
    assert "Synthetic input retained only in execution" not in listing.model_dump_json()
    assert "agent_trace" not in listing.model_dump_json()


@pytest.mark.parametrize("change", [
    "actor", "execution_id", "turn_binding", "conversation_owner", "source_acl", "dependency_acl",
])
async def test_conversation_detail_rechecks_identity_and_authority_after_usage(change):
    actor, row, source = await conversation_fixture()
    access = CurrentAccess()
    parent = entry(actor)
    parent.conversation_id = row.conversation_id
    row.turn.dependencies = [parent.turn.id]
    identity = row.execution.id

    def mutate():
        if change == "actor":
            row.execution.actor_id = uuid4()
        elif change == "execution_id":
            row.execution.id = uuid4()
        elif change == "turn_binding":
            row.execution.turn_id = uuid4()
        elif change == "conversation_owner":
            row.owner_id = uuid4()
        elif change == "source_acl":
            access.revoked_sources.add((source.document_id, source.asset_version_id,
                                        source.projection_id))
        else:
            access.revoked_turns.add(parent.turn.id)

    repository = SnapshotRepository([row, parent], mutate)
    service = ExecutionReadService(repository, access)
    with pytest.raises(AppError) as denied:
        await service.detail(actor, identity)
    assert denied.value.code == "not_found"
    assert repository.usage_read


@pytest.mark.parametrize("change", ["actor", "execution_id", "attempt_id", "run_id"])
async def test_evaluation_detail_rechecks_exact_link_after_usage(monkeypatch, change):
    env = reader_fixture("running")
    trace, _, _ = await retained_trace()
    span = trace.spans[0].model_copy(update={"evidence_refs": (env.source,)})
    env.execution.stages[TRACE_STORAGE_KEY] = trace.model_copy(
        update={"spans": (span,)},
    ).model_dump(mode="json")
    identity = env.execution.id
    usage_read = False

    async def changed_usage(self, actor, execution):
        nonlocal usage_read
        usage_read = True
        if change == "actor":
            env.execution.actor_id = uuid4()
        elif change == "execution_id":
            env.attempt.execution_id = uuid4()
        elif change == "attempt_id":
            env.execution.evaluation_attempt_id = uuid4()
        else:
            env.attempt.run_id = uuid4()
        return []

    monkeypatch.setattr(SqlAlchemyMonitoringRepository, "usage", changed_usage)
    with pytest.raises(AppError) as denied:
        await env.reader.detail(env.actor, identity)
    assert denied.value.code == "not_found"
    assert usage_read


async def test_evaluation_manifest_change_cannot_authorize_a_previously_captured_body(monkeypatch):
    env = reader_fixture("running")
    trace, _, _ = await retained_trace()
    span = trace.spans[0].model_copy(update={"evidence_refs": (env.source,)})
    env.execution.stages[TRACE_STORAGE_KEY] = trace.model_copy(
        update={"spans": (span,)},
    ).model_dump(mode="json")
    replacement = AgentEvidenceRef(
        document_id=uuid4(), asset_version_id=uuid4(), projection_id=uuid4(),
    )
    usage_read = False

    async def changed_usage(self, actor, execution):
        nonlocal usage_read
        usage_read = True
        # The fresh snapshot is independently visible. The old body's source is not.
        env.run.snapshot["sources"] = [replacement.model_dump(mode="json")]
        env.references[:] = [replacement]
        return []

    monkeypatch.setattr(SqlAlchemyMonitoringRepository, "usage", changed_usage)
    with pytest.raises(AppError) as denied:
        await env.reader.detail(env.actor, env.execution.id)
    assert denied.value.code == "not_found"
    assert usage_read
