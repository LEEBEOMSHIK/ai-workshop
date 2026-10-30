"""Bounded Ollama 0.40.3 text-chat codec; policy selection lives outside this module."""

import json
import math
from collections.abc import Mapping
from typing import Any, NoReturn
from uuid import uuid4

from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.models.orchestration_policy import OllamaRuntimeOptions
from ai_workshop.labs.rag.orchestration.domain import ANSWER_TOOL
from ai_workshop.labs.rag.orchestration.rejections import (
    DelegationRejection,
    DelegationRejectionReason,
)

_FIELDS = {"model", "messages", "temperature", "max_tokens", "response_format", "tool_choice",
           "tools", "parallel_tool_calls", "reasoning_effort", "stream", "store"}


def _unsupported() -> NoReturn:
    raise GenerationProviderError("orchestration_not_supported", retryable=False)


def _invalid() -> NoReturn:
    raise GenerationProviderError("provider_invalid_response", retryable=False)


def native_chat_request(
    body: Mapping[str, Any], *, manager: bool,
    runtime_options: OllamaRuntimeOptions | None = None,
    allowed_handoffs: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Translate bounded SDK requests and explicitly selected typed runtime options."""
    if (set(body) - _FIELDS or not isinstance(body.get("model"), str) or not body["model"]
            or body.get("stream", False) is not False or body.get("store", False) is not False):
        _unsupported()
    temperature = body.get("temperature", 1.0)
    limit = body.get("max_tokens")
    if (type(temperature) not in (int, float) or not math.isfinite(temperature)
            or not 0 <= temperature <= 2 or type(limit) is not int or not 1 <= limit <= 2**31 - 1):
        _unsupported()
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        _unsupported()
    converted = []
    for message in messages:
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message.get("role") not in ("system", "user", "assistant")
                or not isinstance(message.get("content"), str)):
            _unsupported()
        converted.append(dict(message))
    result: dict[str, Any] = {
        "model": body["model"], "messages": converted, "stream": False,
        "options": {"temperature": temperature, "top_p": 1.0, "num_predict": limit},
    }
    if runtime_options is not None:
        if runtime_options.num_batch is not None:
            result["options"]["num_batch"] = runtime_options.num_batch
        if runtime_options.num_thread is not None:
            result["options"]["num_thread"] = runtime_options.num_thread
    if "reasoning_effort" in body:
        if body["reasoning_effort"] != "none":
            _unsupported()
        result["think"] = False
    if allowed_handoffs:
        tools = body.get("tools")
        if (manager or body.get("tool_choice", "auto") not in ("auto", "required")
                or body.get("parallel_tool_calls") is not False
                or not isinstance(tools, list) or len(tools) != len(allowed_handoffs)):
            _unsupported()
        converted_tools = []
        names = []
        for tool in tools:
            if (not isinstance(tool, dict) or set(tool) != {"type", "function"}
                    or tool.get("type") != "function"
                    or not isinstance(tool.get("function"), dict)):
                _unsupported()
            function = tool["function"]
            if (set(function) - {"name", "description", "parameters", "strict"}
                    or function.get("name") not in allowed_handoffs
                    or not isinstance(function.get("parameters"), dict)
                    or ("description" in function and not isinstance(function["description"], str))
                    or ("strict" in function and type(function["strict"]) is not bool)):
                _unsupported()
            names.append(function["name"])
            converted_tools.append({"type": "function", "function": {
                key: value for key, value in function.items() if key != "strict"}})
        if len(set(names)) != len(allowed_handoffs):
            _unsupported()
        result["tools"] = converted_tools
    elif manager:
        tools = body.get("tools")
        if (body.get("tool_choice") != "required" or body.get("parallel_tool_calls") is not False
                or "response_format" in body or not isinstance(tools, list) or len(tools) != 1):
            _unsupported()
        tool = tools[0]
        if (not isinstance(tool, dict) or set(tool) != {"type", "function"}
                or tool.get("type") != "function" or not isinstance(tool.get("function"), dict)):
            _unsupported()
        function = tool["function"]
        if (set(function) - {"name", "description", "parameters", "strict"}
                or function.get("name") != ANSWER_TOOL
                or not isinstance(function.get("parameters"), dict)
                or ("description" in function and not isinstance(function["description"], str))
                or ("strict" in function and type(function["strict"]) is not bool)):
            _unsupported()
        # The server ignores strict/tool_choice/parallel controls. The caller enforces
        # exactly one approved delegation before allowing SDK tool execution.
        result["tools"] = [{"type": "function", "function": {
            key: value for key, value in function.items() if key != "strict"}}]
    elif any(key in body for key in ("tools", "tool_choice", "parallel_tool_calls")):
        _unsupported()
    if "response_format" in body:
        response_format = body["response_format"]
        if (not isinstance(response_format, dict)
                or set(response_format) != {"type", "json_schema"}
                or response_format["type"] != "json_schema"):
            _unsupported()
        schema = response_format["json_schema"]
        if (not isinstance(schema, dict) or set(schema) - {"name", "strict", "schema"}
                or not isinstance(schema.get("schema"), dict)
                or ("name" in schema and not isinstance(schema["name"], str))
                or ("strict" in schema and type(schema["strict"]) is not bool)):
            _unsupported()
        result["format"] = schema["schema"]
    return result


def _count(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**31 - 1 else None


def native_chat_response(
    payload: Any, *, expected_model: str, delegation: bool = False,
) -> dict[str, Any]:
    """Produce the SDK envelope without retaining arbitrary fields or hidden thinking."""
    def invalid_call(reason: DelegationRejectionReason) -> NoReturn:
        if delegation:
            raise DelegationRejection(reason, provider_error=True)
        _invalid()

    if not isinstance(payload, dict):
        _invalid()
    if payload.get("model") != expected_model:
        raise GenerationProviderError("provider_model_mismatch", retryable=False)
    reason = payload.get("done_reason")
    message = payload.get("message")
    if (payload.get("done") is not True or reason not in ("stop", "length")
            or not isinstance(message, dict) or message.get("role") != "assistant"
            or not isinstance(message.get("content"), str)):
        _invalid()
    output: dict[str, Any] = {"role": "assistant", "content": message["content"]}
    calls = message.get("tool_calls", [])
    if not isinstance(calls, list):
        invalid_call(DelegationRejectionReason.MALFORMED_TOOL_CALL)
    converted = []
    for call in calls:
        if (not isinstance(call, dict) or not isinstance(call.get("id"), str)
                or not call["id"] or not isinstance(call.get("function"), dict)):
            invalid_call(DelegationRejectionReason.MALFORMED_TOOL_CALL)
        function = call["function"]
        if not isinstance(function.get("name"), str) or not function["name"]:
            invalid_call(DelegationRejectionReason.MALFORMED_TOOL_CALL)
        if not isinstance(function.get("arguments"), dict):
            invalid_call(DelegationRejectionReason.INVALID_ARGUMENTS)
        try:
            arguments = json.dumps(function["arguments"], ensure_ascii=False,
                                   separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            invalid_call(DelegationRejectionReason.INVALID_ARGUMENTS)
        converted.append({"id": call["id"], "type": "function", "function": {
            "name": function["name"], "arguments": arguments}})
    if converted:
        output["tool_calls"] = converted
        if reason == "stop":
            reason = "tool_calls"
    prompt = _count(payload.get("prompt_eval_count"))
    completion = _count(payload.get("eval_count"))
    return {"id": "chatcmpl-local-" + uuid4().hex, "object": "chat.completion", "created": 0,
            "model": expected_model, "choices": [{"index": 0, "message": output,
                                                    "finish_reason": reason}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                      "total_tokens": (prompt + completion
                                       if prompt is not None and completion is not None else None)}}
