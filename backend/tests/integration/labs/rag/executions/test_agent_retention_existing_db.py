"""Real private storage and detail in the original database; every write rolls back."""

import json
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import ai_workshop.main  # noqa: F401
from ai_workshop.config import get_settings
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_monitoring import GenerativeMonitoringReader
from ai_workshop.labs.rag.evaluation.generative_repository import GenerativeRepository
from ai_workshop.labs.rag.executions.agent_trace import (
    TRACE_STORAGE_KEY,
    capture_agent_trace,
    current_agent_trace,
)
from ai_workshop.labs.rag.executions.domain import ExecutionIdentity, ExecutionOutcome
from ai_workshop.labs.rag.executions.models import ExecutionRecord
from ai_workshop.labs.rag.executions.observer import ExecutionObserver, observed_call
from ai_workshop.labs.rag.executions.repository import SqlAlchemyExecutionRecorder
from ai_workshop.shared.db import create_engine
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, request, response, runner


async def test_original_db_retained_sdk_round_trip_and_late_write_all_roll_back():
    engine = create_engine(get_settings())
    run_id, execution_id, attempt_id = uuid4(), uuid4(), uuid4()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
                )
                async with sessions.begin() as session:
                    template_pair = (await session.execute(
                        select(GenerativeRunRecord, GenerativeAttemptRecord)
                        .join(GenerativeAttemptRecord,
                              GenerativeAttemptRecord.run_id == GenerativeRunRecord.id)
                        .where(GenerativeRunRecord.status == "completed")
                        .order_by(GenerativeRunRecord.created_at.desc()).limit(1)
                    )).one()
                    template, template_attempt = template_pair
                    owner = template.owner_id
                    source = template.snapshot["sources"][0]
                    session.add(GenerativeRunRecord(
                        id=run_id, owner_id=owner, request_id=uuid4(),
                        dataset_snapshot_id=template.dataset_snapshot_id,
                        policy_id=template.policy_id,
                        snapshot=template.snapshot, snapshot_bytes=template.snapshot_bytes,
                        snapshot_digest=template.snapshot_digest,
                        expected_rules=template.expected_rules, rules_digest=template.rules_digest,
                        repetition_count=2,
                    ))
                    await session.flush()
                    session.add(GenerativeAttemptRecord(
                        id=attempt_id, run_id=run_id,
                        configuration_version_id=template_attempt.configuration_version_id,
                        case_id=template_attempt.case_id, repetition=0, attempt_number=1,
                        execution_id=execution_id,
                    ))
                repository = GenerativeRepository(sessions)
                token = await repository.claim_run(run_id, {"fixture": "synthetic rollback"})
                assert token and await repository.claim_attempt(attempt_id, token)
                recorder = SqlAlchemyExecutionRecorder(sessions)
                observer = ExecutionObserver(ExecutionIdentity(
                    execution_id=execution_id, actor_id=owner, evaluation_attempt_id=attempt_id,
                ), recorder)
                await observer.start()
                assert observer.persisted_id == execution_id
                selected = request()
                evidence = replace(
                    selected.evidence[0], document_id=UUID(source["document_id"]),
                    asset_version_id=UUID(source["asset_version_id"]),
                    projection_id=UUID(source["projection_id"]),
                )
                selected = replace(selected, evidence=(evidence,))
                calls = []

                def handler(value):
                    calls.append(json.loads(value.content))
                    return response(value, delegate=len(calls) == 1)

                with capture_agent_trace(True):
                    await observed_call(runner(handler).generate(selected, policy=POLICY), observer)
                    captured = current_agent_trace()
                assert captured and observer.complete and len(calls) == 2
                async with sessions() as session:
                    record = await session.get(ExecutionRecord, execution_id)
                    assert record.stages[TRACE_STORAGE_KEY] == captured.model_dump(mode="json")
                detail = await GenerativeMonitoringReader(sessions).detail(owner, execution_id)
                assert detail.agent_trace == captured
                assert len(detail.agent_trace.spans) == 5
                assert detail.agent_trace.spans[0].input.text == calls[0]["messages"][-1]["content"]
                assert detail.agent_trace.spans[-1].input.text
                with pytest.raises(AppError) as denied:
                    await GenerativeMonitoringReader(sessions).detail(uuid4(), execution_id)
                assert denied.value.code == "not_found"
                await observer.finish(ExecutionOutcome(state="failed", error_code="synthetic_end"))
                late = captured.model_copy(update={"revision": captured.revision + 1})
                await recorder.record_agent_trace(execution_id, late)
                async with sessions() as session:
                    record = await session.get(ExecutionRecord, execution_id)
                    assert record.stages[TRACE_STORAGE_KEY] == captured.model_dump(mode="json")
            finally:
                await transaction.rollback()
            for table, identity in (
                (GenerativeRunRecord, run_id), (GenerativeAttemptRecord, attempt_id),
                (ExecutionRecord, execution_id),
            ):
                assert await connection.scalar(select(table.id).where(table.id == identity)) is None
    finally:
        await engine.dispose()
