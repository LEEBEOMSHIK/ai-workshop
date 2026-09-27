"""PostgreSQL proof validation with existing references; all synthetic writes roll back."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

import ai_workshop.main  # noqa: F401
from ai_workshop.config import get_settings
from ai_workshop.labs.rag.evaluation.generative import (
    ClaimCitation,
    ExpectedAnswerRule,
    GenerativeAcceptancePolicy,
    GenerativeObservation,
    PrivateGenerativeResult,
)
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativeJudgmentRecord,
    GenerativePolicyRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_repository import canonical
from ai_workshop.labs.rag.evaluation.models import (
    EvaluationDatasetCaseRecord,
    EvaluationRunConfigurationRecord,
    EvaluationRunRecord,
)
from ai_workshop.labs.rag.executions.models import ExecutionRecord
from ai_workshop.labs.rag.generation.audit_models import GenerationExecutionAuditRecord
from ai_workshop.shared.db import create_engine


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "valid",
        "scalar_only",
        "unreviewed",
        "wrong_citation",
        "missing_repeat",
        "null_rule_version",
        "negative_review_failed",
        "wrong_rule_status",
        "missing_propositions",
        "empty_raw_citations",
        "duplicate_claim_index",
    ],
)
async def test_database_recomputes_complete_generative_proof(mode):
    engine = create_engine(get_settings())
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                sessions = async_sessionmaker(
                    connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )
                async with sessions.begin() as session:
                    assert session.bind is connection
                    candidate = await session.scalar(
                        select(EvaluationRunConfigurationRecord)
                        .where(
                            EvaluationRunConfigurationRecord.generation_profile_id.is_not(None),
                        )
                        .order_by(EvaluationRunConfigurationRecord.created_at.desc())
                        .limit(1)
                    )
                    assert candidate is not None
                    old = await session.get(EvaluationRunRecord, candidate.run_id)
                    cases = (
                        await session.scalars(
                            select(EvaluationDatasetCaseRecord).where(
                                EvaluationDatasetCaseRecord.dataset_snapshot_id
                                == old.dataset_snapshot_id,
                            )
                        )
                    ).all()
                    template = await session.scalar(
                        select(GenerationExecutionAuditRecord)
                        .where(
                            GenerationExecutionAuditRecord.configuration_version_id
                            == candidate.configuration_version_id,
                            GenerationExecutionAuditRecord.policy_allowed.is_(True),
                        )
                        .limit(1)
                    )
                    assert template is not None, "Existing generation audit references required"
                    policy = GenerativeAcceptancePolicy(
                        version=1,
                        min_context_coverage=1,
                        min_correctness=0 if mode == "missing_propositions" else 1,
                        min_abstention=1,
                        max_p95_latency_ms=1000,
                    )
                    rules = {}
                    for case in cases:
                        positive = bool(case.expected_evidence_ids)
                        rules[str(case.id)] = ExpectedAnswerRule(
                            version=1,
                            expected_answer_status="answered"
                            if positive
                            else "insufficient_evidence",
                            required_evidence_groups=tuple(
                                (UUID(v),) for v in case.expected_evidence_ids
                            ),
                            required_propositions=("synthetic approved result",)
                            if positive and mode != "unreviewed"
                            else (),
                        ).model_dump(mode="json")
                    policy_id, run_id = uuid4(), uuid4()
                    if mode == "missing_propositions":
                        for rule in rules.values():
                            rule.pop("required_propositions")
                    if mode == "null_rule_version":
                        next(iter(rules.values()))["version"] = None
                    if mode == "wrong_rule_status":
                        next(iter(rules.values()))["expected_answer_status"] = (
                            "insufficient_evidence"
                        )
                    session.add(
                        GenerativePolicyRecord(
                            id=policy_id,
                            owner_id=old.owner_id,
                            name=f"rollback-{policy_id}",
                            version=1,
                            definition=policy.model_dump(mode="json"),
                            digest=policy.digest(),
                        )
                    )
                    await session.flush()
                    raw = canonical(old.execution_snapshot)
                    run = GenerativeRunRecord(
                        id=run_id,
                        owner_id=old.owner_id,
                        request_id=uuid4(),
                        dataset_snapshot_id=old.dataset_snapshot_id,
                        policy_id=policy_id,
                        snapshot=old.execution_snapshot,
                        snapshot_bytes=raw,
                        snapshot_digest=hashlib.sha256(raw).hexdigest(),
                        expected_rules=rules,
                        rules_digest=hashlib.sha256(canonical(rules)).hexdigest(),
                        repetition_count=2,
                        status="running",
                        claim_token=uuid4(),
                        claimed_at=datetime.now(UTC),
                    )
                    session.add(run)
                    await session.flush()
                    if mode != "scalar_only":
                        for case in cases:
                            for repetition in range(1 if mode == "missing_repeat" else 2):
                                id, execution_id = uuid4(), uuid4()
                                selected = tuple(UUID(v) for v in case.expected_evidence_ids)
                                observation = GenerativeObservation(
                                    execution_id=execution_id,
                                    retrieved_evidence_ids=selected,
                                    selected_evidence_ids=selected,
                                    cited_evidence_ids=(uuid4(),)
                                    if mode == "wrong_citation"
                                    else selected,
                                    generation_status="answered"
                                    if selected
                                    else "insufficient_evidence",
                                    citation_valid=True if selected else None,
                                    duration_ms=50,
                                )
                                result = PrivateGenerativeResult(
                                    observation=observation,
                                    answer="synthetic approved result" if selected else None,
                                    citations=()
                                    if mode == "empty_raw_citations" or not selected
                                    else (
                                        (ClaimCitation(claim_index=0, evidence_ids=selected),)
                                        * (2 if mode == "duplicate_claim_index" else 1)
                                    ),
                                )
                                session.add(
                                    GenerativeAttemptRecord(
                                        id=id,
                                        run_id=run.id,
                                        configuration_version_id=candidate.configuration_version_id,
                                        case_id=case.id,
                                        repetition=repetition,
                                        attempt_number=1,
                                        execution_id=execution_id,
                                        claim_token=run.claim_token,
                                        status="completed",
                                        finished_at=datetime.now(UTC),
                                        result=result.model_dump(mode="json"),
                                        result_bytes=canonical(result.model_dump(mode="json")),
                                        result_digest=result.digest(),
                                    )
                                )
                                await session.flush()
                                session.add(
                                    ExecutionRecord(
                                        id=execution_id,
                                        actor_id=run.owner_id,
                                        evaluation_attempt_id=id,
                                        status="completed",
                                        complete=True,
                                        stages={},
                                        ended_at=datetime.now(UTC),
                                    )
                                )
                                await session.flush()
                                if mode == "negative_review_failed" and not selected:
                                    session.add(
                                        GenerativeJudgmentRecord(
                                            id=uuid4(),
                                            attempt_id=id,
                                            reviewer_id=old.owner_id,
                                            result_digest=result.digest(),
                                            rule_digest=hashlib.sha256(
                                                canonical(rules[str(case.id)])
                                            ).hexdigest(),
                                            status="failed",
                                            reason="Synthetic rejection of the response content",
                                        )
                                    )
                                values = {
                                    column.name: getattr(template, column.name)
                                    for column in GenerationExecutionAuditRecord.__table__.columns
                                    if column.name not in {"id", "created_at", "execution_id"}
                                }
                                values.update(
                                    created_at=datetime.now(UTC),
                                    execution_id=execution_id,
                                    evidence_ids=list(selected),
                                    status="succeeded" if selected else "allowed",
                                )
                                session.add(GenerationExecutionAuditRecord(**values))
                    run.status, run.claim_token, run.claimed_at = "completed", None, None
                    run.finished_at = datetime.now(UTC)
                query = text("SELECT rag_verify_generative_candidate(:run,:version)")
                if mode == "valid":
                    metrics = await connection.scalar(
                        query, {"run": run_id, "version": candidate.configuration_version_id}
                    )
                    assert metrics["correctness"] == 1
                    assert metrics["duration_count"] == len(cases) * 2
                    from ai_workshop.labs.rag.configurations.repository import (
                        SqlAlchemyRagConfigurationRepository,
                    )

                    async with sessions.begin() as session:
                        accepted = await SqlAlchemyRagConfigurationRepository(
                            session
                        ).accept_generative_evaluation(
                            version_id=candidate.configuration_version_id,
                            evaluation_run_id=run_id,
                            actor_id=old.owner_id,
                        )
                        assert accepted["correctness"] == 1
                else:
                    with pytest.raises(DBAPIError):
                        async with connection.begin_nested():
                            await connection.execute(
                                query,
                                {"run": run_id, "version": candidate.configuration_version_id},
                            )
            finally:
                await outer.rollback()
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
