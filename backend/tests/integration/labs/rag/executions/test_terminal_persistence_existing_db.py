"""Existing PostgreSQL trigger regression; savepoints only, outer rollback mandatory."""

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

import ai_workshop.main  # noqa: F401 -- register the existing SQLAlchemy mappings
from ai_workshop.labs.rag.evaluation.generative import (
    GenerativeObservation,
    PrivateGenerativeResult,
)
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_repository import GenerativeRepository, canonical
from ai_workshop.labs.rag.executions.domain import (
    STAGES,
    ExecutionIdentity,
    ExecutionOutcome,
    StageObservation,
)
from ai_workshop.labs.rag.executions.repository import SqlAlchemyExecutionRecorder
from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
from ai_workshop.shared.db import create_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_TERMINAL_PERSISTENCE_EXISTING_DB") != "1",
        reason="Explicit original database rollback verification is required.",
    ),
]

_TABLES = (
    "users", "rag_domains", "rag_conversations", "rag_conversation_turns", "rag_executions",
    "rag_generative_runs", "rag_generative_attempts", "rag_generative_policies",
    "rag_evaluation_datasets", "rag_evaluation_dataset_cases", "rag_configuration_versions",
)


async def _fingerprints(connection: AsyncConnection) -> tuple[object, ...]:
    result = []
    for table in _TABLES:
        result.append(await connection.scalar(text(
            "SELECT count(*)::text || ':' || "
            "md5(coalesce(string_agg(md5(row_to_json(t)::text), '' "
            "ORDER BY md5(row_to_json(t)::text)), '')) FROM " + table + " t"
        )))
    return tuple(result)


@pytest.mark.parametrize("status,gap", [
    ("completed", None), ("failed", None), ("cancelled", None), ("interrupted", None),
    ("completed", "retrieval"), ("cancelled", "pending"),
    ("completed", "deleted"), ("completed", "parent_mismatch"),
])
async def test_trigger_finalized_turn_closes_only_matching_started_persistence(
    monkeypatch: pytest.MonkeyPatch, status: str, gap: str | None,
) -> None:
    for key in list(os.environ):
        if key.upper().startswith("AI_WORKSHOP_"):
            monkeypatch.delenv(key)
    engine = create_engine(load_original_settings(Path(__file__).resolve().parents[6]))
    engine.sync_engine.hide_parameters = True

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(_connection: Connection) -> None:
        raise AssertionError("Terminal persistence verification must never COMMIT.")

    conversation, turn, request, execution = uuid4(), uuid4(), uuid4(), uuid4()
    started = datetime.now(UTC)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            before = await _fingerprints(connection)
            try:
                actor = await connection.scalar(text(
                    "SELECT id FROM users WHERE role='owner' AND is_active LIMIT 1"
                ))
                domain = await connection.scalar(text(
                    "SELECT id FROM rag_domains ORDER BY created_at LIMIT 1"
                ))
                assert actor and domain, "An existing active owner and domain are required."
                await connection.execute(text("""INSERT INTO rag_conversations
                    (id,owner_id,domain_id,title,revision,created_at,updated_at)
                    VALUES (:id,:actor,:domain,'synthetic persistence rollback',1,now(),now())"""),
                    {"id": conversation, "actor": actor, "domain": domain})
                await connection.execute(text("""INSERT INTO rag_conversation_turns
                    (id,conversation_id,request_id,sequence,status,query,request,request_digest,
                    scope_identity,segment,dependencies,execution_terminated,created_at,updated_at)
                    VALUES (:id,:conversation,:request,1,'running','synthetic','{}',
                    :digest,:digest,1,'[]',false,now(),now())"""),
                    {"id": turn, "conversation": conversation, "request": request,
                     "digest": "0" * 64})
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                )
                recorder = SqlAlchemyExecutionRecorder(sessions)
                await recorder.start(ExecutionIdentity(
                    execution_id=execution, actor_id=actor, turn_id=turn,
                ))
                for stage in STAGES:
                    if stage == gap:
                        continue
                    await recorder.record(execution, StageObservation(
                        stage=stage,
                        state=("pending" if gap == "pending" else "running")
                        if stage == "persistence" else "completed",
                        started_at=started,
                    ))
                await connection.execute(text("""UPDATE rag_conversation_turns
                    SET status=:status, error_code=:error, execution_terminated=true,
                    updated_at=now() WHERE id=:id"""),
                    {"id": turn, "status": status,
                     "error": None if status == "completed" else "synthetic_failure"})
                query = text("SELECT * FROM rag_executions WHERE id=:id")
                terminal = (await connection.execute(query, {"id": execution})).mappings().one()
                assert terminal["status"] == status
                assert terminal["complete"] is False
                assert terminal["stages"]["persistence"]["state"] == (
                    "pending" if gap == "pending" else "running"
                )
                if gap == "deleted":
                    await connection.execute(text(
                        "UPDATE rag_conversations SET deleted_at=now() WHERE id=:id"
                    ), {"id": conversation})
                elif gap == "parent_mismatch":
                    # The trigger preserves terminal executions; emulate an inconsistent parent.
                    await connection.execute(text(
                        "UPDATE rag_conversation_turns SET status='failed' WHERE id=:id"
                    ), {"id": turn})
                end = StageObservation(
                    stage="persistence", state="completed", started_at=started,
                    ended_at=started + timedelta(milliseconds=12), duration_ms=12.0, operations=[],
                )
                await recorder.record(execution, end)
                await recorder.finish(execution, ExecutionOutcome(state=status))
                saved = (await connection.execute(query, {"id": execution})).mappings().one()
                expected_state = (
                    "pending" if gap == "pending" else "running"
                    if gap in {"deleted", "parent_mismatch"} else "completed"
                )
                assert saved["stages"]["persistence"]["state"] == expected_state
                assert saved["complete"] is (gap is None)
                for field in ("status", "answer_status", "error_code", "ended_at"):
                    assert saved[field] == terminal[field]
                await recorder.record(execution, end.model_copy(update={"duration_ms": 999.0}))
                await recorder.record(
                    execution, StageObservation(stage="selection", state="failed"),
                )
                repeat = (await connection.execute(query, {"id": execution})).mappings().one()
                assert repeat["stages"] == saved["stages"]
            finally:
                await transaction.rollback()
                assert await _fingerprints(connection) == before
                for table, identity in (
                    ("rag_conversations", conversation), ("rag_conversation_turns", turn),
                    ("rag_executions", execution),
                ):
                    assert await connection.scalar(text(
                        f"SELECT count(*) FROM {table} WHERE id=:id"
                    ), {"id": identity}) == 0
                await connection.rollback()
    finally:
        await engine.dispose()


