from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.evaluation.generative import (
    ExpectedAnswerRule,
    GenerativeObservation,
    evaluate_generative,
)
from ai_workshop.labs.rag.executions import observer as trace
from ai_workshop.labs.rag.executions.domain import ExecutionIdentity
from tests.unit.labs.rag.executions.test_observer import Recorder


@pytest.mark.parametrize(
    "failure",
    [
        {"failure_stage": "generation"},
        {"error_code": "provider_timeout"},
    ],
)
@pytest.mark.parametrize(
    "retrieved,selected,expected",
    [
        ((), (), (None, None)),
        ((UUID(int=2),), (), (1.0, None)),
        ((UUID(int=2),), (UUID(int=3),), (1.0, 0.0)),
        ((UUID(int=2),), (UUID(int=2),), (1.0, 1.0)),
    ],
)
def test_failure_coverage_distinguishes_preserved_ids_from_unknown(
    failure, retrieved, selected, expected
):
    observation = GenerativeObservation(
        execution_id=uuid4(),
        retrieved_evidence_ids=retrieved,
        selected_evidence_ids=selected,
        **failure,
    )
    metrics = evaluate_generative(
        observation,
        ExpectedAnswerRule(
            version=1,
            expected_answer_status="answered",
            required_evidence_groups=((UUID(int=2),),),
        ),
        None,
    )
    assert (metrics.retrieval_coverage, metrics.context_coverage) == expected
    assert metrics.generation_completed is False
    assert metrics.correctness == "unreviewed"


def test_completed_empty_search_retains_measured_zero_coverage():
    metrics = evaluate_generative(
        GenerativeObservation(
            execution_id=uuid4(),
            generation_status="insufficient_evidence",
        ),
        ExpectedAnswerRule(
            version=1,
            expected_answer_status="answered",
            required_evidence_groups=((UUID(int=2),),),
        ),
        None,
    )
    assert metrics.retrieval_coverage == 0
    assert metrics.context_coverage == 0


@pytest.mark.asyncio
async def test_checkpoint_keeps_exact_ids_separate_from_bounded_candidate_record():
    observer = trace.ExecutionObserver(
        ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), Recorder()
    )
    ids = tuple(UUID(int=i) for i in range(1, 252))

    async def record():
        trace.capture_evidence_ids(retrieved=ids, selected=ids[-2:])

    await trace.observed_call(record(), observer)
    assert observer.retrieved_evidence_ids == ids
    assert observer.selected_evidence_ids == ids[-2:]
    assert trace.current_observer.get() is None
    other = trace.ExecutionObserver(
        ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), Recorder()
    )
    assert other.retrieved_evidence_ids == ()
    assert other.selected_evidence_ids == ()


@pytest.mark.parametrize("failure", ["generation", "citation_validation"])
async def test_workflow_persists_pre_failure_ids_and_permission_exposures(monkeypatch, failure):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from ai_workshop.config import Settings
    from ai_workshop.labs.rag.evaluation import generative_workflow as module
    from ai_workshop.labs.rag.evaluation.generative import PrivateGenerativeResult
    from ai_workshop.shared.errors import AppError

    run_id, token, attempt_id, case_id = (uuid4() for _ in range(4))
    owner, execution_id, allowed, unexpected = (uuid4() for _ in range(4))
    run = SimpleNamespace(owner_id=owner, dataset_snapshot_id=uuid4(), input_approval=None)
    attempt = SimpleNamespace(
        id=attempt_id, execution_id=execution_id, case_id=case_id, configuration_version_id=uuid4()
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
            async def fail():
                trace.capture_evidence_ids(retrieved=(allowed, unexpected), selected=(allowed,))
                await observer.end("request")
                await observer.begin(failure)
                if failure == "citation_validation":
                    await observer.end(failure, state="failed", reason="exact_value_not_supported")
                raise AppError("provider_timeout", "Safe failure.", 504)

            return await trace.observed_call(fail(), observer)

    async def pipelines(*args):
        yield Pipeline()

    monkeypatch.setattr(
        module,
        "load_evaluation_dataset",
        lambda raw: SimpleNamespace(
            cases=[
                SimpleNamespace(
                    id=case_id,
                    permission_scenario=SimpleNamespace(
                        authorized_source_ids=frozenset({allowed}),
                    ),
                ),
            ]
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
    observed = records[0].observation
    assert observed.retrieved_evidence_ids == (allowed, unexpected)
    assert observed.selected_evidence_ids == (allowed,)
    assert observed.access_exposures == (unexpected,)
    assert observed.failure_stage == failure
    assert observed.error_code == "provider_timeout"
    assert records[0].answer is None
    assert records[0].citations == ()


async def test_final_access_revalidation_does_not_checkpoint_revoked_evidence(monkeypatch):
    from ai_workshop.shared.errors import AppError
    from tests.unit.labs.rag.search.test_selected_scope_history import (
        ACTOR_ID,
        DOCUMENT_ID,
        _acceptance_harness,
        _domain_scope,
        _selected_request,
    )

    service, configuration, scope, _, sources, runtime, _ = _acceptance_harness()
    original_resolve = sources.resolve

    async def resolve_then_change(**kwargs):
        prepared = await original_resolve(**kwargs)
        scope.switch_a_version()
        return prepared

    monkeypatch.setattr(sources, "resolve", resolve_then_change)
    observer = trace.ExecutionObserver(
        ExecutionIdentity(actor_id=ACTOR_ID, turn_id=uuid4()), Recorder()
    )
    await observer.start()
    with pytest.raises(AppError) as raised:
        await trace.observed_call(
            service.search_resolved(
                actor_id=ACTOR_ID,
                request=_selected_request([DOCUMENT_ID]),
                configuration=configuration,
                conversation_scope=_domain_scope(),
            ),
            observer,
        )
    assert raised.value.code == "conversation_scope_changed"
    assert runtime.generation_requests == []
    assert observer.retrieved_evidence_ids == ()
    assert observer.selected_evidence_ids == ()


async def test_selection_record_failure_keeps_approved_exact_ids(caplog):
    from tests.unit.labs.rag.search.test_selected_scope_history import (
        ACTOR_ID,
        DOCUMENT_ID,
        _acceptance_harness,
        _domain_scope,
        _selected_request,
    )

    class BrokenSelectionRecorder(Recorder):
        async def record(self, id, observation):
            if observation.stage == "selection":
                raise RuntimeError("private selection body")
            await super().record(id, observation)

    service, configuration, _, _, _, runtime, _ = _acceptance_harness()
    observer = trace.ExecutionObserver(
        ExecutionIdentity(actor_id=ACTOR_ID, turn_id=uuid4()),
        BrokenSelectionRecorder(),
    )
    await observer.start()
    output = await trace.observed_call(
        service.search_resolved(
            actor_id=ACTOR_ID,
            request=_selected_request([DOCUMENT_ID]),
            configuration=configuration,
            conversation_scope=_domain_scope(),
        ),
        observer,
    )
    assert len(runtime.generation_requests) == 1
    assert observer.complete is False
    assert observer.retrieved_evidence_ids == output.retrieved_evidence_ids
    assert observer.retrieved_evidence_ids
    assert observer.selected_evidence_ids == tuple(
        item.evidence.id for item in output.grounding_evidence
    )
    assert observer.selected_evidence_ids
    assert "private selection body" not in caplog.text
