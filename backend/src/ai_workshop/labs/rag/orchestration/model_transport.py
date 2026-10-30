"""Observe actual local HTTP requests, with no credentials, URLs or hidden reasoning."""

import json
from collections.abc import Mapping
from time import perf_counter
from typing import Any

import httpx2

from ai_workshop.labs.rag.executions.agent_trace import CitationReferenceMap
from ai_workshop.labs.rag.executions.model_timing import (
    OllamaServerTiming,
    ServerTimingStatus,
    parse_ollama_timing,
)
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    track_local_http_attempt,
)
from ai_workshop.labs.rag.generation.openai_compatible import parse_http_json, validate_http_message
from ai_workshop.labs.rag.orchestration.domain import (
    ANSWER_TOOL,
    MANAGER,
    SPECIALIST,
    OrchestrationContext,
)
from ai_workshop.labs.rag.orchestration.ollama_chat import native_chat_request, native_chat_response
from ai_workshop.labs.rag.orchestration.rejections import (
    DelegationRejection,
    DelegationRejectionReason,
    validate_delegation_arguments,
)
from ai_workshop.shared.errors import AppError

_INPUT_FIELDS = (
    "messages", "tools", "tool_choice", "parallel_tool_calls", "temperature", "max_tokens",
    "response_format", "reasoning_effort", "stream", "store",
)
# This bounds received bytes independently from the smaller observation display limit.
_MAX_RESPONSE_BYTES = 1024 * 1024
_NATIVE_INPUT_FIELDS = ("model", "messages", "tools", "options", "format", "think", "stream")


def safe_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _usage(value: object) -> tuple[int | None, int | None]:
    values = value if isinstance(value, Mapping) else {}
    def token(name: str) -> int | None:
        value = values.get(name)
        return value if type(value) is int and 0 <= value <= 2**31 - 1 else None

    return token("prompt_tokens"), token("completion_tokens")


def _response_output(
    payload: Any, *, manager: bool, expected_model: str, dialect: str,
    allowed_handoffs: tuple[str, ...] = (), final_allowed: bool = True,
) -> str:
    if not isinstance(payload, dict) or payload.get("model") != expected_model:
        raise GenerationProviderError("provider_model_mismatch", retryable=False)
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise GenerationProviderError("provider_invalid_response", retryable=False)
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        raise GenerationProviderError("provider_invalid_response", retryable=False)
    message = choice["message"]
    validate_http_message(message, dialect=dialect,
                          allow_tool_calls=manager or bool(allowed_handoffs))
    if manager or (allowed_handoffs and message.get("tool_calls")):
        calls = message.get("tool_calls")
        if calls is None or calls == []:
            raise DelegationRejection(DelegationRejectionReason.REQUIRED_HANDOFF_MISSING)
        if not isinstance(calls, list):
            raise DelegationRejection(DelegationRejectionReason.MALFORMED_TOOL_CALL)
        if len(calls) > 1:
            raise DelegationRejection(DelegationRejectionReason.MULTIPLE_TOOL_CALLS)
        if not isinstance(calls[0], dict):
            raise DelegationRejection(DelegationRejectionReason.MALFORMED_TOOL_CALL)
        if choice.get("finish_reason") != "tool_calls":
            raise DelegationRejection(DelegationRejectionReason.INVALID_FINISH_REASON)
        call = calls[0]
        function = call.get("function")
        if (call.get("type") != "function" or not isinstance(call.get("id"), str)
                or not call["id"] or not isinstance(function, dict)):
            raise DelegationRejection(DelegationRejectionReason.MALFORMED_TOOL_CALL)
        if function.get("name") not in ((ANSWER_TOOL,) if manager else allowed_handoffs):
            raise DelegationRejection(DelegationRejectionReason.UNAPPROVED_TARGET)
        if not isinstance(function.get("arguments"), str):
            raise DelegationRejection(DelegationRejectionReason.INVALID_ARGUMENTS)
        validate_delegation_arguments(function["arguments"])
        return safe_json({"tool": function["name"], "arguments": function["arguments"]})
    if not final_allowed:
        calls = message.get("tool_calls")
        if calls is not None and not isinstance(calls, list):
            raise DelegationRejection(DelegationRejectionReason.MALFORMED_TOOL_CALL)
        raise DelegationRejection(DelegationRejectionReason.REQUIRED_HANDOFF_MISSING)
    content = message.get("content")
    if (choice.get("finish_reason") != "stop" or message.get("tool_calls")
            or not isinstance(content, str) or not content.strip() or message.get("refusal")):
        raise GenerationProviderError("provider_invalid_response", retryable=False)
    return content