@pytest.mark.parametrize("status,gap", [
    ("completed", None), ("failed", None), ("interrupted", None),
    ("failed", "unobserved"), ("failed", "started_at"), ("failed", "execution"),
    ("failed", "owner"), ("failed", "parent_status"),
])
async def test_trigger_finalized_attempt_closes_only_exact_owned_persistence(
    monkeypatch: pytest.MonkeyPatch, status: str, gap: str | None,
) -> None:
    for key in list(os.environ):
        if key.upper().startswith("AI_WORKSHOP_"):
            monkeypatch.delenv(key)
    engine = create_engine(load_original_settings(Path(__file__).resolve().parents[6]))
    engine.sync_engine.hide_parameters = True

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(_connection: Connection) -> None:
        raise AssertionError("Terminal persistence verification must never COMMIT.")

    run_id, attempt_id, execution_id, other_execution = (uuid4() for _ in range(4))
    started = datetime.now(UTC)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            before = await _fingerprints(connection)
            try:
                inputs = (await connection.execute(text("""
                    SELECT d.id, d.owner_id, p.id AS policy_id
                    FROM rag_evaluation_datasets d JOIN rag_generative_policies p
                    ON p.owner_id=d.owner_id ORDER BY d.created_at LIMIT 1"""))).one()
                case = await connection.scalar(text(
                    "SELECT id FROM rag_evaluation_dataset_cases "
                    "WHERE dataset_snapshot_id=:id LIMIT 1"
                ), {"id": inputs.id})
                version = await connection.scalar(text(
                    "SELECT id FROM rag_configuration_versions "
                    "WHERE generation_profile_id IS NOT NULL LIMIT 1"
                ))
                assert case and version, "Existing evaluation inputs are required."
                other_actor = await connection.scalar(text(
                    "SELECT id FROM users WHERE id<>:id LIMIT 1"
                ), {"id": inputs.owner_id})
                if gap == "owner" and other_actor is None:
                    pytest.skip("Another existing actor is required for the owner rejection case.")
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
                )
                snapshot = {"candidates": [{"configuration_version_id": str(version)}]}
                raw = canonical(snapshot)
                async with sessions.begin() as session:
                    session.add(GenerativeRunRecord(
                        id=run_id, owner_id=inputs.owner_id, request_id=uuid4(),
                        dataset_snapshot_id=inputs.id, policy_id=inputs.policy_id,
                        snapshot=snapshot, snapshot_bytes=raw,
                        snapshot_digest=hashlib.sha256(raw).hexdigest(), expected_rules={},
                        rules_digest=hashlib.sha256(canonical({})).hexdigest(), repetition_count=2,
                    ))
                    await session.flush()
                    session.add(GenerativeAttemptRecord(
                        id=attempt_id, run_id=run_id, configuration_version_id=version,
                        case_id=case, repetition=0, attempt_number=1, execution_id=execution_id,
                    ))
                repository = GenerativeRepository(sessions)
                token = await repository.claim_run(run_id, {"fixture": "synthetic rollback"})
                assert token is not None
                assert await repository.claim_attempt(attempt_id, token)
                recorder = SqlAlchemyExecutionRecorder(sessions)
                await recorder.start(ExecutionIdentity(
                    execution_id=execution_id, actor_id=inputs.owner_id,
                    evaluation_attempt_id=attempt_id,
                ))
                for stage in STAGES:
                    if gap == "unobserved" and stage in {"history", "citation_validation"}:
                        continue
                    await recorder.record(execution_id, StageObservation(
                        stage=stage, started_at=started,
                        state="running" if stage == "persistence" else "failed"
                        if stage == "generation" and status == "failed" else "completed",
                    ))
                result = PrivateGenerativeResult(observation=GenerativeObservation(
                    execution_id=execution_id, generation_status="insufficient_evidence"
                    if status == "completed" else None,
                    error_code=None if status == "completed" else "synthetic_failure",
                ))
                if status == "failed":
                    # Exercise the actual failure-saving transaction that precedes observer.end.
                    await repository.complete_attempt(
                        attempt_id, token, result, error_code="synthetic_failure",
                    )
                    await repository.finish_run(run_id, token)
                else:
                    async with sessions.begin() as session:
                        parent = await session.get(GenerativeAttemptRecord, attempt_id)
                        assert parent is not None
                        parent.status, parent.finished_at = status, datetime.now(UTC)
                        parent.error_code = None if status == "completed" else "synthetic_failure"
                        parent.result = result.model_dump(mode="json")
                        parent.result_bytes = canonical(parent.result)
                        parent.result_digest = result.digest()
                if gap == "execution":
                    await connection.execute(text(
                        "UPDATE rag_executions SET id=:other WHERE id=:id"
                    ), {"id": execution_id, "other": other_execution})
                    execution_id = other_execution
                elif gap == "owner":
                    await connection.execute(text(
                        "UPDATE rag_executions SET actor_id=:actor WHERE id=:id"
                    ), {"id": execution_id, "actor": other_actor})
                elif gap == "parent_status":
                    await connection.execute(text(
                        "UPDATE rag_executions SET status='completed' WHERE id=:id"
                    ), {"id": execution_id})
                query = text("SELECT * FROM rag_executions WHERE id=:id")
                terminal = (await connection.execute(query, {"id": execution_id})).mappings().one()
                assert terminal["status"] == ("completed" if gap == "parent_status" else status)
                assert terminal["stages"]["persistence"]["state"] == "running"
                assert terminal["complete"] is False
                parents_before = []
                for table, identity in (("rag_generative_runs", run_id),
                                        ("rag_generative_attempts", attempt_id)):
                    parents_before.append(await connection.scalar(text(
                        f"SELECT to_jsonb(t) FROM {table} t WHERE id=:id"
                    ), {"id": identity}))
                end = StageObservation(
                    stage="persistence", state="completed",
                    started_at=started + timedelta(milliseconds=1)
                    if gap == "started_at" else started,
                    ended_at=started + timedelta(milliseconds=12), duration_ms=12.0, operations=[],
                )
                await recorder.record(execution_id, end)
                await recorder.finish(execution_id, ExecutionOutcome(state=status))
                saved = (await connection.execute(query, {"id": execution_id})).mappings().one()
                assert saved["stages"]["persistence"]["state"] == (
                    "completed" if gap in {None, "unobserved"} else "running"
                )
                assert saved["complete"] is (gap is None)
                assert {k: v for k, v in saved["stages"].items() if k != "persistence"} == {
                    k: v for k, v in terminal["stages"].items() if k != "persistence"
                }
                for field in ("status", "answer_status", "error_code", "ended_at"):
                    assert saved[field] == terminal[field]
                for index, (table, identity) in enumerate((
                    ("rag_generative_runs", run_id), ("rag_generative_attempts", attempt_id),
                )):
                    assert await connection.scalar(text(
                        f"SELECT to_jsonb(t) FROM {table} t WHERE id=:id"
                    ), {"id": identity}) == parents_before[index]
                await recorder.record(execution_id, end.model_copy(update={"duration_ms": 999.0}))
                await recorder.record(
                    execution_id, StageObservation(stage="selection", state="failed"),
                )
                repeated = (await connection.execute(query, {"id": execution_id})).mappings().one()
                assert repeated["stages"] == saved["stages"]
            finally:
                await transaction.rollback()
                assert await _fingerprints(connection) == before
                for table, identity in (
                    ("rag_generative_runs", run_id), ("rag_generative_attempts", attempt_id),
                    ("rag_executions", execution_id),
                ):
                    assert await connection.scalar(text(
                        f"SELECT count(*) FROM {table} WHERE id=:id"
                    ), {"id": identity}) == 0
                await connection.rollback()
    finally:
        await engine.dispose()
