"""Opt-in runtime request controls preserve model input and existing failure contracts."""

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from types import MappingProxyType, SimpleNamespace

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.deployments.domain import ExecutionLocation, ProviderKind
from ai_workshop.labs.rag.executions.agent_trace import capture_agent_trace, current_agent_trace
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    GenerationTermination,
    tracked_generation_call,
)
from ai_workshop.labs.rag.generation.profile import resolve_generation_profile
from ai_workshop.labs.rag.models.domain import Profile, ProfileKind, thaw_json
from ai_workshop.labs.rag.models.orchestration_policy import (
    OrchestrationPolicy,
    resolve_orchestration_policy,
)
from ai_workshop.labs.rag.orchestration.model_transport import safe_json
from ai_workshop.labs.rag.orchestration.ollama_chat import native_chat_request
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.generation.test_profile_resolution import (
    deployment,
    generation_profile,
    llm_model,
)
from tests.unit.labs.rag.generation.test_readiness import PROFILE_ID, VERSION_ID, readiness
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, runner
from tests.unit.labs.rag.orchestration.test_direct_answer import (
    provider_response,
    selected_request,
)
from tests.unit.labs.rag.orchestration.test_ollama_chat import request as codec_request
from tests.unit.labs.rag.orchestration.test_policy import configuration


def policy(options, **changes):
    return OrchestrationPolicy(**configuration(
        local_http_api="ollama_chat", ollama_runtime=options, **changes,
    ))


def runtime_request(mode="direct_answer", options=None):
    selected = selected_request(mode, native=True)
    return replace(selected, profile=replace(selected.profile, orchestration=policy(
        options, dispatch_mode=mode,
    )))


def test_absent_and_null_runtime_preserve_original_raw_config():
    raw = {"orchestration": configuration()}
    before = deepcopy(raw)
    assert resolve_orchestration_policy(raw).ollama_runtime is None
    assert policy(None).ollama_runtime is None
    assert raw == before


@pytest.mark.parametrize("values", [
    {"num_batch": 1}, {"num_batch": 2048}, {"num_thread": 1}, {"num_thread": 64},
    {"num_batch": 256, "num_thread": 10},
])
def test_runtime_bounds_roundtrip_and_are_frozen(values):
    selected = policy({"version": 1, **values})
    assert OrchestrationPolicy.model_validate_json(selected.model_dump_json()) == selected
    assert selected.ollama_runtime.model_dump(exclude_none=True) == {"version": 1, **values}
    with pytest.raises(ValidationError):
        selected.ollama_runtime.num_batch = 512


@pytest.mark.parametrize("values", [
    {}, {"num_batch": 256}, {"version": 1}, {"version": 1, "num_batch": None},
    {"version": True, "num_batch": 256}, {"version": 1.0, "num_batch": 256},
    {"version": "1", "num_batch": 256}, {"version": 2, "num_batch": 256},
    *[{"version": 1, "num_batch": value} for value in (True, 0, -1, 2049, 256.0, "256")],
    *[{"version": 1, "num_thread": value} for value in (True, 0, -1, 65, 10.0, "10")],
    {"version": 1, "num_batch": 256, "num_ctx": 1024},
    {"version": 1, "num_batch": 256, "temperature": 0},
])
def test_invalid_runtime_values_fail_closed(values):
    with pytest.raises(ValidationError):
        policy(values)


def test_runtime_is_native_only_and_cannot_silently_enter_compatibility_api():
    with pytest.raises(ValidationError):
        OrchestrationPolicy(**configuration(ollama_runtime={"version": 1, "num_batch": 256}))


def test_registered_deep_frozen_profile_resolves_without_mutating_snapshot():
    exact = replace(deployment(), provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
                    location=ExecutionLocation.LOCAL, external_transfer=False,
                    transmitted_data_categories=(), data_processing_notice_ref=None,
                    secret_ref=None, max_retries=0)
    config = thaw_json(generation_profile().config)
    config["generation"]["response_schema_version"] = 2
    config["orchestration"] = configuration(local_http_api="ollama_chat", ollama_runtime={
        "version": 1, "num_batch": 256,
    })
    before = deepcopy(config)
    registered = Profile.create(kind=ProfileKind.GENERATION, name="synthetic-runtime", version=1,
                                config=config, bindings=(), deployment_version_id=exact.id)
    assert isinstance(registered.config["orchestration"]["ollama_runtime"], MappingProxyType)
    resolved = resolve_generation_profile(registered, exact, llm_model())
    assert resolved.orchestration.ollama_runtime.num_batch == 256
    assert resolved.orchestration.ollama_runtime.num_thread is None
    assert config == before == thaw_json(registered.config)
    assert resolve_orchestration_policy(registered.config) == resolved.orchestration


def test_native_codec_default_bytes_are_exactly_preserved():
    expected = (
        b'{"model":"local:alias","messages":[{"role":"system","content":"rules"},'
        b'{"role":"user","content":"question"}],"stream":false,'
        b'"options":{"temperature":0.0,"top_p":1.0,"num_predict":128}}'
    )
    assert safe_json(native_chat_request(codec_request(), manager=False)).encode() == expected
    assert safe_json(native_chat_request(
        codec_request(), manager=False, runtime_options=None,
    )).encode() == expected


@pytest.mark.parametrize("values", [
    {"num_batch": 256}, {"num_thread": 10}, {"num_batch": 256, "num_thread": 10},
])
def test_codec_adds_only_explicit_typed_runtime_values(values):
    body = codec_request()
    before = deepcopy(body)
    baseline = native_chat_request(body, manager=False)
    actual = native_chat_request(body, manager=False, runtime_options=policy({
        "version": 1, **values,
    }).ollama_runtime)
    assert actual["options"] == baseline["options"] | values
    for key in values:
        del actual["options"][key]
    assert safe_json(actual) == safe_json(baseline)
    assert body == before


