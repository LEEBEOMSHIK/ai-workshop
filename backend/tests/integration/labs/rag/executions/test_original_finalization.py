"""Opt-in original PostgreSQL checks; synthetic rows never survive outer rollback.

No model, API server, account, database, index or object store is created.
These checks cover SQL persistence/readback, not browser or model failure E2E.
"""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_sessionmaker

import ai_workshop.main  # noqa: F401 -- register existing SQLAlchemy mappings
from ai_workshop.labs.rag.executions.domain import (
    STAGES,
    ExecutionIdentity,
    ExecutionOutcome,
    SelectionObservation,
    StageObservation,
)
from ai_workshop.labs.rag.executions.read_repository import SqlAlchemyMonitoringRepository
from ai_workshop.labs.rag.executions.repository import SqlAlchemyExecutionRecorder
from ai_workshop.labs.rag.executions.service import stages, summary
from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
from ai_workshop.shared.db import create_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_ORIGINAL_FINALIZATION") != "1",
        reason="Explicit original finalization rollback verification is required.",
    ),
]


@pytest.mark.parametrize("trigger_first", [False, True])
@pytest.mark.parametrize("missing_retrieval", [False, True])
async def test_failure_finalization_and_monitoring_readback(
    monkeypatch: pytest.MonkeyPatch, trigger_first: bool, missing_retrieval: bool
) -> None:
    # Discard inherited overrides before the guarded original .env loader.
    for key in list(os.environ):
        if key.upper().startswith("AI_WORKSHOP_"):
            monkeypatch.delenv(key)
    engine = create_engine(load_original_settings(Path(__file__).resolve().parents[6]))

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(_connection: Connection) -> None:
        raise AssertionError("Original finalization verification must never COMMIT.")

    conversation, turn, request = uuid4(), uuid4(), uuid4()
    execution_id = uuid4()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "0061_alias_recovery"
                ), "The original schema must already be 0061; do not migrate in this test."
                actor = await connection.scalar(
                    text("SELECT id FROM users WHERE role='owner' AND is_active LIMIT 1")
                )
                domain = await connection.scalar(
                    text("SELECT id FROM rag_domains ORDER BY created_at LIMIT 1")
                )
                assert actor and domain, "An existing active owner and domain are required."
                await connection.execute(
                    text("""INSERT INTO rag_conversations
                    (id,owner_id,domain_id,title,revision,created_at,updated_at)
                    VALUES (:id,:actor,:domain,'synthetic rollback check',1,now(),now())"""),
                    {"id": conversation, "actor": actor, "domain": domain},
                )
                await connection.execute(
                    text("""INSERT INTO rag_conversation_turns
                    (id,conversation_id,request_id,sequence,status,query,request,request_digest,
                    scope_identity,segment,dependencies,execution_terminated,created_at,updated_at)
                    VALUES (:id,:conversation,:request,1,'running','synthetic','{}',
                    :digest,:digest,1,'[]',false,now(),now())"""),
                    {
                        "id": turn,
                        "conversation": conversation,
                        "request": request,
                        "digest": "0" * 64,
                    },
                )
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                )
                recorder = SqlAlchemyExecutionRecorder(sessions)
                await recorder.start(
                    ExecutionIdentity(execution_id=execution_id, actor_id=actor, turn_id=turn)
                )
                expected: dict[str, object] = {}
                selection = SelectionObservation(
                    candidate_count=3,
                    selected_count=1,
                    min_semantic_score=0.8,
                    serialized_bytes=128,
                )
                for stage in STAGES:
                    if stage == "retrieval" and missing_retrieval:
                        continue
                    observation = StageObservation(
                        stage=stage,
                        state="failed" if stage == "generation" else (
                            "skipped" if stage in {"citation_validation", "persistence"}
                            else "completed"
                        ),
                        reason="generation_failed" if stage == "generation" else None,
                        duration_ms=12.5,
                        selection=selection if stage == "selection" else None,
                    )
                    expected[stage] = observation.model_dump(mode="json")
                    await recorder.record(execution_id, observation)

                async def terminate_turn() -> None:
                    await connection.execute(
                        text("""UPDATE rag_conversation_turns
                        SET status='failed',error_code='generation_failed',
                        execution_terminated=true,updated_at=now() WHERE id=:id"""),
                        {"id": turn},
                    )

                if trigger_first:
                    await terminate_turn()
                await recorder.finish(
                    execution_id, ExecutionOutcome(state="failed", error_code="generation_failed")
                )
                if not trigger_first:
                    await terminate_turn()
                entry = await SqlAlchemyMonitoringRepository(sessions).find(actor, execution_id)
                assert entry is not None and entry.execution is not None
                assert entry.execution.status == "failed"
                assert entry.execution.error_code == "generation_failed"
                assert entry.execution.ended_at is not None
                assert entry.execution.stages == expected
                view = summary(entry)
                assert view.status == "failed" and view.failed_stage == "generation"
                assert view.error_code == "generation_failed"
                assert view.observation_complete is (not missing_retrieval)
                assert view.duration_ms is not None
                observations = {observation.stage: observation for observation in stages(entry)}
                assert observations["selection"].selection == selection
                assert observations["generation"].duration_ms == 12.5
                assert observations["retrieval"].state == (
                    "unrecorded" if missing_retrieval else "completed"
                )
            finally:
                await transaction.rollback()
                # Verify absence through a new transaction, including on assertion failure.
                for table, identity in (
                    ("rag_executions", execution_id),
                    ("rag_conversation_turns", turn),
                    ("rag_conversations", conversation),
                ):
                    assert await connection.scalar(
                        text(f"SELECT count(*) FROM {table} WHERE id=:id"), {"id": identity}
                    ) == 0, "Synthetic verification rows must not survive rollback."
                await connection.rollback()
    finally:
        await engine.dispose()
