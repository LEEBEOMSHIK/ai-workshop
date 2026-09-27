"""Existing connection only; every write rolls back, including successful commits."""

import hashlib
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
from ai_workshop.shared.db import create_engine
from ai_workshop.shared.errors import AppError


@pytest.mark.asyncio
async def test_original_db_duplicate_and_stale_claims_preserve_terminal_attempt():
    engine = create_engine(get_settings())
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                dataset = (
                    await connection.execute(
                        text("SELECT id, owner_id FROM rag_evaluation_datasets LIMIT 1")
                    )
                ).one()
                case = await connection.scalar(
                    text(
                        "SELECT id FROM rag_evaluation_dataset_cases "
                        "WHERE dataset_snapshot_id=:id LIMIT 1"
                    ),
                    {"id": dataset.id},
                )
                version = await connection.scalar(
                    text(
                        "SELECT id FROM rag_configuration_versions "
                        "WHERE generation_profile_id IS NOT NULL LIMIT 1"
                    )
                )
                assert case and version, (
                    "Existing synthetic dataset and generation version required"
                )
                sessions = async_sessionmaker(
                    connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )
                async with sessions() as bound:
                    assert bound.bind is connection
                    assert bound.sync_session.join_transaction_mode == "create_savepoint"
                policy = GenerativeAcceptancePolicy(
                    version=1,
                    min_context_coverage=1,
                    min_correctness=1,
                    min_abstention=1,
                    max_p95_latency_ms=100000,
                )
                run_id, attempt_id, execution_id, policy_id = (uuid4() for _ in range(4))
                snapshot = {"candidates": [{"configuration_version_id": str(version)}]}
                raw = canonical(snapshot)
                async with sessions.begin() as session:
                    session.add(
                        GenerativePolicyRecord(
                            id=policy_id,
                            owner_id=dataset.owner_id,
                            name=f"rollback-{policy_id}",
                            version=1,
                            definition=policy.model_dump(mode="json"),
                            digest=policy.digest(),
                        )
                    )
                    await session.flush()
                    session.add(
                        GenerativeRunRecord(
                            id=run_id,
                            owner_id=dataset.owner_id,
                            request_id=uuid4(),
                            dataset_snapshot_id=dataset.id,
                            policy_id=policy_id,
                            snapshot=snapshot,
                            snapshot_bytes=raw,
                            snapshot_digest=hashlib.sha256(raw).hexdigest(),
                            expected_rules={},
                            rules_digest=hashlib.sha256(canonical({})).hexdigest(),
                            repetition_count=2,
                        )
                    )
                    await session.flush()
                    session.add(
                        GenerativeAttemptRecord(
                            id=attempt_id,
                            run_id=run_id,
                            configuration_version_id=version,
                            case_id=case,
                            repetition=0,
                            attempt_number=1,
                            execution_id=execution_id,
                        )
                    )
                repository = GenerativeRepository(sessions)
                token = await repository.claim_run(run_id, {"fixture": "synthetic rollback"})
                assert token is not None
                assert await repository.claim_run(run_id, {}) is None
                assert await repository.claim_attempt(attempt_id, uuid4()) is None
                assert await repository.claim_attempt(attempt_id, token) is not None
                assert await repository.claim_attempt(attempt_id, token) is None
                result = PrivateGenerativeResult(
                    observation=GenerativeObservation(
                        execution_id=execution_id,
                        failure_stage="generation",
                        error_code="provider_timeout",
                    )
                )
                with pytest.raises(AppError, match="claim"):
                    await repository.complete_attempt(attempt_id, uuid4(), result)
                await repository.complete_attempt(
                    attempt_id,
                    token,
                    result,
                    error_code="provider_timeout",
                )
                with pytest.raises(AppError, match="claim"):
                    await repository.complete_attempt(attempt_id, token, result)
                async with sessions() as session:
                    stored = await session.scalar(
                        select(GenerativeAttemptRecord).where(
                            GenerativeAttemptRecord.id == attempt_id,
                        )
                    )
                    assert stored.status == "failed"
                    assert stored.result_digest == result.digest()
                await repository.finish_run(run_id, token)
                async with sessions.begin() as session:
                    await repository.retry_failed(session, dataset.owner_id, run_id)
                async with sessions() as session:
                    attempts = (
                        await session.scalars(
                            select(GenerativeAttemptRecord)
                            .where(
                                GenerativeAttemptRecord.run_id == run_id,
                            )
                            .order_by(GenerativeAttemptRecord.attempt_number)
                        )
                    ).all()
                    assert [a.status for a in attempts] == ["failed", "pending"]
                    assert attempts[0].result_digest == result.digest()
                    assert attempts[1].execution_id != execution_id
                fresh = await repository.claim_run(run_id, {})
                assert fresh is not None
                assert await repository.claim_attempt(attempts[1].id, fresh) is not None
                from datetime import UTC, datetime, timedelta

                assert await repository.heartbeat(run_id, token) is False
                assert await repository.heartbeat(run_id, fresh) is True
                assert (
                    await repository.interrupt_stale(datetime.now(UTC) - timedelta(minutes=10)) == 0
                )
                assert (
                    await repository.interrupt_stale(datetime.now(UTC) + timedelta(minutes=1)) == 1
                )
                with pytest.raises(AppError, match="claim"):
                    await repository.complete_attempt(attempts[1].id, fresh, result)
                async with sessions() as session:
                    expired = await session.get(GenerativeAttemptRecord, attempts[1].id)
                    assert expired.status == "interrupted"
                    assert expired.error_code == "evaluation_worker_interrupted"
            finally:
                await transaction.rollback()
            # The outer rollback must also undo repository-level session commits.
            assert (
                await connection.scalar(
                    select(GenerativeRunRecord.id).where(
                        GenerativeRunRecord.id == run_id,
                    )
                )
                is None
            )
    finally:
        await engine.dispose()
