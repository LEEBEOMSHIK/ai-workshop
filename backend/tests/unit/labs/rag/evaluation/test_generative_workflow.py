from uuid import UUID

import pytest

from ai_workshop.labs.rag.evaluation.generative import (
    ExpectedAnswerRule,
    GenerativeObservation,
    PrivateGenerativeResult,
    evaluate_generative,
    judge_propositions,
)


def observation(**values):
    return GenerativeObservation(
        execution_id=UUID(int=1),
        retrieved_evidence_ids=(UUID(int=2),),
        selected_evidence_ids=(UUID(int=2),),
        cited_evidence_ids=(UUID(int=2),),
        generation_status="answered",
        citation_valid=True,
        **values,
    )


def rule(**values):
    return ExpectedAnswerRule(
        version=1,
        expected_answer_status="answered",
        required_evidence_groups=((UUID(int=2),),),
        **values,
    )


def test_valid_citation_does_not_establish_correctness():
    metrics = evaluate_generative(observation(), rule(), None)
    assert metrics.context_coverage == 1.0
    assert metrics.citation_valid is True
    assert metrics.correctness == "unreviewed"
    assert metrics.abstention_correct is None


def test_negative_answered_case_fails_abstention():
    metrics = evaluate_generative(
        observation(),
        ExpectedAnswerRule(
            version=1,
            expected_answer_status="insufficient_evidence",
        ),
        None,
    )
    assert metrics.abstention_correct is False
    assert metrics.correctness == "failed"


def test_missing_required_context_fails_coverage():
    metrics = evaluate_generative(
        observation().model_copy(update={"selected_evidence_ids": ()}),
        rule(),
        None,
    )
    assert metrics.context_coverage == 0


def test_rule_judgment_is_bound_to_exact_private_result():
    answer = PrivateGenerativeResult(observation=observation(), answer="Payment in seven days.")
    expected = rule(required_propositions=("seven days",), forbidden_propositions=("one day",))
    judgment = judge_propositions(answer, expected)
    assert judgment.status == "passed"
    assert judgment.provenance == "rule"
    assert judgment.result_digest == answer.digest()
    changed = answer.model_copy(update={"answer": "Payment in one day."})
    assert judge_propositions(changed, expected).status == "failed"
    assert judge_propositions(changed, expected).result_digest != judgment.result_digest


def test_no_propositions_cannot_invent_content_pass():
    answer = PrivateGenerativeResult(observation=observation(), answer="Unsupported content.")
    assert judge_propositions(answer, rule()).status == "unreviewed"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1])
def test_invalid_observation_duration_rejected(bad):
    with pytest.raises(ValueError):
        observation(duration_ms=bad)


@pytest.mark.asyncio
async def test_duplicate_delivery_does_not_execute_claimed_pipeline_twice():
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from ai_workshop.config import Settings
    from ai_workshop.labs.rag.evaluation.generative_workflow import GenerativeWorkflow

    workflow = GenerativeWorkflow(
        None,
        Settings(
            _env_file=None, environment="test", secret_key="synthetic-unit-test-secret-key-only"
        ),
    )
    workflow.repository.claim_run = AsyncMock(side_effect=[uuid4(), None])
    workflow._execute_claimed = AsyncMock()
    run_id = uuid4()
    await workflow.run(run_id)
    await workflow.run(run_id)
    workflow._execute_claimed.assert_awaited_once()