def test_arbitrary_sdk_options_remain_unsupported():
    with pytest.raises(GenerationProviderError, match="orchestration_not_supported"):
        native_chat_request(codec_request() | {"options": {"num_batch": 256}}, manager=False)


@pytest.mark.parametrize("mode", ["manager_delegation", "direct_answer"])
async def test_actual_sdk_wire_differs_only_in_runtime_and_trace_retains_exact_request(mode):
    all_calls, all_results = [], []
    values = {"num_batch": 256, "num_thread": 10}
    for options in (None, {"version": 1, **values}):
        selected = runtime_request(mode, options)
        calls, checks = [], []

        async def authorize(checks=checks):
            checks.append(True)

        def handler(value, calls=calls, selected=selected):
            calls.append(bytes(value.content))
            return provider_response(value, selected, native=True,
                                     manager=mode == "manager_delegation" and len(calls) == 1)

        with capture_agent_trace(True):
            result = await runner(handler).generate(selected, policy=POLICY, revalidate=authorize)
            trace = current_agent_trace()
        assert len(calls) == len(checks) == (1 if mode == "direct_answer" else 2)
        assert len(trace.spans) == (2 if mode == "direct_answer" else 5)
        models = [span for span in trace.spans if span.kind == "model"]
        for call, span in zip(calls, models, strict=True):
            assert json.loads(span.input.text) == json.loads(call)
        assert models[-1].citation_reference_map.evidence_ids == tuple(
            item.evidence_id for item in selected.evidence
        )
        all_calls.append(calls)
        all_results.append(result.generation)
    for before, after in zip(*all_calls, strict=True):
        normalized = json.loads(after)
        assert normalized["options"] == json.loads(before)["options"] | values
        for key in values:
            del normalized["options"][key]
        assert safe_json(normalized).encode() == before
    assert all_results[0] == all_results[1]


@pytest.mark.parametrize("case,expected", [
    ("valid", True), ("invalid_value", False), ("wrong_api", False), ("wrong_dialect", False),
])
async def test_readiness_uses_the_same_native_runtime_validation(case, expected):
    raw = configuration(local_http_api="ollama_chat", ollama_runtime={
        "version": 1, "num_batch": 0 if case == "invalid_value" else 256,
    })
    if case == "wrong_api":
        raw["local_http_api"] = "openai_chat_completions"
    target = readiness(SimpleNamespace(bindings=(), deployment_version_id=VERSION_ID,
                                      config={"generation": {"response_schema_version": 2},
                                              "orchestration": raw}),
                       SimpleNamespace(status="ready", safe_error_code=None,
                                       observed_provider_model_id="runtime/exact-model"))
    target.settings.provider_endpoint_dialects = {
        "local-runtime": "openai" if case == "wrong_dialect" else "ollama",
    }
    assert await target.is_ready(PROFILE_ID) is expected


async def test_runtime_wrong_actual_dialect_is_rejected_without_http():
    target = runner(lambda _: pytest.fail("No I/O for invalid dialect"), dialect="openai")
    with pytest.raises(GenerationProviderError, match="orchestration_not_supported"):
        await target.generate(
            runtime_request(options={"version": 1, "num_batch": 256}), policy=POLICY,
        )


async def test_runtime_acl_denial_still_prevents_any_model_send():
    async def denied():
        raise AppError("source_access_denied", "Synthetic ACL denial.", 403)

    with pytest.raises(AppError, match="Synthetic ACL denial"):
        await runner(lambda _: pytest.fail("No I/O after ACL denial")).generate(
            runtime_request(options={"version": 1, "num_batch": 256}),
            policy=POLICY, revalidate=denied,
        )


@pytest.mark.parametrize("outcome", ["invalid", "timeout", "cancel"])
async def test_failed_runtime_request_is_retained_without_retry_or_fallback(outcome):
    entered, calls = asyncio.Event(), []
    selected = runtime_request(options={"version": 1, "num_batch": 256})
    if outcome == "timeout":
        selected = replace(selected, profile=replace(selected.profile, timeout_seconds=0.2))

    async def handler(value):
        calls.append(bytes(value.content))
        entered.set()
        if outcome != "invalid":
            await asyncio.Event().wait()
        return provider_response(value, selected, native=True, content={
            "schema_version": 2, "status": "answered", "claims": [
                {"text": "invalid alias", "evidence_ids": ["e999"]},
            ],
        })

    termination = GenerationTermination()
    with capture_agent_trace(True):
        if outcome == "cancel":
            task = asyncio.create_task(tracked_generation_call(
                runner(handler).generate(selected, policy=POLICY), termination,
            ))
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            code = "provider_timeout" if outcome == "timeout" else "provider_invalid_response"
            with pytest.raises(GenerationProviderError, match=code):
                await tracked_generation_call(
                    runner(handler).generate(selected, policy=POLICY), termination,
                )
        trace = current_agent_trace()
    assert entered.is_set() and len(calls) == 1 and len(trace.spans) == 2
    model = next(span for span in trace.spans if span.kind == "model")
    assert json.loads(model.input.text) == json.loads(calls[0])
    assert json.loads(model.input.text)["options"]["num_batch"] == 256
    assert model.citation_reference_map is not None
    if outcome != "invalid":
        assert not termination.confirmed
