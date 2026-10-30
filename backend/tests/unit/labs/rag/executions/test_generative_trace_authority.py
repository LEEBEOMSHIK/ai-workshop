"""Real evaluation readers with a synthetic SQL boundary; no DB or model calls."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.evaluation.generative import (
    ClaimCitation,
    ExpectedAnswerRule,
    GenerativeObservation,
    PrivateGenerativeResult,
)
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativeJudgmentRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_monitoring import GenerativeMonitoringReader
from ai_workshop.labs.rag.evaluation.models import EvaluationDatasetCaseRecord
from ai_workshop.labs.rag.executions.agent_trace import (
    TRACE_STORAGE_KEY,
    AgentContent,
    AgentEvidenceRef,
    AgentSpan,
    AgentTrace,
)
from ai_workshop.labs.rag.executions.models import ExecutionRecord
from ai_workshop.labs.rag.generation.audit_models import GenerationExecutionAuditRecord
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.assets.models import DocumentRecord
from ai_workshop.shared.errors import AppError


def reader_fixture(mode="running"):
    now = datetime.now(UTC)
    actor, execution_id, attempt_id, case_id, version, profile = (uuid4() for _ in range(6))
    source = AgentEvidenceRef(document_id=uuid4(), asset_version_id=uuid4(), projection_id=uuid4())
    cited = AgentEvidenceRef(document_id=uuid4(), asset_version_id=uuid4(), projection_id=uuid4())
    evidence_id, span_id = uuid4(), uuid4()
    status = "running" if mode == "running" else "failed" if mode == "failed" else "completed"
    error = "provider_timeout" if mode == "failed" else None
    raw_result = None if mode == "running" else PrivateGenerativeResult(
        observation=GenerativeObservation(
            execution_id=execution_id, error_code=error,
            generation_status="answered" if mode == "answered" else
            "insufficient_evidence" if mode == "insufficient" else None,
            failure_stage="generation" if error else None,
            cited_evidence_ids=(evidence_id,) if mode == "answered" else (),
        ),
        answer="Synthetic rule" if mode == "answered" else None,
        citations=(ClaimCitation(claim_index=0, evidence_ids=(evidence_id,)),)
        if mode == "answered" else (),
    )
    references = [source, cited] if mode == "answered" else [source]
    rule = ExpectedAnswerRule(
        version=1, expected_answer_status="answered", required_propositions=("rule",),
        required_evidence_groups=((evidence_id,),),
    )
    run = SimpleNamespace(
        id=uuid4(), owner_id=actor, dataset_snapshot_id=uuid4(), policy_id=uuid4(),
        status=status, created_at=now, repetition_count=2, rules_digest="a" * 64,
        expected_rules={str(case_id): rule.model_dump(mode="json")},
        snapshot={
            "sources": [dict(ref.model_dump(mode="json"), title="Synthetic source",
                             evidence_units=[{"id": str(evidence_id), "page": 1}])
                        for ref in references],
            "candidates": [{"configuration_version_id": str(version), "component_snapshot": {
                "profiles": [{"kind": "generation", "id": str(profile)}],
            }}],
        },
        cancelled_by=None, cancelled_at=None, cancellation_reason=None,
    )
    attempt = SimpleNamespace(
        id=attempt_id, run_id=run.id, execution_id=execution_id, case_id=case_id,
        configuration_version_id=version, repetition=0, attempt_number=1,
        status=status, error_code=error, result=raw_result.model_dump(mode="json")
        if raw_result else None, result_digest=raw_result.digest() if raw_result else None,
    )
    trace = AgentTrace(
        run_id=uuid4(), root_span_id=span_id, revision=1, updated_at=now,
        spans=(AgentSpan(
            id=span_id, parent_id=None, sequence=0, kind="agent", name="rag_manager",
            state="running" if status == "running" else "completed", started_at=now,
            instructions=AgentContent(content_status="complete", text="Synthetic instruction"),
            evidence_refs=(source,),
        ),),
    )
    execution = SimpleNamespace(
        id=execution_id, actor_id=actor, evaluation_attempt_id=attempt_id, created_at=now,
        ended_at=None if status == "running" else now, status=status, complete=status != "running",
        stages={TRACE_STORAGE_KEY: trace.model_dump(mode="json")},
    )
    env = SimpleNamespace(
        actor=actor, run=run, attempt=attempt, execution=execution, source=source,
        references=references, acl_checks=0, revoke_at=None, revoked=False,
        lifecycle="active", version_status="ready", projection_status="ready",
    )

    class Session:
        async def execute(self, statement):
            values = {v for v in statement.compile().params.values() if isinstance(v, UUID)}
            model = statement.column_descriptions[0]["entity"]
            if model is DocumentRecord:
                env.acl_checks += 1
                if env.revoke_at == env.acl_checks:
                    env.revoked = True
                expected = next(
                    value for value in statement.compile().params.values()
                    if isinstance(value, list)
                )
                available = (
                    actor in values and not env.revoked and env.lifecycle == "active"
                    and env.version_status == env.projection_status == "ready"
                )
                rows = [
                    (ref.document_id, ref.asset_version_id, ref.projection_id)
                    for ref in env.references
                    if (ref.document_id, ref.asset_version_id, ref.projection_id) in expected
                    and available
                ]
                return SimpleNamespace(all=lambda: rows)
            pair = (execution, attempt) if {execution.id, execution.actor_id} <= values else None
            return SimpleNamespace(one_or_none=lambda: pair)

        async def scalar(self, statement):
            model = statement.column_descriptions[0]["entity"]
            values = {v for v in statement.compile().params.values() if isinstance(v, UUID)}
            if model is GenerativeRunRecord:
                return run if {run.id, run.owner_id} <= values else None
            if model is GenerationExecutionAuditRecord:
                return SimpleNamespace(generation_profile_id=profile)
            if model is ProfileRecord:
                return SimpleNamespace(config={"generation": {"response_schema_version": 2}})
            raise AssertionError(f"Unexpected scalar: {model}")

        async def scalars(self, statement):
            model = statement.column_descriptions[0]["entity"]
            if model is EvaluationDatasetCaseRecord:
                rows = [SimpleNamespace(id=case_id, query_bytes=b"Synthetic question")]
            elif model is GenerativeAttemptRecord:
                rows = [attempt]
            elif model is ExecutionRecord:
                rows = [execution.id]
            elif model is GenerativeJudgmentRecord:
                rows = []
            elif model is GenerationExecutionAuditRecord:
                if env.revoke_at == "usage":
                    env.revoked = True
                rows = []
            else:
                raise AssertionError(f"Unexpected scalars: {model}")
            return SimpleNamespace(all=lambda: rows)

    @asynccontextmanager
    async def sessions():
        yield Session()

    env.reader = GenerativeMonitoringReader(sessions)
    return env


@pytest.mark.parametrize("mode", ["running", "failed", "insufficient", "answered"])
async def test_authorized_trace_uses_frozen_sources_before_or_without_citation(mode):
    env = reader_fixture(mode)
    detail = await env.reader.detail(env.actor, env.execution.id)
    assert detail.agent_trace is not None
    assert detail.agent_trace.spans[0].evidence_refs == (env.source,)
    assert detail.agent_trace.spans[0].instructions.content_status == "not_retained"
    assert "Synthetic instruction" not in detail.model_dump_json()
    assert detail.document_count == (1 if mode == "answered" else 0)
    if mode == "answered":
        assert detail.generation and len(detail.generation.citations) == 1
    elif mode == "running":
        assert detail.generation is None
    else:
        assert detail.generation and detail.generation.citations == []


@pytest.mark.parametrize("field", ["document_id", "asset_version_id", "projection_id"])
async def test_trace_reference_outside_frozen_source_manifest_remains_hidden(field):
    env = reader_fixture()
    ref = env.execution.stages[TRACE_STORAGE_KEY]["spans"][0]["evidence_refs"][0]
    ref[field] = str(uuid4())
    with pytest.raises(AppError) as denied:
        await env.reader.detail(env.actor, env.execution.id)
    assert denied.value.code == "not_found"


@pytest.mark.parametrize("owner", ["execution", "run"])
async def test_another_owner_cannot_read_trace_even_with_matching_source(owner):
    env = reader_fixture()
    if owner == "execution":
        env.execution.actor_id = uuid4()
    else:
        env.run.owner_id = uuid4()
    with pytest.raises(AppError) as denied:
        await env.reader.detail(env.actor, env.execution.id)
    assert denied.value.code == "not_found"


@pytest.mark.parametrize("when", [1, 2, "usage"])
async def test_current_acl_is_rechecked_before_after_and_after_usage(when):
    env = reader_fixture("answered" if when == "usage" else "running")
    if when == "usage":
        env.execution.stages[TRACE_STORAGE_KEY]["spans"][0]["evidence_refs"] = [
            env.references[-1].model_dump(mode="json"),
        ]
    env.revoke_at = when
    with pytest.raises(AppError) as denied:
        await env.reader.detail(env.actor, env.execution.id)
    assert denied.value.code == "not_found"
    assert env.revoked  # The requested revocation boundary was actually reached.


async def test_mismatched_attempt_execution_identity_cannot_return_trace():
    env = reader_fixture("answered")
    env.execution.stages[TRACE_STORAGE_KEY]["spans"][0]["evidence_refs"] = [
        env.references[-1].model_dump(mode="json"),
    ]
    env.attempt.execution_id = uuid4()
    with pytest.raises(AppError) as denied:
        await env.reader.detail(env.actor, env.execution.id)
    assert denied.value.code == "not_found"


@pytest.mark.parametrize("nested", [False, True])
async def test_unrelated_snapshot_metadata_cannot_extend_frozen_source_authority(nested):
    env = reader_fixture()
    foreign = AgentEvidenceRef(document_id=uuid4(), asset_version_id=uuid4(), projection_id=uuid4())
    env.references.append(foreign)
    target = env.run.snapshot["sources"][0] if nested else env.run.snapshot
    target["unrelated_metadata"] = foreign.model_dump(mode="json")
    env.execution.stages[TRACE_STORAGE_KEY]["spans"][0]["evidence_refs"] = [
        foreign.model_dump(mode="json"),
    ]
    with pytest.raises(AppError) as denied:
        await env.reader.detail(env.actor, env.execution.id)
    assert denied.value.code == "not_found"


@pytest.mark.parametrize("field,value", [
    ("lifecycle", "archived"), ("version_status", "failed"), ("projection_status", "failed"),
])
async def test_archived_or_stale_source_cannot_authorize_a_trace(field, value):
    env = reader_fixture()
    setattr(env, field, value)
    with pytest.raises(AppError) as denied:
        await env.reader.detail(env.actor, env.execution.id)
    assert denied.value.code == "not_found"


async def test_malformed_trace_is_isolated_and_marked_incomplete():
    env = reader_fixture("insufficient")
    env.execution.stages[TRACE_STORAGE_KEY]["spans"][0]["sequence"] = 5
    detail = await env.reader.detail(env.actor, env.execution.id)
    assert detail.agent_trace is None
    assert detail.observation_complete is False
    assert detail.generation and detail.generation.status == "insufficient_evidence"
