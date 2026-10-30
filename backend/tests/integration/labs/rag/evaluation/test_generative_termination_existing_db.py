"""Termination fencing against the existing DB; all fixture writes roll back."""

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

import ai_workshop.main  # noqa: F401
from ai_workshop.config import get_settings
from ai_workshop.labs.rag.evaluation.generative import (
    GenerativeAcceptancePolicy,
    GenerativeObservation,
    PrivateGenerativeResult,
)
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativePolicyRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_repository import GenerativeRepository, canonical
from ai_workshop.labs.rag.executions.models import ExecutionRecord
from ai_workshop.labs.rag.generation.audit_models import GenerationExecutionAuditRecord
from ai_workshop.shared.db import create_engine
from ai_workshop.shared.errors import AppError


async def test_original_db_unconfirmed_fences_only_pending_siblings_and_rejects_retry():
    engine = create_engine(get_settings())
    created_runs = []
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                dataset = (await connection.execute(text(
                    "SELECT id, owner_id FROM rag_evaluation_datasets LIMIT 1"
                ))).one()
                case = await connection.scalar(text(
                    "SELECT id FROM rag_evaluation_dataset_cases "
                    "WHERE dataset_snapshot_id=:id LIMIT 1"
                ), {"id": dataset.id})
                version_record = (await connection.execute(text(
                    "SELECT v.id, v.generation_profile_id, a.id AS audit_id "
                    "FROM rag_configuration_versions v "
                    "JOIN rag_profiles p ON p.id=v.generation_profile_id "
                    "JOIN rag_generation_execution_audits a "
                    "ON a.configuration_version_id=v.id AND a.generation_profile_id=p.id "
                    "WHERE coalesce((p.config::jsonb#>>'{generation,response_schema_version}')"
                    "::int,1) IN (1,2) AND a.policy_allowed IS TRUE LIMIT 1"
                ))).one()
                version = version_record.id
                assert case and version, "Existing dataset and generation version required"
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
                )
                async with sessions() as bound:
                    assert bound.bind is connection
                    assert bound.sync_session.join_transaction_mode == "create_savepoint"
                policy = GenerativeAcceptancePolicy(
                    version=1, min_context_coverage=1, min_correctness=1, min_abstention=1,
                    max_p95_latency_ms=120000,
                )

                async def create_run(count):
                    run_id, policy_id = uuid4(), uuid4()
                    created_runs.append(run_id)
                    snapshot = {"candidates": [{
                        "configuration_version_id": str(version),
                        "component_snapshot": {"profiles": [{
                            "id": str(version_record.generation_profile_id), "kind": "generation",
                        }]},
                    }]}
                    raw = canonical(snapshot)
                    attempts = [GenerativeAttemptRecord(
                        id=uuid4(), run_id=run_id, configuration_version_id=version,
                        case_id=case, repetition=index, attempt_number=1, execution_id=uuid4(),
                    ) for index in range(count)]
                    async with sessions.begin() as session:
                        session.add(GenerativePolicyRecord(
                            id=policy_id, owner_id=dataset.owner_id, name=f"rollback-{policy_id}",
                            version=1, definition=policy.model_dump(mode="json"),
                            digest=policy.digest(),
                        ))
                        await session.flush()
                        session.add(GenerativeRunRecord(
                            id=run_id, owner_id=dataset.owner_id, request_id=uuid4(),
                            dataset_snapshot_id=dataset.id, policy_id=policy_id,
                            snapshot=snapshot, snapshot_bytes=raw,
                            snapshot_digest=hashlib.sha256(raw).hexdigest(), expected_rules={},
                            rules_digest=hashlib.sha256(canonical({})).hexdigest(),
                            repetition_count=count,
                        ))
                        await session.flush()
                        session.add_all(attempts)
                    return SimpleNamespace(id=run_id, attempts=attempts)

                target, other = await create_run(3), await create_run(2)
                repository = GenerativeRepository(sessions)
                token = await repository.claim_run(target.id, {"fixture": "synthetic rollback"})
                assert token is not None
                previous, current, pending = target.attempts
                assert await repository.claim_attempt(previous.id, token)
                previous_result = PrivateGenerativeResult(observation=GenerativeObservation(
                    execution_id=previous.execution_id, generation_status="insufficient_evidence",
                ))
                async with sessions.begin() as session:
                    session.add(ExecutionRecord(
                        id=previous.execution_id, actor_id=dataset.owner_id,
                        evaluation_attempt_id=previous.id, status="running", stages={},
                    ))
                    await session.flush()
                    template = await session.get(GenerationExecutionAuditRecord,
                                                 version_record.audit_id)
                    assert template is not None
                    session.add(GenerationExecutionAuditRecord(
                        execution_id=previous.execution_id, actor_id=dataset.owner_id,
                        configuration_version_id=version,
                        generation_profile_id=version_record.generation_profile_id,
                        deployment_version_id=template.deployment_version_id,
                        installation_policy_version_id=template.installation_policy_version_id,
                        provider=template.provider, provider_model_id=template.provider_model_id,
                        location=template.location, external_transfer=False, policy_allowed=True,
                        prompt_ref=template.prompt_ref, prompt_version=template.prompt_version,
                        evidence_ids=[], latency_ms=0, status="allowed", correlation_id=uuid4(),
                        created_at=datetime.now(UTC),
                    ))
                await repository.complete_attempt(previous.id, token, previous_result)
                assert await repository.claim_attempt(current.id, token)
                failed_result = PrivateGenerativeResult(observation=GenerativeObservation(
                    execution_id=current.execution_id, failure_stage="generation",
                    error_code="provider_termination_unconfirmed",
                ))
                with pytest.raises(AppError, match="claim"):
                    await repository.complete_attempt(current.id, uuid4(), failed_result,
                                                      error_code="provider_termination_unconfirmed")
                async with sessions() as session:
                    untouched = await session.get(GenerativeAttemptRecord, pending.id)
                    assert untouched.status == "pending"
                    assert (await session.get(GenerativeRunRecord, target.id)).status == "running"
                await repository.complete_attempt(current.id, token, failed_result,
                                                  error_code="provider_termination_unconfirmed")
                async with sessions() as session:
                    run = await session.get(GenerativeRunRecord, target.id)
                    assert run.status == "failed" and run.claim_token is None
                    assert run.finished_at is not None
                    stored_previous = await session.get(GenerativeAttemptRecord, previous.id)
                    stored_current = await session.get(GenerativeAttemptRecord, current.id)
                    stored_pending = await session.get(GenerativeAttemptRecord, pending.id)
                    assert stored_previous.status == "completed"
                    assert stored_previous.result_digest == previous_result.digest()
                    assert stored_current.status == "failed"
                    assert stored_current.result_digest == failed_result.digest()
                    assert stored_current.error_code == "provider_termination_unconfirmed"
                    assert stored_pending.status == "interrupted"
                    assert stored_pending.error_code == "provider_termination_unconfirmed"
                    assert stored_pending.result is None
                    assert stored_pending.result_digest is None
                    assert stored_pending.finished_at is not None
                    assert (await session.get(GenerativeRunRecord, other.id)).status == "pending"
                    for attempt in other.attempts:
                        untouched = await session.get(GenerativeAttemptRecord, attempt.id)
                        assert untouched.status == "pending"
                assert await repository.claim_attempt(pending.id, token) is None
                assert await repository.claim_run(target.id, {}) is None
                assert await repository.heartbeat(target.id, token) is False
                with pytest.raises(AppError, match="claim"):
                    await repository.complete_attempt(current.id, token, failed_result,
                                                      error_code="provider_termination_unconfirmed")
                async with sessions.begin() as session:
                    with pytest.raises(AppError) as denied:
                        await repository.retry_failed(session, dataset.owner_id, target.id)
                    assert denied.value.code == "evaluation_retry_unavailable"
                control = await create_run(2)
                control_token = await repository.claim_run(control.id, {})
                assert control_token is not None
                for attempt in control.attempts:
                    assert await repository.claim_attempt(attempt.id, control_token)
                    result = PrivateGenerativeResult(observation=GenerativeObservation(
                        execution_id=attempt.execution_id, failure_stage="generation",
                        error_code="provider_timeout",
                    ))
                    await repository.complete_attempt(attempt.id, control_token, result,
                                                      error_code="provider_timeout")
                await repository.finish_run(control.id, control_token)
                async with sessions.begin() as session:
                    await repository.retry_failed(session, dataset.owner_id, control.id)
                async with sessions() as session:
                    retry_run = await session.get(GenerativeRunRecord, control.id)
                    retries = (await session.scalars(select(GenerativeAttemptRecord).where(
                        GenerativeAttemptRecord.run_id == control.id,
                    ).order_by(GenerativeAttemptRecord.attempt_number))).all()
                    assert retry_run.status == "pending"
                    assert [attempt.status for attempt in retries] == [
                        "failed", "failed", "pending", "pending",
                    ]
                    assert all(attempt.error_code == "provider_timeout" for attempt in retries[:2])
                    assert await session.get(GenerativeRunRecord, target.id)
            finally:
                await transaction.rollback()
            assert not (await connection.scalars(select(GenerativeRunRecord.id).where(
                GenerativeRunRecord.id.in_(created_runs)
            ))).all()
    finally:
        await engine.dispose()