class ObservedLocalTransport(httpx2.AsyncBaseTransport):
    def __init__(
        self, delegate: httpx2.AsyncBaseTransport, context: OrchestrationContext, *, dialect: str,
    ) -> None:
        self.delegate, self.context = delegate, context
        self.dialect = dialect

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        try:
            return await self._request(request)
        except (GenerationProviderError, AppError) as error:
            # OpenAI wraps transport exceptions. Preserve only our closed application errors.
            self.context.failure = error
            raise

    async def _request(self, request: httpx2.Request) -> httpx2.Response:
        state = self.context
        body = json.loads(request.content)
        if (body.get("model") != state.request.profile.runtime_model
                or body.get("stream", False) is not False):
            raise GenerationProviderError("orchestration_not_supported", retryable=False)
        policy = state.request.profile.orchestration
        assert policy is not None
        api = policy.local_http_api
        wire_body = body
        input_fields: tuple[str, ...] = _INPUT_FIELDS
        if api == "ollama_chat":
            if self.dialect != "ollama" or not request.url.path.endswith("/v1/chat/completions"):
                raise GenerationProviderError("orchestration_not_supported", retryable=False)
            wire_body = native_chat_request(
                body, manager=state.active_agent == MANAGER,
                runtime_options=policy.ollama_runtime,
                allowed_handoffs=state.allowed_handoffs(),
            )
            path = request.url.path.removesuffix("/v1/chat/completions") + "/api/chat"
            headers = request.headers.copy()
            headers.pop("content-length", None)
            request = httpx2.Request(
                "POST", request.url.copy_with(path=path), headers=headers,
                content=safe_json(wire_body).encode("utf-8"), extensions=request.extensions,
            )
            input_fields = _NATIVE_INPUT_FIELDS
        if state.revalidate is not None:
            await state.revalidate()
        state.reserve_model(body.get("max_tokens"))
        span = await state.collector.start_span(
            kind="model", name="chat_completion", parent_id=state.agent_spans[state.active_agent],
            model_name=state.request.profile.model_name, input_kind="http_request",
            input=safe_json({key: wire_body[key] for key in input_fields if key in wire_body}),
            evidence_refs=state.evidence_refs(),
            citation_reference_map=(CitationReferenceMap(
                evidence_ids=tuple(item.evidence_id for item in state.request.evidence),
            ) if state.active_agent != MANAGER
                and state.request.profile.prompt_ref == "rag-answer-v6" else None),
        )
        started = perf_counter()
        headers_ms: float | None = None
        body_ms: float | None = None
        validation_ms: float | None = None
        server_status: ServerTimingStatus = (
            "missing" if api == "ollama_chat" else "not_exposed_by_non_streaming_api"
        )
        server_timing: OllamaServerTiming | None = None
        usage: tuple[int | None, int | None] = (None, None)
        usage_recorded = False
        rejection: DelegationRejection | None = None

        async def complete_response() -> httpx2.Response:
            nonlocal headers_ms, body_ms
            response = await self.delegate.handle_async_request(request)
            headers_ms = (perf_counter() - started) * 1000
            try:
                length = response.headers.get("content-length")
                if length is not None and (not length.isdecimal()
                                           or int(length) > _MAX_RESPONSE_BYTES):
                    raise GenerationProviderError("provider_invalid_response", retryable=False)
                body = bytearray()
                # A partially received/oversized response cannot establish local termination.
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                        raise GenerationProviderError("provider_invalid_response", retryable=False)
                    body.extend(chunk)
                body_ms = (perf_counter() - started) * 1000
                headers = response.headers.copy()
                for name in ("content-encoding", "content-length", "transfer-encoding"):
                    headers.pop(name, None)
                return httpx2.Response(
                    response.status_code, headers=headers, content=bytes(body), request=request,
                )
            finally:
                # Close this response even when reading is cancelled or the receive cap is hit.
                await response.aclose()

        try:
            try:
                response = await track_local_http_attempt(complete_response())
            finally:
                request_ms = (perf_counter() - started) * 1000
            if not 200 <= response.status_code < 300:
                raise GenerationProviderError(
                    ("provider_rate_limited" if response.status_code == 429
                     else "provider_request_failed"),
                    retryable=False,
                )
            validating = perf_counter()
            try:
                payload = parse_http_json(response.text)
                if isinstance(payload, dict):
                    usage = _usage({
                        "prompt_tokens": payload.get("prompt_eval_count"),
                        "completion_tokens": payload.get("eval_count"),
                    } if api == "ollama_chat" else payload.get("usage"))
                if api == "ollama_chat":
                    server_status, server_timing = parse_ollama_timing(payload)
                    payload = native_chat_response(
                        payload, expected_model=state.request.profile.runtime_model,
                        delegation=state.active_agent == MANAGER or bool(state.allowed_handoffs()),
                    )
                    response = httpx2.Response(200, json=payload, request=request)
                state.usages.append(usage)
                usage_recorded = True
                output = _response_output(
                    payload, manager=state.active_agent == MANAGER,
                    expected_model=state.request.profile.runtime_model, dialect=self.dialect,
                    allowed_handoffs=state.allowed_handoffs(),
                    final_allowed=not state.autonomous or state.active_agent == SPECIALIST,
                )
                if state.autonomous and isinstance(payload, dict):
                    # Each HTTP request is stateless; local servers may reuse call IDs.
                    # SDK invocation IDs are run-scoped. Qualify only after validating
                    # exactly one approved handoff; preserve the provider's wire output.
                    calls = payload["choices"][0]["message"].get("tool_calls")
                    if calls:
                        calls[0]["id"] = f"rag_{state.model_calls}_{calls[0]['id']}"
                        response = httpx2.Response(200, json=payload, request=request)
            finally:
                validation_ms = (perf_counter() - validating) * 1000
        except DelegationRejection as error:
            rejection = error
            if not usage_recorded:
                # Native malformed delegation can fail before conversion returns usage.
                # Unrelated native envelope errors retain their existing unknown usage.
                state.usages.append(usage)
            raise
        finally:
            # Do not settle cancellation here: the outer timeout owns its final failed state.
            state.collector.attach_model_timing(
                span, request_duration_ms=request_ms, response_headers_ms=headers_ms,
                response_body_ms=body_ms, response_validation_ms=validation_ms,
                api=api, server_timing_status=server_status, server_timing=server_timing,
            )
            if rejection is not None:
                await state.collector.end_span(
                    span, state="failed", error_code=rejection.reason.value,
                    input_tokens=usage[0], output_tokens=usage[1],
                )
        await state.collector.end_span(
            span, output=output, input_tokens=usage[0], output_tokens=usage[1],
        )
        return response

    async def aclose(self) -> None:
        await self.delegate.aclose()
