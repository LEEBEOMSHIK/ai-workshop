import json
from dataclasses import replace
from types import SimpleNamespace

import httpx2
import pytest

from ai_workshop.labs.rag.executions.agent_trace import capture_agent_trace, current_agent_trace
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.models.orchestration_policy import OrchestrationPolicy
from tests.unit.labs.rag.generation.test_readiness import PROFILE_ID, VERSION_ID, readiness
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, answer, request, runner
from tests.unit.labs.rag.orchestration.test_policy import configuration


def native_request():
    selected = request()
    return replace(selected, profile=replace(
        selected.profile, orchestration=OrchestrationPolicy(
            **configuration(local_http_api="ollama_chat"),
        ),
    ))


def native_response(value, *, manager):
    message = {"role": "assistant", "content": json.dumps(answer()),
               "thinking": "PRIVATE_NATIVE_THINKING"}
    if manager:
        message["content"] = ""
        message["tool_calls"] = [{"id": "call_synthetic_native", "function": {
            "name": "write_grounded_answer", "arguments": {"task": "위험 한도 설명"},
        }}]
    return httpx2.Response(200, request=value, json={
        "model": native_request().profile.runtime_model, "done": True, "done_reason": "stop",
        "message": message, "prompt_eval_count": 40, "eval_count": 20,
        "total_duration": 100_000_000, "load_duration": 10_000_000,
        "prompt_eval_duration": 60_000_000, "eval_duration": 20_000_000,
    })


def test_existing_policy_keeps_compatibility_default():
    policy = OrchestrationPolicy(**configuration())
    assert getattr(policy, "local_http_api", None) == "openai_chat_completions"


async def test_native_calls_persist_actual_wire_input_and_server_metrics():
    calls = []

    def handler(value):
        assert value.url.path == "/api/chat"
        body = json.loads(value.content)
        calls.append(body)
        assert body["stream"] is False
        assert body["options"]["top_p"] == 1.0
        assert body["options"]["num_predict"] == native_request().profile.max_output_tokens
        assert "response_format" not in body
        return native_response(value, manager=len(calls) == 1)

    with capture_agent_trace(True):
        result = await runner(handler).generate(native_request(), policy=POLICY)
        trace = current_agent_trace()
    assert len(calls) == 2 and result.generation is not None
    assert result.execution.input_tokens == 80 and result.execution.output_tokens == 40
    models = [span for span in trace.spans if span.kind == "model"]
    for span, wire in zip(models, calls, strict=True):
        assert span.model_timing.api == "ollama_chat"
        assert span.model_timing.server_timing_status == "available"
        assert span.model_timing.server_timing.load_ms == 10
        assert span.model_timing.server_timing.prompt_eval_ms == 60
        assert span.model_timing.server_timing.eval_ms == 20
        assert span.model_timing.server_timing.total_ms == 100
        observed = json.loads(span.input.text)
        assert observed["messages"] == wire["messages"]
        assert observed["options"] == wire["options"]
    assert "PRIVATE_NATIVE_THINKING" not in trace.model_dump_json()


async def test_native_opt_in_requires_actual_ollama_runtime_without_calls():
    def forbidden(_value):
        raise AssertionError("Invalid native binding must not contact a runtime")

    with pytest.raises(GenerationProviderError, match="orchestration_not_supported"):
        await runner(forbidden, dialect="openai").generate(native_request(), policy=POLICY)


@pytest.mark.parametrize("dialect,expected", [("ollama", True), ("openai", False), (None, False)])
async def test_native_readiness_checks_endpoint_dialect(dialect, expected):
    config = {"generation": {"response_schema_version": 2},
              "orchestration": configuration(local_http_api="ollama_chat")}
    service = readiness(
        SimpleNamespace(bindings=(), deployment_version_id=VERSION_ID, config=config),
        SimpleNamespace(status="ready", safe_error_code=None,
                        observed_provider_model_id="runtime/exact-model"),
    )
    service.settings.provider_endpoint_dialects = {"local-runtime": dialect} if dialect else {}
    assert await service.is_ready(PROFILE_ID) is expected
