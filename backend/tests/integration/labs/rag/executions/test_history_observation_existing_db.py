"""History timing against original PostgreSQL triggers; synthetic writes all roll back."""

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_sessionmaker

import ai_workshop.main  # noqa: F401 -- register existing SQLAlchemy mappings
from ai_workshop.labs.rag.evaluation.generative import (
    GenerativeObservation,
    PrivateGenerativeResult,
)
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_repository import GenerativeRepository, canonical
from ai_workshop.labs.rag.executions.domain import ExecutionIdentity, ExecutionOutcome
from ai_workshop.labs.rag.executions.observer import ExecutionObserver
from ai_workshop.labs.rag.executions.repository import SqlAlchemyExecutionRecorder
from ai_workshop.labs.rag.generation.audit_models import GenerationExecutionAuditRecord
from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
from ai_workshop.shared.db import create_engine
from tests.integration.labs.rag.executions.test_terminal_persistence_existing_db import (
    _fingerprints,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_HISTORY_OBSERVATION_EXISTING_DB") != "1",
        reason="Explicit original database rollback verification is required.",
    ),
]


@pytest.mark.parametrize("early_history", [False, True], ids=["late-reproduction", "early-fix"])
@pytest.mark.parametrize("failure", [False, True], ids=["completed", "failed"])
async def test_history_must_be_recorded_before_the_attempt_terminal_trigger(
    monkeypatch: pytest.MonkeyPatch, early_history: bool, failure: bool,
) -> None:
    """Unit tests cover worker ordering; this proves its persistence boundary in PostgreSQL."""
    for key in list(os.environ):
        if key.upper().startswith("AI_WORKSHOP_"):
            monkeypatch.delenv(key)
    engine = create_engine(load_original_settings(Path(__file__).resolve().parents[6]))
    engine.sync_engine.hide_parameters = True

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(_connection: Connection) -> None:
        raise AssertionError("History observation verification must never COMMIT.")

    run_id, attempt_id, execution_id, audit_id = (uuid4() for _ in range(4))
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            before = await _fingerprints(connection)
            audit_before = await connection.scalar(text(
                "SELECT count(*)::text || ':' || md5(coalesce(string_agg("
                "md5(row_to_json(t)::text), '' ORDER BY md5(row_to_json(t)::text)), '')) "
                "FROM rag_generation_execution_audits t"
            ))
            try:
                inputs = (await connection.execute(text("""
                    SELECT d.id, d.owner_id, p.id AS policy_id
                    FROM rag_evaluation_datasets d JOIN rag_generative_policies p
                    ON p.owner_id=d.owner_id ORDER BY d.created_at LIMIT 1"""))).one()
                case_id = await connection.scalar(text(
                    "SELECT id FROM rag_evaluation_dataset_cases "
                    "WHERE dataset_snapshot_id=:id LIMIT 1"
                ), {"id": inputs.id})
                version = (await connection.execute(text("""
                    SELECT v.id, v.generation_profile_id, a.id AS audit_id
                    FROM rag_configuration_versions v JOIN rag_profiles p
                    ON p.id=v.generation_profile_id JOIN rag_generation_execution_audits a
                    ON a.configuration_version_id=v.id AND a.generation_profile_id=p.id
                    WHERE coalesce((p.config::jsonb#>>'{generation,response_schema_version}')
                    ::int,1) IN (1,2) AND a.policy_allowed IS TRUE LIMIT 1"""))).one()
                assert case_id, "Existing evaluation inputs are required."
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
                )
                snapshot = {"candidates": [{
                    "configuration_version_id": str(version.id),
                    "component_snapshot": {"profiles": [{
                        "id": str(version.generation_profile_id), "kind": "generation",
                    }]},
                }]}
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
                        id=attempt_id, run_id=run_id, configuration_version_id=version.id,
                        case_id=case_id, repetition=0, attempt_number=1, execution_id=execution_id,
                    ))
                repository = GenerativeRepository(sessions)
                token = await repository.claim_run(
                    run_id, {"fixture": "synthetic history rollback"},
                )
                assert token is not None
                assert await repository.claim_attempt(attempt_id, token)
                observer = ExecutionObserver(ExecutionIdentity(
                    execution_id=execution_id, actor_id=inputs.owner_id,
                    evaluation_attempt_id=attempt_id,
                ), SqlAlchemyExecutionRecorder(sessions))
                await observer.start()
                await observer.begin("request")
                if early_history:
                    await observer.end("history", state="skipped", reason="not_executed")
                await observer.end("request")
                # This persistence-only fixture performs no contextualization/search/model call.
                # Explicit skipped observations do not claim that those operations executed.
                for stage in ("contextualization", "retrieval", "selection"):
                    await observer.end(stage, state="skipped", reason="synthetic_fixture")
                await observer.begin("generation")
                error_code = "synthetic_generation_failure" if failure else None
                await observer.end(
                    "generation", state="failed" if failure else "skipped",
                    reason=error_code or "synthetic_fixture",
                )
                await observer.end("citation_validation", state="skipped", reason="not_executed")
                if not failure:
                    async with sessions.begin() as session:
                        template = await session.get(
                            GenerationExecutionAuditRecord, version.audit_id,
                        )
                        assert template is not None
                        session.add(GenerationExecutionAuditRecord(
                            id=audit_id, execution_id=execution_id, actor_id=inputs.owner_id,
                            configuration_version_id=version.id,
                            generation_profile_id=version.generation_profile_id,
                            deployment_version_id=template.deployment_version_id,
                            installation_policy_version_id=template.installation_policy_version_id,
                            provider=template.provider,
                            provider_model_id=template.provider_model_id,
                            location=template.location,
                            external_transfer=False, policy_allowed=True,
                            prompt_ref=template.prompt_ref, prompt_version=template.prompt_version,
                            evidence_ids=[], latency_ms=0, status="allowed", correlation_id=uuid4(),
                            created_at=datetime.now(UTC),
                        ))
                result = PrivateGenerativeResult(observation=GenerativeObservation(
                    execution_id=execution_id,
                    generation_status=None if failure else "insufficient_evidence",
                    error_code=error_code,
                ))
                await observer.begin("persistence")
                query = text("SELECT * FROM rag_executions WHERE id=:id")
                running = (await connection.execute(query, {"id": execution_id})).mappings().one()
                assert running["status"] == "running"
                assert ("history" in running["stages"]) is early_history
                await repository.complete_attempt(attempt_id, token, result, error_code=error_code)
                terminal = (await connection.execute(query, {"id": execution_id})).mappings().one()
                assert terminal["status"] == ("failed" if failure else "completed")
                assert terminal["complete"] is False
                await observer.end("persistence")
                await observer.finish(ExecutionOutcome(
                    state="failed" if failure else "completed", error_code=error_code,
                    answer_status=result.observation.generation_status,
                ))
                saved = (await connection.execute(query, {"id": execution_id})).mappings().one()
                assert saved["complete"] is early_history
                assert saved["stages"]["persistence"]["state"] == "completed"
                if early_history:
                    history = saved["stages"]["history"]
                    assert history["state"] == "skipped" and history["reason"] == "not_executed"
                    assert history["started_at"] is None and history["duration_ms"] is None
                    assert history.get("history_selection") is None
                else:
                    assert "history" not in saved["stages"]  # Terminal writes remain rejected.
                for field in ("status", "answer_status", "error_code", "ended_at"):
                    assert saved[field] == terminal[field]
                async with sessions() as session:
                    attempt = await session.get(GenerativeAttemptRecord, attempt_id)
                    assert attempt is not None
                    assert attempt.result == result.model_dump(mode="json")
                    assert attempt.result_bytes == canonical(attempt.result)
                    assert attempt.result_digest == result.digest()
                await repository.finish_run(run_id, token)
            finally:
                await transaction.rollback()
                assert await _fingerprints(connection) == before
                assert await connection.scalar(text(
                    "SELECT count(*)::text || ':' || md5(coalesce(string_agg("
                    "md5(row_to_json(t)::text), '' ORDER BY md5(row_to_json(t)::text)), '')) "
                    "FROM rag_generation_execution_audits t"
                )) == audit_before
                for table, identity in (
                    ("rag_generative_runs", run_id), ("rag_generative_attempts", attempt_id),
                    ("rag_executions", execution_id), ("rag_generation_execution_audits", audit_id),
                ):
                    assert await connection.scalar(text(
                        f"SELECT count(*) FROM {table} WHERE id=:id"
                    ), {"id": identity}) == 0
                await connection.rollback()
    finally:
        await engine.dispose()
