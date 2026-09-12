"""Request-scoped port behavior using explicit fake executor/passive readiness."""

import json
from dataclasses import FrozenInstanceError, replace
from importlib import import_module
from importlib.util import find_spec
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.deployments.domain import ProviderKind
from ai_workshop.labs.rag.generation.codex_events import CodexEventResult, CodexTokenUsage
from ai_workshop.labs.rag.generation.codex_stream import CodexStreamResult
from ai_workshop.labs.rag.generation.codex_workspace import CodexWorkspaceResult
from ai_workshop.labs.rag.generation.domain import ContextualizationRequest, GenerationStatus
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    ProviderExecutionMetadata,
    ProviderHealthResult,
)
from ai_workshop.labs.rag.generation.windows_process import ProcessFailure
from tests.unit.labs.rag.generation.test_codex_execution import request_fixture


class FakeExecutor:
    def __init__(self, result, log):
        self.result = result
        self.log = log
        self.calls = []
        self.error = None

    async def execute(self, context, *, request):
        self.calls.append((context, request))
        self.log.append("execute")
        if self.error is not None:
            raise self.error
        return self.result


class FakeReadiness:
    def __init__(self, result, log):
        self.result = result
        self.log = log
        self.calls = []

    async def health(self, *, context, profile):
        self.calls.append((context, profile))
        self.log.append("health")
        return self.result


def setup_runtime(*, content=None, readiness_missing=False):
    name = "ai_workshop.labs.rag.generation.codex_runtime"
    assert find_spec(name) is not None, "request-scoped runtime is missing"
    context, request = request_fixture()
    if content is None:
        content = json.dumps(
            {
                "schema_version": 2,
                "status": "answered",
                "claims": [
                    {
                        "text": "Synthetic supported fact",
                        "evidence_ids": [str(request.evidence[0].evidence_id)],
                    },
                ],
            }
        )
    result = CodexWorkspaceResult(
        stream=CodexStreamResult(
            events=CodexEventResult(content, "synthetic-thread", CodexTokenUsage(12, 3, 8, 2, 0)),
            active_processes_after_cleanup=0,
        ),
        process_termination_verified=True,
    )
    log = []
    executor = FakeExecutor(result, log)
    profile = request.profile
    readiness = FakeReadiness(
        ProviderHealthResult(
            True,
            None,
            ProviderExecutionMetadata(
                ProviderKind.DEVELOPMENT_CODEX_EXEC,
                profile.runtime_model,
                profile.deployment.id,
                None,
                None,
                0,
            ),
        ),
        log,
    )
    times = iter([10.0, 10.25, 10.5, 10.75, 11.0, 11.25, 11.5, 11.75])
    runtime = import_module(name).CodexExecRuntime(
        context=context,
        profile=profile,
        executor=executor,
        readiness=None if readiness_missing else readiness,
        monotonic_clock=lambda: next(times),
    )
    return runtime, context, request, executor, readiness, log


async def test_passive_health_never_executes_and_preserves_observed_unknown():
    runtime, context, request, executor, readiness, log = setup_runtime()
    health = await runtime.health()
    assert health.ready is True and health.observed_provider_model_id is None
    assert health.execution.provider_model_id == request.profile.runtime_model
    assert readiness.calls == [(context, request.profile)]
    assert not executor.calls and log == ["health"]


async def test_generation_requires_health_and_maps_usage_and_measured_latency():
    runtime, context, request, executor, readiness, log = setup_runtime()
    result = await runtime.generate(request)
    assert result.status is GenerationStatus.ANSWERED
    assert result.generation.claims[0].text == "Synthetic supported fact"
    assert result.execution.provider is ProviderKind.DEVELOPMENT_CODEX_EXEC
    assert result.execution.provider_model_id == request.profile.runtime_model
    assert (result.execution.input_tokens, result.execution.output_tokens) == (12, 8)
    assert result.execution.latency_ms == 750
    assert log == ["health", "execute"]
    assert executor.calls == [(context, request)]
    assert readiness.result.observed_provider_model_id is None


async def test_insufficient_evidence_and_contextualization_use_strict_parsers():
    runtime, _, request, executor, _, _ = setup_runtime(
        content='{"schema_version":2,"status":"insufficient_evidence","claims":[]}',
    )
    result = await runtime.generate(request)
    assert result.status is GenerationStatus.INSUFFICIENT_EVIDENCE and result.generation is None
    executor.result = replace(
        executor.result,
        stream=replace(
            executor.result.stream,
            events=replace(
                executor.result.stream.events, final_text='{"resolved_query":" synthetic query "}'
            ),
        ),
    )
    result = await runtime.contextualize(
        ContextualizationRequest(
            request.question,
            request.history,
            request.profile,
        )
    )
    assert result.resolved_query == "synthetic query"


@pytest.mark.parametrize("missing", [False, True])
async def test_unready_or_missing_readiness_never_executes(missing):
    runtime, _, request, executor, readiness, _ = setup_runtime(readiness_missing=missing)
    readiness.result = replace(readiness.result, ready=False)
    with pytest.raises(GenerationProviderError, match="^deployment_not_ready$"):
        await runtime.generate(request)
    assert not executor.calls


