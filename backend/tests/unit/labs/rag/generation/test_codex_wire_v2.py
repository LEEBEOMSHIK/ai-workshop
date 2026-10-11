import json
from dataclasses import replace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.codex_prompt import build_codex_prompt
from ai_workshop.labs.rag.generation.domain import GenerationRequest
from ai_workshop.labs.rag.models.context_evidence import EvidenceBudget
from ai_workshop.labs.rag.models.numeric_proof_policy import SOURCE_NUMERIC_PROOF_V1

from .numeric_proof_fixtures import numeric_fixture
from .test_structured_output_v3 import draft_json


def test_wire2_normalizes_only_empty_insufficient_claims():
    from ai_workshop.labs.rag.generation.codex_wire_v2 import parse_codex_grounded_wire_v2

    fixture = numeric_fixture(("0.30%", "0.20%"))
    parsed = parse_codex_grounded_wire_v2(
        json.dumps(draft_json(fixture)),
        allowed_evidence_ids={e.evidence_id for e in fixture.evidence},
        policy=SOURCE_NUMERIC_PROOF_V1,
    )
    assert parsed.generation.schema_version == 3
    empty = parse_codex_grounded_wire_v2(
        '{"schema_version":3,"status":"insufficient_evidence","claims":[]}',
        allowed_evidence_ids=(),
        policy=SOURCE_NUMERIC_PROOF_V1,
    )
    assert empty.generation is None


def test_v6_prompt_payload_preserves_catalogue_and_nonce():
    fixture = numeric_fixture(("0.30%", "0.20%"), request_id=UUID(int=30))
    profile = replace(fixture.profile, evidence_budget=EvidenceBudget(2, 4, 1000))
    request = GenerationRequest(
        "synthetic difference",
        "difference",
        (),
        fixture.evidence,
        profile,
        "same-correlation",
        fixture.catalogue,
    )
    envelope = build_codex_prompt(request)
    assert envelope.schema_ref == "codex-grounded-wire-v2"
    payload = json.loads(envelope.stdin_json)
    assert payload["numeric_catalogue"]["request_id"] == str(UUID(int=30))
    assert len(payload["numeric_catalogue"]["tokens"]) == 2
    assert json.loads(envelope.output_schema_json)["properties"]["schema_version"]["enum"] == [3]


@pytest.mark.asyncio
async def test_unsupported_provider_refuses_before_http():
    import httpx

    from ai_workshop.labs.rag.generation.execution import GenerationProviderError
    from ai_workshop.labs.rag.generation.openai_compatible import LocalOpenAICompatibleRuntime

    from .test_openai_compatible import local_deployment

    calls = []

    async def forbidden(request):
        calls.append(request)
        raise AssertionError("HTTP must not be called")

    fixture = numeric_fixture(("1원",))
    deployment = local_deployment()
    profile = replace(
        fixture.profile,
        model_id=deployment.model_definition_id,
        runtime_model=deployment.provider_model_id,
        deployment=deployment,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(forbidden), trust_env=False
    ) as client:
        runtime = LocalOpenAICompatibleRuntime(
            client=client, deployment=deployment, endpoint="http://localhost:8999"
        )
        with pytest.raises(GenerationProviderError) as raised:
            await runtime.generate(GenerationRequest("x", "x", (), fixture.evidence, profile, "x"))
    assert raised.value.code == "generation_schema_not_supported"
    assert calls == []


def test_v6_verification_signature_selects_wire2():
    from ai_workshop.labs.rag.generation.codex_verification import verification_binding

    from .test_codex_verification import verification_fixture

    fixture = verification_fixture()
    configuration = fixture.lookup.values[fixture.context.configuration_version_id]
    profile = replace(
        configuration.profile,
        prompt_ref="rag-codex-answer-v6",
        response_schema_version=3,
        numeric_proof_policy=SOURCE_NUMERIC_PROOF_V1,
        evidence_budget=EvidenceBudget(2, 4, 1000),
    )
    result = verification_binding(replace(configuration, profile=profile), fixture.registry.runner)
    assert result.answer_prompt.schema_ref == "codex-grounded-wire-v2"


@pytest.mark.asyncio
async def test_synthetic_v6_verification_uses_wire2_and_own_catalogue():
    from ai_workshop.labs.rag.generation.domain import ContextualizationRequest

    from .test_codex_verification import _verify, verification_fixture

    fixture = verification_fixture()
    config_id = fixture.context.configuration_version_id
    configuration = fixture.lookup.values[config_id]
    fixture.lookup.values[config_id] = replace(
        configuration,
        profile=replace(
            configuration.profile,
            prompt_ref="rag-codex-answer-v6",
            response_schema_version=3,
            numeric_proof_policy=SOURCE_NUMERIC_PROOF_V1,
            evidence_budget=EvidenceBudget(2, 4, 1000),
        ),
    )
    previous_execute = fixture.executor.execute

    async def execute(context, *, request):
        result = await previous_execute(context, request=request)
        if isinstance(request, ContextualizationRequest):
            return result
        assert request.numeric_catalogue.request_id == context.request_id
        assert request.numeric_catalogue.tokens == ()
        return replace(
            result,
            stream=replace(
                result.stream,
                events=replace(
                    result.stream.events,
                    final_text='{"schema_version":3,"status":"insufficient_evidence","claims":[]}',
                ),
            ),
        )

    fixture.executor.execute = execute
    assert (await _verify(fixture)).ready is True


async def test_runtime_rejects_other_request_catalogue_before_health_or_execution():
    from ai_workshop.labs.rag.generation.execution import GenerationProviderError

    from .test_codex_runtime import setup_runtime

    runtime, context, request, executor, readiness, log = setup_runtime()
    profile = replace(
        request.profile,
        prompt_ref="rag-codex-answer-v6",
        response_schema_version=3,
        numeric_proof_policy=SOURCE_NUMERIC_PROOF_V1,
        evidence_budget=EvidenceBudget(2, 4, 1000),
    )
    runtime = replace(runtime, profile=profile)
    fixture = numeric_fixture(("0.30%",))
    with pytest.raises(GenerationProviderError) as error:
        await runtime.generate(
            replace(request, profile=profile, numeric_catalogue=fixture.catalogue)
        )
    assert error.value.code == "codex_binding_mismatch"
    assert executor.calls == [] and readiness.calls == []
