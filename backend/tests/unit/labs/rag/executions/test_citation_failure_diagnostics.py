from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.executions.domain import ExecutionIdentity, ExecutionOutcome
from ai_workshop.labs.rag.executions.observer import ExecutionObserver, observed_call
from ai_workshop.labs.rag.generation.domain import GeneratedClaim, StructuredGeneration
from ai_workshop.labs.rag.generation.execution import ProviderGenerationResult
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget
from ai_workshop.labs.rag.highlighting.domain import AnswerPolicy
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.labs.rag.retrieval.domain import SparseHit
from ai_workshop.labs.rag.search.schemas import SearchRequest
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.executions.test_observer import Recorder
from tests.unit.labs.rag.highlighting.test_context import ContextEmbedding
from tests.unit.labs.rag.highlighting.test_evidence_selector import _source
from tests.unit.labs.rag.search.test_generation_policy_gate import (
    ACTOR_ID,
    CONFIGURATION_ID,
    INSTALLATION_POLICY_ID,
    WORKSPACE_ID,
    _approval,
    _configuration,
    _service,
)
from tests.unit.labs.rag.search.test_provider_insufficient_evidence import (
    ActiveScopeResolver,
    InsufficientRuntime,
)


@pytest.mark.parametrize("diagnostics", [False, True])
@pytest.mark.parametrize("reason", ["exact_value_not_supported", "evidence_not_allowed"])
async def test_citation_failure_preserves_safe_detail_and_completed_measurements(
    reason, diagnostics
):
    source = _source(1, "An explanation of the device warranty.")

    class Retriever:
        async def search_sparse(self, **kwargs):
            return (SparseHit(source.chunk, 1, 7.2),)

    class Sources:
        async def resolve(self, **kwargs):
            return (source,)

    class Runtime(InsufficientRuntime):
        async def generate(self, request):
            evidence_id = request.evidence[0].evidence_id
            claim = (
                GeneratedClaim("The warranty is 99%.", (evidence_id,))
                if reason == "exact_value_not_supported"
                else GeneratedClaim("An explanation.", (UUID(int=999),))
            )
            return ProviderGenerationResult(StructuredGeneration(1, (claim,)), self.execution)

    approval = _approval()
    configuration = _configuration(approval=approval)
    configuration = replace(
        configuration,
        generation_runtime=Runtime(None),
        embedding=ContextEmbedding(),
        answer_policy=AnswerPolicy(0.9, 1.0),
        generation_profile=replace(
            configuration.generation_profile,
            prompt_ref="rag-answer-v2",
            evidence_budget=EvidenceBudget(8, 32, 12000),
        ),
    )
    service, _, _, audits = _service(
        configuration=configuration,
        decision=PolicyDecision(
            True,
            None,
            INSTALLATION_POLICY_ID,
            tuple(item.policy_version_id for item in approval.workspace_policies),
            workspace_policy_snapshots=tuple(
                (item.workspace_id, item.policy_version_id) for item in approval.workspace_policies
            ),
        ),
    )
    service.sparse_retriever, service.source_resolver = Retriever(), Sources()
    service.scope_resolver = ActiveScopeResolver()
    service.turn_signer = ConversationTurnSigner(b"synthetic-test-signing-key-32-bytes")
    recorder = Recorder()
    observer = ExecutionObserver(ExecutionIdentity(actor_id=ACTOR_ID, turn_id=uuid4()), recorder)
    await observer.start()
    with pytest.raises(AppError) as raised:
        await observed_call(
            service.search(
                actor_id=ACTOR_ID,
                request=SearchRequest(
                    query="synthetic fact",
                    configuration_id=CONFIGURATION_ID,
                    workspace_ids=[WORKSPACE_ID],
                    experimental=True,
                    include_diagnostics=diagnostics,
                ),
            ),
            observer,
        )
    assert raised.value.code == "citation_validation_failed"
    assert "99%" not in str(raised.value)
    assert audits.audits[-1].safe_error_code == "citation_validation_failed"
    await observer.fail(raised.value.code)
    await observer.finish(ExecutionOutcome(state="failed", error_code=raised.value.code))
    failures = [row for row in recorder.rows if row.state == "failed"]
    assert len(failures) == 1
    assert failures[0].stage == "citation_validation"
    assert failures[0].reason == reason
    assert failures[0].duration_ms is not None
    completed = {row.stage: row for row in recorder.rows if row.state == "completed"}
    assert completed["retrieval"].duration_ms is not None
    assert completed["generation"].duration_ms is not None
    assert completed["selection"].selection.selected_count == 1
    assert recorder.outcome.error_code == "citation_validation_failed"
    assert observer.retrieved_evidence_ids == tuple(
        evidence.id for evidence in source.chunk.evidence_units
    )
    assert observer.selected_evidence_ids == (source.chunk.evidence_units[0].id,)