@pytest.mark.parametrize("surface", ["health", "event"])
async def test_observed_model_mismatch_is_rejected(surface):
    runtime, _, request, executor, readiness, _ = setup_runtime()
    if surface == "health":
        readiness.result = replace(readiness.result, observed_provider_model_id="different-model")
    else:
        executor.result = replace(
            executor.result,
            stream=replace(
                executor.result.stream,
                events=replace(executor.result.stream.events, observed_model="different-model"),
            ),
        )
    with pytest.raises(GenerationProviderError, match="^provider_model_mismatch$"):
        await runtime.generate(request)


@pytest.mark.parametrize("field", ["profile_id", "deployment", "max_output_tokens"])
async def test_immutable_binding_rejects_changed_request_profile(field):
    runtime, _, request, executor, readiness, _ = setup_runtime()
    value = (
        uuid4()
        if field == "profile_id"
        else 999
        if field == "max_output_tokens"
        else replace(request.profile.deployment, id=uuid4())
    )
    changed = replace(request, profile=replace(request.profile, **{field: value}))
    with pytest.raises(GenerationProviderError, match="^codex_binding_mismatch$"):
        await runtime.generate(changed)
    assert not executor.calls and not readiness.calls
    with pytest.raises(FrozenInstanceError):
        runtime.profile = changed.profile


@pytest.mark.parametrize(
    "content",
    [
        '{"schema_version":2,"status":"insufficient_evidence"}',
        '{"schema_version":2,"status":"answered","claims":[]}',
        '{"schema_version":2,"status":"answered","claims":[],"reasoning":"private canary"}',
        "private raw invalid canary",
    ],
)
async def test_invalid_wire_output_is_safe(content):
    runtime, _, request, _, _, _ = setup_runtime(content=content)
    with pytest.raises(GenerationProviderError, match="^structured_output_invalid$") as error:
        await runtime.generate(request)
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert "canary" not in repr(error.value)


@pytest.mark.parametrize(
    "change",
    [
        {"input_tokens": True},
        {"output_tokens": -1},
        {"cached_input_tokens": 13},
        {"reasoning_output_tokens": 9},
        {"cache_write_input_tokens": "private canary"},
        {"output_tokens": 513},
    ],
)
async def test_malformed_usage_never_becomes_execution_metadata(change):
    runtime, _, request, executor, _, _ = setup_runtime()
    stream = executor.result.stream
    executor.result = replace(
        executor.result,
        stream=replace(
            stream, events=replace(stream.events, usage=replace(stream.events.usage, **change))
        ),
    )
    with pytest.raises(GenerationProviderError, match="^provider_invalid_response$"):
        await runtime.generate(request)


@pytest.mark.parametrize(
    "change",
    [
        {"cleanup_verified": False},
        {"process_termination_verified": False},
        {"failure": "codex_workspace_cleanup_failed"},
    ],
)
async def test_workspace_failure_discards_otherwise_valid_answer(change):
    runtime, _, request, executor, _, _ = setup_runtime()
    executor.result = replace(executor.result, **change)
    with pytest.raises(GenerationProviderError):
        await runtime.generate(request)


@pytest.mark.parametrize(
    "change",
    [
        {"cleanup_verified": False},
        {"active_processes_after_cleanup": False},
        {"process_failure": ProcessFailure.NONZERO_EXIT},
        {"event_failure": "codex_event_invalid_json"},
    ],
)
async def test_failed_stream_cannot_release_embedded_answer(change):
    runtime, _, request, executor, _, _ = setup_runtime()
    executor.result = replace(executor.result, stream=replace(executor.result.stream, **change))
    with pytest.raises(GenerationProviderError):
        await runtime.generate(request)


@pytest.mark.parametrize(
    "content",
    [
        '{"resolved_query":"first","resolved_query":"second"}',
        '{"resolved_query":"valid","reasoning":"private canary"}',
    ],
)
async def test_context_output_duplicates_or_extra_fields_are_rejected(content):
    runtime, _, request, _, _, _ = setup_runtime(content=content)
    with pytest.raises(GenerationProviderError, match="^structured_output_invalid$"):
        await runtime.contextualize(
            ContextualizationRequest(
                request.question,
                request.history,
                request.profile,
            )
        )


async def test_contextualization_cannot_bypass_readiness():
    runtime, _, request, executor, readiness, log = setup_runtime()
    readiness.result = replace(readiness.result, ready=False)
    with pytest.raises(GenerationProviderError, match="^deployment_not_ready$"):
        await runtime.contextualize(
            ContextualizationRequest(
                request.question,
                request.history,
                request.profile,
            )
        )
    assert not executor.calls and log == ["health"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("ready", 1),
        ("deployment_version_id", uuid4()),
        ("provider_model_id", "different-requested-model"),
        ("provider", ProviderKind.OPENAI_RESPONSES),
    ],
)
async def test_passive_health_must_match_exact_execution_binding(field, value):
    runtime, _, request, executor, readiness, _ = setup_runtime()
    if field == "ready":
        readiness.result = replace(readiness.result, ready=value)
    else:
        readiness.result = replace(
            readiness.result, execution=replace(readiness.result.execution, **{field: value})
        )
    with pytest.raises(GenerationProviderError, match="^provider_invalid_response$"):
        await runtime.generate(request)
    assert not executor.calls


async def test_untrusted_exception_or_error_code_cannot_escape_runtime():
    runtime, _, request, executor, _, _ = setup_runtime()
    executor.error = GenerationProviderError("synthetic private raw canary", retryable=True)
    with pytest.raises(GenerationProviderError, match="^provider_invalid_response$") as raised:
        await runtime.generate(request)
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    assert raised.value.retryable is False
