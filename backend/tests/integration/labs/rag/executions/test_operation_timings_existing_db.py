"""Original DB stage round-trip: SAVEPOINT writes, outer rollback, no durable rows."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

import ai_workshop.main  # noqa: F401 -- register the existing SQLAlchemy mappings
from ai_workshop.labs.rag.conversations.access import ConversationAccess
from ai_workshop.labs.rag.executions.domain import (
    ExecutionIdentity,
    ExecutionOutcome,
    StageObservation,
)
from ai_workshop.labs.rag.executions.observer import ExecutionObserver, observed_call
from ai_workshop.labs.rag.executions.operation_timings import measure_operation
from ai_workshop.labs.rag.executions.read_repository import SqlAlchemyMonitoringRepository
from ai_workshop.labs.rag.executions.repository import SqlAlchemyExecutionRecorder
from ai_workshop.labs.rag.executions.service import ExecutionReadService
from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
from ai_workshop.shared.db import create_engine
from ai_workshop.shared.errors import AppError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_OPERATION_TIMINGS_EXISTING_DB") != "1",
        reason="Explicit original database rollback verification is required.",
    ),
]

_TABLES = ("users", "rag_domains", "rag_conversations", "rag_conversation_turns", "rag_executions")


async def _fingerprints(connection: AsyncConnection) -> tuple[object, ...]:
    result: list[object] = []
    for table in _TABLES:
        # Only constant identifiers; no existing account or document values leave SQL.
        result.append(await connection.scalar(text(
            "SELECT count(*)::text || ':' || "
            "md5(coalesce(string_agg(md5(row_to_json(t)::text), '' "
            "ORDER BY md5(row_to_json(t)::text)), '')) FROM " + table + " t"
        )))
    return tuple(result)


async def test_operations_and_legacy_json_round_trip_with_owner_checks_and_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in list(os.environ):
        if key.upper().startswith("AI_WORKSHOP_"):
            monkeypatch.delenv(key)
    settings = load_original_settings(Path(__file__).resolve().parents[6])
    engine = create_engine(settings)
    engine.sync_engine.hide_parameters = True

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(_connection: Connection) -> None:
        raise AssertionError("Operation timing verification must never COMMIT.")

    conversation, turn, request, execution = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            before = await _fingerprints(connection)
            try:
                actor = await connection.scalar(
                    text("SELECT id FROM users ORDER BY created_at LIMIT 1")
                )
                domain = await connection.scalar(
                    text("SELECT id FROM rag_domains ORDER BY created_at LIMIT 1")
                )
                assert actor and domain, "An existing account and domain are required."
                await connection.execute(text("""INSERT INTO rag_conversations
                    (id,owner_id,domain_id,title,revision,created_at,updated_at)
                    VALUES (:id,:actor,:domain,'synthetic timing rollback',1,now(),now())"""),
                    {"id": conversation, "actor": actor, "domain": domain},
                )
                await connection.execute(text("""INSERT INTO rag_conversation_turns
                    (id,conversation_id,request_id,sequence,status,query,request,request_digest,
                    scope_identity,segment,dependencies,execution_terminated,created_at,updated_at)
                    VALUES (:id,:conversation,:request,1,'running','synthetic','{}',
                    :digest,:digest,1,'[]',false,now(),now())"""),
                    {"id": turn, "conversation": conversation, "request": request,
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
                # Simulate a past stage without an operations field; do not synthesize zero.
                await recorder.record(execution, StageObservation.model_validate({
                    "stage": "request", "state": "completed",
                }))

                async def work() -> None:
                    await observer.begin("selection")
                    with (
                        measure_operation("selection.context", items=2),
                        measure_operation("keyword.normalize", items=2, reused_items=1),
                        measure_operation("embedding.result_reuse", items=2, reused_items=2),
                    ):
                        pass
                    await observer.end("selection")

                await observed_call(work(), observer)
                await observer.finish(ExecutionOutcome(state="completed"))
                assert observer.complete
                query = text("SELECT stages FROM rag_executions WHERE id=:id")
                stored = await connection.scalar(query, {"id": execution})
                assert "operations" not in stored["request"]
                operations = stored["selection"]["operations"]
                assert {value["name"] for value in operations} == {
                    "selection.context", "keyword.normalize", "embedding.result_reuse",
                }
                assert all(set(value) == {
                    "name", "duration_ms", "calls", "failures", "items", "reused_items",
                } for value in operations)
                reader = ExecutionReadService(
                    SqlAlchemyMonitoringRepository(sessions), ConversationAccess(sessions),
                )
                detail = await reader.detail(actor, execution)
                selected = next(value for value in detail.stages if value.stage == "selection")
                assert selected.operations is not None
                assert [value.model_dump(mode="json") for value in selected.operations] == (
                    operations
                )
                old_stage = next(value for value in detail.stages if value.stage == "request")
                assert old_stage.operations is None
                with pytest.raises(AppError) as denied:
                    await reader.detail(uuid4(), execution)
                assert denied.value.code == "not_found"

                # A late record cannot replace already terminal stage data.
                await recorder.record(execution, StageObservation(
                    stage="selection", state="completed", operations=[],
                ))
                assert await connection.scalar(query, {"id": execution}) == stored
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
