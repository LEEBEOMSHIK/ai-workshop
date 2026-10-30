"""Offline contract tests for the explicitly selected native Ollama bridge."""

from copy import deepcopy
from typing import Any

import pytest

from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.orchestration.domain import ANSWER_TOOL
from ai_workshop.labs.rag.orchestration.ollama_chat import (
    native_chat_request,
    native_chat_response,
)


def request() -> dict[str, Any]:
    return {"model": "local:alias", "messages": [{"role": "system", "content": "rules"},
            {"role": "user", "content": "question"}], "temperature": 0.0, "max_tokens": 128}


def response() -> dict[str, Any]:
    return {"model": "local:alias", "done": True, "done_reason": "stop",
            "message": {"role": "assistant", "content": "answer", "thinking": "private"},
            "prompt_eval_count": 12, "eval_count": 3}


def test_specialist_wire_semantics_and_input_preservation() -> None:
    body = request()
    body.update(reasoning_effort="none", store=False, response_format={
        "type": "json_schema", "json_schema": {"name": "answer", "strict": True,
        "schema": {"type": "object", "properties": {}}}})
    before = deepcopy(body)
    actual = native_chat_request(body, manager=False)
    assert actual == {"model": "local:alias", "messages": body["messages"], "stream": False,
                      "options": {"temperature": 0.0, "top_p": 1.0, "num_predict": 128},
                      "think": False, "format": {"type": "object", "properties": {}}}
    assert body == before


def test_manager_tool_constraint_is_retained_for_application_validation() -> None:
    body = request()
    body.update(tool_choice="required", parallel_tool_calls=False, tools=[{
        "type": "function", "function": {"name": ANSWER_TOOL, "description": "answer",
        "strict": True, "parameters": {"type": "object"}}}])
    actual = native_chat_request(body, manager=True)
    assert actual["tools"] == [{"type": "function", "function": {
        "name": ANSWER_TOOL, "description": "answer", "parameters": {"type": "object"}}}]
    assert "think" not in actual
    assert "tool_choice" not in actual


@pytest.mark.parametrize("patch", [
    {"unknown": True}, {"stream": True}, {"store": True}, {"reasoning_effort": "high"},
    {"max_tokens": True}, {"temperature": float("nan")}, {"tools": []},
    {"tool_choice": "required"}, {"parallel_tool_calls": True},
    {"messages": [{"role": "user", "content": [{"type": "image_url"}]}]},
    {"messages": [{"role": "user", "content": "text", "unexpected": 1}]},
    {"response_format": {"type": "json_schema", "json_schema": {"schema": "bad"}}},
])
def test_unsupported_requests_fail_closed(patch: dict[str, Any]) -> None:
    with pytest.raises(GenerationProviderError):
        native_chat_request(request() | patch, manager=False)


def test_response_preserves_usage_and_discards_private_fields() -> None:
    actual = native_chat_response(response(), expected_model="local:alias")
    assert actual["choices"] == [{"index": 0, "message": {
        "role": "assistant", "content": "answer"}, "finish_reason": "stop"}]
    assert actual["usage"] == {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
    assert "private" not in str(actual)


def test_tool_id_and_arguments_preserved_and_length_not_normalized() -> None:
    payload = response()
    payload["message"]["tool_calls"] = [{"id": "call_actual", "function": {
        "name": ANSWER_TOOL, "arguments": {"task": "answer"}, "index": 0}}]
    actual = native_chat_response(payload, expected_model="local:alias")
    choice = actual["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["id"] == "call_actual"
    assert choice["message"]["tool_calls"][0]["function"]["arguments"] == '{"task":"answer"}'
    payload["done_reason"] = "length"
    truncated = native_chat_response(payload, expected_model="local:alias")
    assert truncated["choices"][0]["finish_reason"] == "length"


@pytest.mark.parametrize("patch", [
    {"tool_choice": "auto"}, {"parallel_tool_calls": True}, {"tools": []},
    {"tools": [{"type": "function", "function": {
        "name": "unapproved", "parameters": {"type": "object"}}}]},
])
def test_manager_rejects_unenforceable_or_unapproved_tool_requests(patch: dict[str, Any]) -> None:
    body = request() | {"tool_choice": "required", "parallel_tool_calls": False, "tools": [
        {"type": "function", "function": {"name": ANSWER_TOOL, "parameters": {}}}]}
    with pytest.raises(GenerationProviderError):
        native_chat_request(body | patch, manager=True)


@pytest.mark.parametrize("arguments", ["{}", [], {"number": float("nan")}])
def test_tool_arguments_must_be_json_object(arguments: object) -> None:
    payload = response()
    payload["message"]["tool_calls"] = [{"id": "call_actual", "function": {
        "name": ANSWER_TOOL, "arguments": arguments}}]
    with pytest.raises(GenerationProviderError):
        native_chat_response(payload, expected_model="local:alias")


@pytest.mark.parametrize("patch", [
    {"model": "different"}, {"done": False}, {"done": 1}, {"done_reason": "unknown"},
    {"message": {"role": "user", "content": "answer"}},
    {"message": {"role": "assistant", "content": 1}},
    {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {
        "name": ANSWER_TOOL, "arguments": {}}}]}},
])
def test_invalid_native_response_fails_closed(patch: dict[str, Any]) -> None:
    with pytest.raises(GenerationProviderError):
        native_chat_response(response() | patch, expected_model="local:alias")


def test_invalid_optional_usage_is_unknown_not_zero() -> None:
    actual = native_chat_response(response() | {"eval_count": True}, expected_model="local:alias")
    assert actual["usage"] == {"prompt_tokens": 12, "completion_tokens": None, "total_tokens": None}
