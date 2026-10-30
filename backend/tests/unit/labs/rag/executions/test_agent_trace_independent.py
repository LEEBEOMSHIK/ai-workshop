"""Independent authorization, storage and asynchronous observation contracts."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx2
import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.conversations.access import source_identities
from ai_workshop.labs.rag.conversations.service import _stored_response
from ai_workshop.labs.rag.executions.agent_trace import (
    TRACE_STORAGE_KEY,
    AgentEvidenceRef,
    AgentTrace,
    AgentTraceCollector,
    capture_agent_trace,
    current_agent_trace,
    next_agent_trace,
    persisted_agent_trace,
    read_agent_trace,
)
from ai_workshop.labs.rag.executions.domain import ExecutionIdentity
from ai_workshop.labs.rag.executions.observer import ExecutionObserver, current_observer
from ai_workshop.labs.rag.executions.repository import SqlAlchemyExecutionRecorder
from ai_workshop.labs.rag.executions.schemas import ExecutionSearchRequest
from ai_workshop.labs.rag.executions.service import ExecutionReadService
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    GenerationTermination,
    tracked_generation_call,
)
from ai_workshop.labs.rag.generation.runtime_resolver import (
    GenerationRuntimeResolver,
    builtin_generation_runtime_factories,
)
from ai_workshop.labs.rag.orchestration.openai_agents import OpenAIAgentsOrchestrator
from ai_workshop.labs.rag.search.schemas import SearchDiagnosticsResponse
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.conversations.test_service import response, seed_conversation
from tests.unit.labs.rag.conversations.test_service import setup as setup
from tests.unit.labs.rag.executions.test_read_service import Repository, entry
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY
from tests.unit.labs.rag.orchestration.test_agents_sdk import request as sdk_request
from tests.unit.labs.rag.orchestration.test_agents_sdk import response as sdk_response
from tests.unit.labs.rag.orchestration.test_agents_sdk import runner as sdk_runner


async def trace_with_source():
    source = AgentEvidenceRef(
        document_id=uuid4(), asset_version_id=uuid4(), projection_id=uuid4(),
    )
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        root = await collector.start_span(
            kind="agent", name="manager", instructions="Synthetic instruction marker",
            input="Synthetic trace-only revoked source marker", evidence_refs=(source,),
        )
        await collector.end_span(root, output="Synthetic output marker")
        value = current_agent_trace()
        assert value is not None
    return value, source


async def test_metadata_copy_and_unmarked_history_strip_bodies_without_mutating_request():
    value, source = await trace_with_source()
    stored = persisted_agent_trace(value)
    legacy = value.model_dump(mode="json")
    legacy.pop("content_retention")
    historical = read_agent_trace({TRACE_STORAGE_KEY: legacy})
    assert historical == stored
    assert "Synthetic" not in stored.model_dump_json()
    assert value.spans[0].input.text is not None
    assert stored.spans[0].evidence_refs == (source,)
    assert stored.spans[0].input.sha256 == value.spans[0].input.sha256
    result = response()
    result.diagnostics = SearchDiagnosticsResponse(
        candidates=[], stages_ms={}, min_keyword_coverage=0.0,
        min_semantic_score=0.0, agent_trace=value,
    )
    body = _stored_response(result)
    assert AgentTrace.model_validate(body["diagnostics"]["agent_trace"]) == stored
    assert source_identities(body) == {
        (source.document_id, source.asset_version_id, source.projection_id),
    }
    assert "Synthetic trace-only" not in json.dumps(body)
    assert result.diagnostics.agent_trace == value


async def test_snapshot_stale_updates_and_terminal_mutation_are_rejected():
    value, _ = await trace_with_source()
    stored = next_agent_trace(None, value)
    assert stored is not None
    assert next_agent_trace(stored, value) is None
    foreign = value.model_copy(update={"run_id": uuid4(), "revision": value.revision + 1})
    with pytest.raises(ValueError, match="identity"):
        next_agent_trace(stored, foreign)
    changed = value.model_copy(update={
        "revision": value.revision + 1,
        "spans": (value.spans[0].model_copy(update={"state": "failed"}),),
    })
    with pytest.raises(ValueError, match="Terminal"):
        next_agent_trace(stored, changed)


class MemorySessions:
    def __init__(self, row):
        self.row = row
        self.queries = []

    @asynccontextmanager
    async def begin(self):
        yield self

    async def scalar(self, query):
        self.queries.append(query)
        return self.row


async def test_repository_preserves_stage_namespace_and_blocks_terminal_trace_writes():
    value, _ = await trace_with_source()
    original_stage = {"stage": "retrieval", "state": "completed"}
    row = SimpleNamespace(status="running", stages={"retrieval": original_stage})
    sessions = MemorySessions(row)
    recorder = SqlAlchemyExecutionRecorder(sessions)
    await recorder.record_agent_trace(uuid4(), value)
    assert row.stages["retrieval"] == original_stage
    assert read_agent_trace(row.stages) == value
    assert "Synthetic trace-only revoked source marker" in json.dumps(row.stages)
    assert "FOR UPDATE" in str(sessions.queries[0])
    before = deepcopy(row.stages)
    row.status = "cancelled"
    await recorder.record_agent_trace(uuid4(), value.model_copy(update={"revision": 99}))
    assert row.stages == before


async def test_observer_write_failure_marks_incomplete_and_never_logs_private_exception(caplog):
    seen = []

    class FailingRecorder:
        async def record_agent_trace(self, execution_id, trace):
            assert "Synthetic instruction marker" in trace.model_dump_json()
            seen.append(trace)
            raise RuntimeError("Synthetic credential and private source marker")

    observer = ExecutionObserver(
        ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), FailingRecorder(),
    )
    token = current_observer.set(observer)
    try:
        with capture_agent_trace(True):
            collector = AgentTraceCollector()
            await collector.start_span(
                kind="agent", name="manager", input="Synthetic instruction marker",
            )
            result = current_agent_trace()
            assert result is not None and not result.observation_complete
            assert not observer.complete
    finally:
        current_observer.reset(token)
    assert len(seen) == 1
    assert "Synthetic" not in caplog.text
    assert "write_failed" in caplog.text


async def test_trace_only_source_revocation_hides_monitoring_list_and_detail():
    actor = uuid4()
    row = entry(actor)
    trace, source = await trace_with_source()
    row.execution = SimpleNamespace(
        id=uuid4(), actor_id=actor, turn_id=row.turn.id, evaluation_attempt_id=None,
        stages={TRACE_STORAGE_KEY: persisted_agent_trace(trace).model_dump(mode="json")},
        complete=True, created_at=datetime.now(UTC), ended_at=datetime.now(UTC),
    )
    forbidden = (source.document_id, source.asset_version_id, source.projection_id)

    class SourceAccess:
        async def visible(self, actor_id, turn, **kwargs):
            return forbidden not in source_identities(turn.response)

    service = ExecutionReadService(Repository([row]), SourceAccess())
    assert (await service.search(actor, ExecutionSearchRequest())).total == 0
    assert await service._current_visible(actor, row.turn.id) is None


async def test_malformed_historical_source_manifest_does_not_break_other_execution_listing():
    actor = uuid4()
    damaged = entry(actor)
    healthy = entry(actor)
    trace, _ = await trace_with_source()
    raw = persisted_agent_trace(trace).model_dump(mode="json")
    raw["spans"][0]["evidence_refs"][0]["projection_id"] = None
    damaged.execution = SimpleNamespace(
        id=uuid4(), actor_id=actor, turn_id=damaged.turn.id, evaluation_attempt_id=None,
        stages={TRACE_STORAGE_KEY: raw}, complete=True,
        created_at=datetime.now(UTC), ended_at=datetime.now(UTC),
    )

    class CurrentSourceAccess:
        async def visible(self, actor_id, turn, **kwargs):
            source_identities(turn.response)
            return True

    service = ExecutionReadService(Repository([damaged, healthy]), CurrentSourceAccess())
    result = await service.search(actor, ExecutionSearchRequest())
    assert any(item.id == healthy.turn.id for item in result.items)
    assert all(item.id != damaged.execution.id for item in result.items)


def test_source_manifest_requires_complete_identity_before_acl_traversal():
    with pytest.raises(ValidationError):
        AgentEvidenceRef(document_id=uuid4(), asset_version_id=uuid4(), projection_id=None)


async def test_request_body_overlay_rechecks_trace_only_source_permission(setup):
    service, _, access, executor, actor, incoming = setup
    value = response()
    trace, source = await trace_with_source()
    value.diagnostics = SearchDiagnosticsResponse(
        candidates=[], stages_ms={}, min_keyword_coverage=0.0,
        min_semantic_score=0.0, agent_trace=trace,
    )
    forbidden = (source.document_id, source.asset_version_id, source.projection_id)
    access.visible.side_effect = lambda owner, turn, **kwargs: (
        forbidden not in source_identities(turn.response)
    )
    executor.execute.return_value = value
    created = await seed_conversation(service, "domain", actor)
    current = await service.submit("domain", actor, created.id, incoming)
    assert "Synthetic trace-only revoked source marker" not in current.model_dump_json()


async def test_overlapping_observer_writes_cannot_regress_request_snapshot_revision():
    delayed = asyncio.Event()
    release = asyncio.Event()

    class DelayingRecorder:
        async def record_agent_trace(self, execution_id, trace):
            if trace.revision == 2:
                delayed.set()
                await release.wait()

    observer = ExecutionObserver(
        ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), DelayingRecorder(),
    )
    token = current_observer.set(observer)
    try:
        with capture_agent_trace(True):
            collector = AgentTraceCollector()
            root = await collector.start_span(kind="agent", name="manager")
            earlier = asyncio.create_task(collector.start_span(
                kind="tool", name="first", parent_id=root,
            ))
            await asyncio.wait_for(delayed.wait(), timeout=1)
            await collector.start_span(kind="tool", name="second", parent_id=root)
            release.set()
            await earlier
            result = current_agent_trace()
            assert result is not None
            assert result.revision == collector.revision
            assert [span.name for span in result.spans] == ["manager", "first", "second"]
    finally:
        release.set()
        current_observer.reset(token)


async def test_sdk_library_logs_do_not_reveal_endpoint_or_nested_private_payload(caplog):
    calls = []

    def handler(value):
        calls.append(value)
        logging.getLogger("openai.agents.tracing").warning("SYNTHETIC_NESTED_PRIVATE_MARKER")
        return sdk_response(value, delegate=len(calls) == 1)

    with caplog.at_level(logging.DEBUG):
        await sdk_runner(handler).generate(sdk_request(), policy=POLICY)
    assert "SYNTHETIC_NESTED_PRIVATE_MARKER" not in caplog.text
    assert "127.0.0.1:11434" not in caplog.text
    assert "PRIVATE_REASONING_CANARY" not in caplog.text


async def test_timeout_closes_partially_received_response_without_claiming_remote_stop():
    class SlowBody(httpx2.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b'{"unfinished":'
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    stream = SlowBody()

    def handler(value):
        return httpx2.Response(200, stream=stream, request=value)

    selected = sdk_request()
    selected = replace(selected, profile=replace(selected.profile, timeout_seconds=0.05))
    termination = GenerationTermination()
    with pytest.raises(GenerationProviderError, match="provider_timeout"):
        await tracked_generation_call(
            sdk_runner(handler).generate(selected, policy=POLICY), termination,
        )
    assert stream.closed
    assert not termination.confirmed


async def test_provider_response_with_nonassistant_role_cannot_delegate():
    calls = []

    def handler(value):
        calls.append(value)
        raw = sdk_response(value, delegate=len(calls) == 1).json()
        raw["choices"][0]["message"]["role"] = "user"
        return httpx2.Response(200, json=raw, request=value)

    with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
        await sdk_runner(handler).generate(sdk_request(), policy=POLICY)
    assert len(calls) == 1


async def test_nonollama_dialect_rejects_ollama_only_reasoning_option_before_model_call():
    calls = []

    def handler(value):
        calls.append(value)
        return sdk_response(value, delegate=len(calls) == 1)

    resolver = GenerationRuntimeResolver(
        environment="test", endpoint_refs={"local-runtime": "http://127.0.0.1:11434"},
        secret_refs={}, factories=builtin_generation_runtime_factories(),
    )
    orchestrator = OpenAIAgentsOrchestrator(
        resolver=resolver, transport_factory=lambda: httpx2.MockTransport(handler),
    )
    selected = sdk_request()
    selected = replace(selected, profile=replace(selected.profile, answer_reasoning_effort="none"))
    with pytest.raises(GenerationProviderError, match="generation_schema_not_supported"):
        await orchestrator.generate(selected, policy=POLICY)
    assert not calls


async def test_authority_revoked_between_manager_and_specialist_stops_second_request():
    calls = []
    checks = 0

    def handler(value):
        calls.append(value)
        return sdk_response(value, delegate=True)

    async def revalidate():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise AppError("source_unavailable", "Source unavailable", 404)

    with capture_agent_trace(True):
        with pytest.raises(AppError) as caught:
            await sdk_runner(handler).generate(
                sdk_request(), policy=POLICY, revalidate=revalidate,
            )
        trace = current_agent_trace()
    assert caught.value.code == "source_unavailable"
    assert checks == 2
    assert len(calls) == 1
    assert trace is not None
    assert all(span.state != "running" for span in trace.spans)
    assert "PRIVATE_REASONING_CANARY" not in trace.model_dump_json()


async def test_receive_cap_stops_stream_before_exhaustion_and_keeps_termination_unconfirmed():
    class OversizedBody(httpx2.AsyncByteStream):
        closed = False
        consumed_chunks = 0

        async def __aiter__(self):
            for _ in range(20):
                self.consumed_chunks += 1
                yield b" " * 65536

        async def aclose(self):
            self.closed = True

    stream = OversizedBody()

    def handler(value):
        return httpx2.Response(200, stream=stream, request=value)

    termination = GenerationTermination()
    with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
        await tracked_generation_call(
            sdk_runner(handler).generate(sdk_request(), policy=POLICY), termination,
        )
    assert stream.closed
    assert stream.consumed_chunks < 20
    assert not termination.confirmed


async def test_ambiguous_duplicate_provider_model_key_is_rejected_before_delegation():
    calls = []

    def handler(value):
        calls.append(value)
        raw = sdk_response(value, delegate=len(calls) == 1).text
        ambiguous = '{"model":"synthetic-unapproved-model",' + raw[1:]
        return httpx2.Response(200, content=ambiguous, request=value)

    with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
        await sdk_runner(handler).generate(sdk_request(), policy=POLICY)
    assert len(calls) == 1