@pytest.mark.parametrize("failure", [None, "prepare", "generation", "cancel"])
async def test_attempt_owns_local_host_and_closes_dependencies(monkeypatch, tmp_path, failure):
    import asyncio
    import weakref
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from uuid import uuid4

    from ai_workshop.config import Settings
    from ai_workshop.labs.rag.evaluation import generative_workflow as module
    from ai_workshop.labs.rag.generation.domain import GenerationOutcome, GenerationStatus
    from ai_workshop.labs.rag.generation.execution import GenerationProviderError
    from ai_workshop.labs.rag.generation.local_model_host import LocalModelHost, LocalModelSpec
    from ai_workshop.labs.rag.search import api
    from ai_workshop.shared.errors import AppError
    from tests.unit.labs.rag.executions.test_observer import Recorder

    run_id, token, attempt_id, case_id = (uuid4() for _ in range(4))
    run = SimpleNamespace(owner_id=uuid4(), dataset_snapshot_id=uuid4(), input_approval=None)
    attempt = SimpleNamespace(
        id=attempt_id, execution_id=uuid4(), case_id=case_id, configuration_version_id=uuid4()
    )
    events, hosts, engines, results = [], [], [], []
    spec = LocalModelSpec(
        model_id="synthetic/test", revision="a" * 40, snapshot_path=tmp_path, max_input_tokens=32
    )

    class Engine:
        pass

    def load_engine(spec):
        engine = Engine()
        engines.append(weakref.ref(engine))
        return engine

    def host_factory():
        host = LocalModelHost(loader=load_engine)
        hosts.append(host)
        return host

    class Session:
        async def get(self, model, id):
            return run if id == run_id else SimpleNamespace(fixture_bytes=b"synthetic")

        async def scalars(self, query):
            return SimpleNamespace(all=lambda: [attempt_id])

    @asynccontextmanager
    async def sessions():
        try:
            yield Session()
        finally:
            events.append("session_closed")

    @asynccontextmanager
    async def codex(settings):
        try:
            yield SimpleNamespace(runtime_factory=None)
        finally:
            events.append("codex_closed")

    class Repository:
        async def claim_attempt(self, id, claim):
            return attempt

        async def complete_attempt(self, id, claim, result, *, error_code):
            results.append(result)
            events.append("persisted")

        async def finish_run(self, id, claim):
            events.append("finished")

    class Frozen:
        def __init__(self, settings):
            pass

        async def close(self):
            events.append("frozen_closed")

    class Client:
        async def close(self):
            events.append("search_closed")

    class Adapter:
        def __init__(self, *args, **kwargs):
            pass

        async def prepare(self, *args):
            if failure == "prepare":
                raise AppError("configuration_not_ready", "Synthetic failure.", 409)
            return SimpleNamespace(configuration=SimpleNamespace(generation_profile=None))

    class Pipeline:
        def __init__(self, **kwargs):
            # Exercise the actual search factory and resolver, not a permissive *args stub.
            self.host = kwargs["generation_runtime_resolver"]._local_model_host

        async def execute(self, prepared, *, observer):
            assert self.host is hosts[0]
            assert await self.host.run(spec, lambda *_: "synthetic", timeout=10) == "synthetic"
            assert engines[0]() is not None
            if failure == "cancel":
                raise asyncio.CancelledError
            if failure == "generation":
                raise AppError("provider_timeout", "Synthetic failure.", 504)
            return SimpleNamespace(
                retrieved_evidence_ids=(), grounding_evidence=(),
                generation=GenerationOutcome(status=GenerationStatus.INSUFFICIENT_EVIDENCE),
            )

    case = SimpleNamespace(
        id=case_id, permission_scenario=SimpleNamespace(authorized_source_ids=frozenset())
    )
    monkeypatch.setattr(module, "load_evaluation_dataset", lambda _: SimpleNamespace(cases=[case]))
    monkeypatch.setattr(module, "candidate_input", lambda *args: None)
    monkeypatch.setattr(module, "ProductionEvaluationSearch", Frozen)
    monkeypatch.setattr(module, "codex_services", codex)
    monkeypatch.setattr(module, "FrozenGenerativeAdapter", Adapter)
    monkeypatch.setattr(module, "LocalModelHost", host_factory, raising=False)
    monkeypatch.setattr(module, "SqlAlchemyExecutionRecorder", lambda _: Recorder())
    monkeypatch.setattr(api, "create_elasticsearch", lambda _: Client())
    monkeypatch.setattr(api, "SearchApplicationService", Pipeline)
    monkeypatch.setattr(
        module.SearchResponse, "from_domain", lambda _: SimpleNamespace(grounding_evidence=[])
    )
    workflow = module.GenerativeWorkflow(
        sessions,
        Settings(
            _env_file=None, environment="test", secret_key="synthetic-unit-test-secret-key-only"
        ),
    )
    workflow.repository = Repository()
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await workflow._execute_claimed(run_id, token)
        assert results == [] and "finished" not in events
    else:
        await workflow._execute_claimed(run_id, token)
        expected = {
            None: None, "prepare": "configuration_not_ready", "generation": "provider_timeout"
        }
        assert results[0].observation.error_code == expected[failure]
        assert events.index("frozen_closed") < events.index("persisted")
    assert len(hosts) == 1
    with pytest.raises(GenerationProviderError) as closed:
        await hosts[0].run(spec, lambda *_: None, timeout=10)
    assert closed.value.code == "deployment_not_ready"
    assert all(engine() is None for engine in engines)
    assert events.count("frozen_closed") == events.count("codex_closed") == 1
    assert events.count("session_closed") == 2
    assert events.count("search_closed") == (0 if failure == "prepare" else 1)
