"""Original DB timing round-trip using mock SDK calls and mandatory outer rollback."""

import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import httpx2
import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_sessionmaker

import ai_workshop.main  # noqa: F401 -- register existing mappings
from ai_workshop.labs.rag.conversations.access import ConversationAccess
from ai_workshop.labs.rag.executions.agent_trace import (
    TRACE_STORAGE_KEY,
    capture_agent_trace,
    current_agent_trace,
)
from ai_workshop.labs.rag.executions.domain import ExecutionIdentity, ExecutionOutcome
from ai_workshop.labs.rag.executions.observer import ExecutionObserver, observed_call
from ai_workshop.labs.rag.executions.read_repository import SqlAlchemyMonitoringRepository
from ai_workshop.labs.rag.executions.repository import SqlAlchemyExecutionRecorder
from ai_workshop.labs.rag.executions.service import ExecutionReadService
from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
from ai_workshop.labs.rag.models.context_evidence import EvidenceBudget
from ai_workshop.shared.db import create_engine
from ai_workshop.shared.errors import AppError
from tests.integration.labs.rag.executions.test_operation_timings_existing_db import _fingerprints
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, request, response, runner
from tests.unit.labs.rag.orchestration.test_ollama_native_independent import native_payload
from tests.unit.labs.rag.orchestration.test_reference_packing_independent import alias_answer

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_MODEL_TIMINGS_EXISTING_DB") != "1",
        reason="Explicit original database rollback verification is required.",
    ),
]


@pytest.mark.parametrize("native", [False, True])
async def test_model_timing_storage_owner_detail_legacy_and_rollback(monkeypatch, native):
    for key in list(os.environ):
        if key.upper().startswith("AI_WORKSHOP_"):
            monkeypatch.delenv(key)
    settings = load_original_settings(Path(__file__).resolve().parents[6])
    engine = create_engine(settings)
    engine.sync_engine.hide_parameters = True

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(_connection: Connection) -> None:
        raise AssertionError("Model timing verification must never COMMIT.")

    conversation, turn, request_id, execution = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            before = await _fingerprints(connection)
            try:
                # Read identities only; original document bodies never enter the fixture.
                baseline = (await connection.execute(text(
                    "SELECT owner_id, snapshot->'sources'->0 FROM rag_generative_runs "
                    "WHERE status='completed' ORDER BY created_at DESC LIMIT 1"
                ))).one()
                actor, source = baseline
                domain = await connection.scalar(text(
                    "SELECT id FROM rag_domains ORDER BY created_at LIMIT 1"
                ))
                assert actor and source and domain
                await connection.execute(text("""INSERT INTO rag_conversations
                    (id,owner_id,domain_id,title,revision,created_at,updated_at)
                    VALUES (:id,:actor,:domain,'synthetic model timing rollback',1,now(),now())"""),
                    {"id": conversation, "actor": actor, "domain": domain},
                )
                await connection.execute(text("""INSERT INTO rag_conversation_turns
                    (id,conversation_id,request_id,sequence,status,query,request,request_digest,
                    scope_identity,segment,dependencies,execution_terminated,created_at,updated_at)
                    VALUES (:id,:conversation,:request,1,'running','synthetic','{}',
                    :digest,:digest,1,'[]',false,now(),now())"""),
                    {"id": turn, "conversation": conversation, "request": request_id,
                     "digest": "0" * 64},
                )
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
                )
                recorder = SqlAlchemyExecutionRecorder(sessions)
                observer = ExecutionObserver(ExecutionIdentity(
                    execution_id=execution, actor_id=actor, turn_id=turn,
                ), recorder)
                await observer.start()
                assert observer.persisted_id == execution
                selected = request(local_http_api="ollama_chat") if native else request()
                selected = replace(selected, profile=replace(
                    selected.profile, prompt_ref="rag-answer-v6",
                    evidence_budget=EvidenceBudget(8, 32, 12000),
                ))
                selected = replace(selected, evidence=(replace(
                    selected.evidence[0], document_id=UUID(source["document_id"]),
                    asset_version_id=UUID(source["asset_version_id"]),
                    projection_id=UUID(source["projection_id"]),
                ),))
                calls = []

                def handler(value):
                    calls.append(value)
                    if native:
                        payload = native_payload(value, delegate=len(calls) == 1)
                        if len(calls) == 2:
                            payload["message"]["content"] = json.dumps(alias_answer())
                        return httpx2.Response(
                            200, json=payload, request=value,
                        )
                    return response(value, delegate=len(calls) == 1, content=alias_answer())

                with capture_agent_trace(True):
                    await observed_call(runner(handler).generate(selected, policy=POLICY), observer)
                    captured = current_agent_trace()
                await observer.finish(ExecutionOutcome(state="completed"))
                assert captured and observer.complete and len(calls) == 2
                query = text("SELECT stages FROM rag_executions WHERE id=:id")
                stored = await connection.scalar(query, {"id": execution})
                assert stored[TRACE_STORAGE_KEY] == captured.model_dump(mode="json")
                reader = ExecutionReadService(
                    SqlAlchemyMonitoringRepository(sessions), ConversationAccess(sessions),
                )
                detail = await reader.detail(actor, execution)
                assert detail.agent_trace == captured
                models = [span for span in detail.agent_trace.spans if span.kind == "model"]
                assert len(models) == 2 and all(span.model_timing is not None for span in models)
                assert models[0].citation_reference_map is None
                assert models[1].citation_reference_map.evidence_ids == (
                    selected.evidence[0].evidence_id,
                )
                assert json.loads(models[1].output.text)["claims"][0]["evidence_ids"] == ["e1"]
                specialist = next(span for span in detail.agent_trace.spans
                                  if span.id == models[1].parent_id)
                assert json.loads(specialist.output.text)["claims"][0]["evidence_ids"] == [
                    str(selected.evidence[0].evidence_id),
                ]
                for span in models:
                    assert span.model_timing.api == (
                        "ollama_chat" if native else "openai_chat_completions"
                    )
                    assert span.model_timing.server_timing_status == (
                        "available" if native else "not_exposed_by_non_streaming_api"
                    )
                    if native:
                        assert span.model_timing.server_timing.load_ms == 3.0
                with pytest.raises(AppError) as denied:
                    await reader.detail(uuid4(), execution)
                assert denied.value.code == "not_found"
                await recorder.record_agent_trace(
                    execution, captured.model_copy(update={"revision": captured.revision + 1}),
                )
                assert await connection.scalar(query, {"id": execution}) == stored
                # Simulate historical JSON on this synthetic row only, inside outer rollback.
                for span in stored[TRACE_STORAGE_KEY]["spans"]:
                    span.pop("model_timing", None)
                    span.pop("citation_reference_map", None)
                await connection.execute(text(
                    "UPDATE rag_executions SET stages=CAST(:stages AS json) WHERE id=:id"
                ), {"id": execution, "stages": json.dumps(stored)})
                legacy_detail = await reader.detail(actor, execution)
                assert all(span.model_timing is None for span in legacy_detail.agent_trace.spans)
                assert all(span.citation_reference_map is None
                           for span in legacy_detail.agent_trace.spans)
            finally:
                await transaction.rollback()
            for table, created_id in (
                ("rag_conversations", conversation), ("rag_conversation_turns", turn),
                ("rag_executions", execution),
            ):
                assert await connection.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE id=:id"), {"id": created_id},
                ) == 0
            assert await _fingerprints(connection) == before
            await connection.rollback()
    finally:
        await engine.dispose()