async def test_observer_retains_ended_failure_stage_through_outer_failure_and_persistence():
    recorder = Recorder()
    observer = ExecutionObserver(ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), recorder)
    await observer.start()
    await observer.begin("citation_validation")
    await observer.end("citation_validation", state="failed", reason="exact_value_not_supported")
    await observer.fail("citation_validation_failed")
    await observer.begin("persistence")
    await observer.end("persistence")
    await observer.finish(ExecutionOutcome(state="failed", error_code="citation_validation_failed"))
    assert observer.failed_stage == "citation_validation"
    failures = [row for row in recorder.rows if row.state == "failed"]
    assert len(failures) == 1
    assert failures[0].reason == "exact_value_not_supported"


async def test_observation_write_failure_retains_failure_stage_without_logging_content(caplog):
    class BrokenRecorder(Recorder):
        async def record(self, id, observation):
            raise RuntimeError("private generated answer")

    observer = ExecutionObserver(
        ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()),
        BrokenRecorder(),
    )
    await observer.start()
    await observer.begin("citation_validation")
    await observer.end("citation_validation", state="failed", reason="evidence_not_allowed")
    await observer.fail("citation_validation_failed")
    assert observer.failed_stage == "citation_validation"
    assert observer.complete is False
    assert "private generated answer" not in caplog.text


@pytest.mark.parametrize("stage", ["citation_validation", "retrieval"])
async def test_evaluation_persists_terminal_or_active_failure_stage(monkeypatch, stage):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from ai_workshop.config import Settings
    from ai_workshop.labs.rag.evaluation import generative_workflow as module
    from ai_workshop.labs.rag.evaluation.generative import PrivateGenerativeResult

    run_id, token, attempt_id, case_id = (uuid4() for _ in range(4))
    execution_id = uuid4()
    run = SimpleNamespace(owner_id=ACTOR_ID, dataset_snapshot_id=uuid4(), input_approval=None)
    attempt = SimpleNamespace(
        id=attempt_id,
        execution_id=execution_id,
        case_id=case_id,
        configuration_version_id=CONFIGURATION_ID,
    )
    records = []

    class Session:
        async def get(self, model, id):
            return run if id == run_id else SimpleNamespace(fixture_bytes=b"synthetic fixture")

        async def scalars(self, query):
            return SimpleNamespace(all=lambda: [attempt_id])

    @asynccontextmanager
    async def sessions():
        yield Session()

    @asynccontextmanager
    async def codex(settings):
        yield None

    class Repository:
        async def claim_attempt(self, id, claim):
            return attempt

        async def complete_attempt(self, id, claim, result, *, error_code):
            # Exercise the persisted serialization boundary without touching an app DB.
            records.append(PrivateGenerativeResult.model_validate(result.model_dump(mode="json")))

        async def finish_run(self, id, claim):
            pass

    class Frozen:
        def __init__(self, settings):
            pass

        async def close(self):
            pass

    class Adapter:
        def __init__(self, *args, **kwargs):
            pass

        async def prepare(self, *args):
            return None

    class Pipeline:
        async def execute(self, prepared, *, observer):
            await observer.end("request")
            await observer.begin(stage)
            if stage == "citation_validation":
                await observer.end(stage, state="failed", reason="exact_value_not_supported")
            raise AppError("citation_validation_failed", "Safe failure.", 502)

    async def pipelines(*args):
        yield Pipeline()

    monkeypatch.setattr(
        module,
        "load_evaluation_dataset",
        lambda raw: SimpleNamespace(
            cases=[SimpleNamespace(id=case_id)],
        ),
    )
    monkeypatch.setattr(module, "candidate_input", lambda *args: None)
    monkeypatch.setattr(module, "ProductionEvaluationSearch", Frozen)
    monkeypatch.setattr(module, "codex_services", codex)
    monkeypatch.setattr(module, "get_search_configuration_resolver", lambda *args: None)
    monkeypatch.setattr(module, "FrozenGenerativeAdapter", Adapter)
    monkeypatch.setattr(module, "get_search_service", pipelines)
    monkeypatch.setattr(module, "SqlAlchemyExecutionRecorder", lambda sessions: Recorder())
    workflow = module.GenerativeWorkflow(sessions, Settings())
    workflow.repository = Repository()
    await workflow._execute_claimed(run_id, token)
    assert len(records) == 1
    assert records[0].observation.execution_id == execution_id
    assert records[0].observation.failure_stage == stage
    assert records[0].observation.error_code == "citation_validation_failed"
    assert records[0].answer is None
    assert records[0].citations == ()
