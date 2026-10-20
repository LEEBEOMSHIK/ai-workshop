"""Provider rejection diagnostics disclose only fixed categories and request UUIDs."""

import json
import logging

import httpx
import pytest

from ai_workshop.labs.rag.generation.domain import ContextualizationRequest, GenerationRequest
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.openai_compatible import LocalOpenAICompatibleRuntime
from ai_workshop.shared.request_context import correlation_id_context
from tests.unit.labs.rag.generation.test_openai_compatible import (
    assert_sanitized_error,
    client_for,
    evidence,
    local_deployment,
    ollama_completion,
    schema2_answer,
    schema2_profile,
)

CANARY = "PRIVATE-ANSWER-PROMPT-REASONING-SECRET"
CORRELATION = "90000000-0000-0000-0000-000000000099"
LOGGER = "ai_workshop.labs.rag.generation.openai_compatible"


def completion(content=None, **overrides):
    return httpx.Response(200, json=ollama_completion(
        json.dumps(schema2_answer()) if content is None else content,
        **overrides,
    ))


async def invoke(response, *, operation="generate"):
    calls = []

    def handler(request):
        calls.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    try:
        async with client_for(httpx.MockTransport(handler)) as client:
            runtime = LocalOpenAICompatibleRuntime(
                deployment=local_deployment(), endpoint="http://127.0.0.1:11434",
                api_key=CANARY, client=client, dialect="ollama",
            )
            if operation == "contextualize":
                return await runtime.contextualize(
                    ContextualizationRequest(CANARY, (), schema2_profile()),
                )
            return await runtime.generate(GenerationRequest(
                CANARY, CANARY, (), (evidence(),), schema2_profile(), CORRELATION,
            ))
    finally:
        assert len(calls) == 1


@pytest.mark.parametrize("response, stage, reason", [
    (httpx.Response(302, text=CANARY), "http", "redirect"),
    (httpx.Response(500, text=CANARY), "http", "error"),
    (RuntimeError(CANARY), "transport", "unexpected"),
    (httpx.Response(200, text=CANARY), "response_json", "invalid"),
    (httpx.Response(200, json=[CANARY]), "response_json", "not_object"),
    (httpx.Response(200, json={"choices": CANARY}), "envelope", "choices"),
    (httpx.Response(200, json={"choices": [CANARY]}), "envelope", "choice"),
    (httpx.Response(200, json={"choices": [{}, {}]}), "envelope", "choice_count"),
    (completion(choice_overrides={"finish_reason": "length"}), "finish", "length"),
    (completion(choice_overrides={"finish_reason": CANARY}), "finish", "not_stop"),
    (completion(choice_overrides={"finish_reason": {"secret": CANARY}}),
     "finish", "not_stop"),
    (completion(choice_overrides={"message": CANARY}), "envelope", "message"),
    (completion(message_overrides={CANARY: CANARY}), "message", "unsupported_fields"),
    (completion(message_overrides={"reasoning": {"private": CANARY}}),
     "message", "reasoning_type"),
    (completion(message_overrides={"role": CANARY}), "message", "role"),
    (completion(message_overrides={"tool_calls": [{"function": CANARY}]}),
     "message", "unsupported_output"),
    (completion(message_overrides={"content": [CANARY]}), "message", "content_type"),
    (completion(CANARY), "answer_json", "invalid"),
    (completion(json.dumps(schema2_answer() | {CANARY: CANARY})), "answer_schema", "extra_fields"),
    (completion(json.dumps(schema2_answer() | {"schema_version": 1})),
     "answer_contract", "invalid"),
    (completion(json.dumps(schema2_answer() | {"claims": []})), "answer_contract", "invalid"),
    (completion(json.dumps(schema2_answer() | {"claims": [
        {"text": CANARY, "evidence_ids": [CANARY]},
    ]})), "evidence_id", "invalid"),
    (completion(json.dumps(schema2_answer() | {"claims": [
        {"text": " ", "evidence_ids": [str(evidence().evidence_id)]},
    ]})), "claim", "invalid"),
])
async def test_rejection_records_exact_safe_stage_without_changing_public_error(
    response, stage, reason, caplog,
):
    token = correlation_id_context.set(CORRELATION)
    try:
        with (
            caplog.at_level(logging.WARNING, logger=LOGGER),
            pytest.raises(GenerationProviderError) as caught,
        ):
            await invoke(response)
    finally:
        correlation_id_context.reset(token)
    assert caught.value.code == "provider_invalid_response"
    assert caught.value.retryable is False
    assert_sanitized_error(caught.value, CANARY)
    records = [record for record in caplog.records if record.name == LOGGER]
    assert len(records) == 1
    assert records[0].getMessage().split(" categories=", 1)[0].split(" violations=", 1)[0] == (
        f"provider_response_rejected stage={stage} reason={reason} correlation_id={CORRELATION}"
    )
    assert records[0].exc_info is None
    assert CANARY not in caplog.text
    assert CANARY not in repr(records[0].args)


@pytest.mark.parametrize("content, stage, reason", [
    (CANARY, "context_json", "invalid"),
    (json.dumps({"resolved_query": CANARY, CANARY: CANARY}), "context_schema", "invalid"),
    (json.dumps({"resolved_query": " "}), "context_query", "empty"),
])
async def test_context_failure_uses_safe_categories_and_rejects_unsafe_correlation(
    content, stage, reason, caplog,
):
    token = correlation_id_context.set(CANARY + "\nforged-log")
    try:
        with (
            caplog.at_level(logging.WARNING, logger=LOGGER),
            pytest.raises(GenerationProviderError),
        ):
            await invoke(completion(content), operation="contextualize")
    finally:
        correlation_id_context.reset(token)
    records = [record for record in caplog.records if record.name == LOGGER]
    assert [record.getMessage() for record in records] == [
        f"provider_response_rejected stage={stage} reason={reason} correlation_id=unavailable",
    ]
    assert CANARY not in caplog.text


@pytest.mark.parametrize("status", ["answered", "insufficient_evidence"])
async def test_valid_output_and_ollama_reasoning_are_never_logged(status, caplog):
    answer = schema2_answer() | {"status": status}
    if status == "insufficient_evidence":
        answer["claims"] = []
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        result = await invoke(completion(
            json.dumps(answer), message_overrides={"reasoning": CANARY},
        ))
    assert result.status.value == status
    assert not [record for record in caplog.records if record.name == LOGGER]
    assert CANARY not in caplog.text


@pytest.mark.parametrize("answer, reason", [
    ({key: value for key, value in schema2_answer().items() if key != "status"}, "missing"),
    (schema2_answer() | {"claims": [{"text": CANARY}]}, "missing"),
    (schema2_answer() | {"schema_version": True}, "type"),
    (schema2_answer() | {"schema_version": "2"}, "type"),
    (schema2_answer() | {"claims": CANARY}, "type"),
    (schema2_answer() | {"claims": [CANARY]}, "type"),
    (schema2_answer() | {"claims": [{"text": 42, "evidence_ids": [CANARY]}]}, "type"),
    (schema2_answer() | {"claims": [{"text": CANARY, "evidence_ids": [None]}]}, "type"),
    (schema2_answer() | {"claims": [{"text": 42, "evidence_ids": [None]}]}, "type"),
    ([CANARY], "type"),
    (None, "type"),
    (schema2_answer() | {CANARY: CANARY}, "extra_fields"),
    (schema2_answer() | {"claims": [schema2_answer()["claims"][0] | {CANARY: CANARY}]},
     "extra_fields"),
    (schema2_answer() | {"status": CANARY}, "literal"),
    (schema2_answer() | {"claims": [{"text": CANARY, "evidence_ids": []}]}, "constraint"),
    ({"schema_version": 2, "claims": [], CANARY: CANARY}, "mixed"),
    (schema2_answer() | {"schema_version": CANARY, "status": CANARY}, "mixed"),
])
async def test_schema_rejection_has_bounded_reason_and_no_fields_or_values(answer, reason, caplog):
    with pytest.raises(GenerationProviderError) as caught:
        await invoke(completion(json.dumps(answer)))
    assert caught.value.code == "provider_invalid_response"
    assert caught.value.retryable is False
    assert_sanitized_error(caught.value, CANARY)
    records = [record for record in caplog.records if record.name == LOGGER]
    assert [record.getMessage().split(" categories=", 1)[0] for record in records] == [
        f"provider_response_rejected stage=answer_schema reason={reason} "
        "correlation_id=unavailable",
    ]
    assert all(record.exc_info is None for record in records)
    assert CANARY not in repr(records[0].__dict__)


async def test_unrecognized_schema_error_never_becomes_a_free_text_log(monkeypatch, caplog):
    from pydantic import ValidationError
    from pydantic_core import PydanticCustomError

    from ai_workshop.labs.rag.generation.openai_compatible import _AnswerV2

    def reject(_value):
        raise ValidationError.from_exception_data(CANARY, [{
            "type": PydanticCustomError(CANARY, CANARY, {CANARY: CANARY}),
            "loc": (CANARY,), "input": CANARY,
        }])

    monkeypatch.setattr(_AnswerV2, "model_validate", reject)
    with pytest.raises(GenerationProviderError) as caught:
        await invoke(completion())
    assert_sanitized_error(caught.value, CANARY)
    records = [record for record in caplog.records if record.name == LOGGER]
    assert [record.getMessage() for record in records] == [
        "provider_response_rejected stage=answer_schema reason=invalid correlation_id=unavailable "
        "categories=invalid fields=invalid:unknown",
    ]
    assert CANARY not in repr(records[0].__dict__)


@pytest.mark.parametrize("status", ["answered", "insufficient_evidence"])
async def test_wire_json_schema_preserves_prompt_contract_and_local_validation(status):
    from ai_workshop.labs.rag.generation.openai_compatible import _AnswerV2
    from tests.unit.labs.rag.generation.test_openai_compatible import dialect_call

    answer = schema2_answer() | {"status": status}
    if status == "insufficient_evidence":
        answer["claims"] = []
    result, sent = await dialect_call(ollama_completion(json.dumps(answer)))
    assert sent["response_format"] == {
        "type": "json_schema", "json_schema": {"schema": _AnswerV2.model_json_schema()},
    }
    prompt = sent["messages"][0]["content"]
    start = prompt.index('Return only JSON: ') + len('Return only JSON: ')
    example, _ = json.JSONDecoder().raw_decode(prompt[start:])
    assert set(example) == set(answer) == {"schema_version", "status", "claims"}
    assert set(example["claims"][0]) == {"text", "evidence_ids"}
    assert example["schema_version"] == 2
    assert example["status"] == "answered"
    assert 'status "insufficient_evidence" and claims []' in prompt
    assert 'No extra keys' in prompt
    assert result.status.value == status
    assert sent["max_tokens"] == schema2_profile().max_output_tokens


@pytest.mark.parametrize("answer, categories, fields", [
    ({"schema_version": 2, "claims": [], CANARY: CANARY},
     "extra_fields,missing", "extra_fields:root.extra,missing:status"),
    ({"schema_version": True, "status": CANARY, "claims": [
        {"text": 42, "evidence_ids": [], CANARY: CANARY}, {"text": CANARY},
    ]}, "constraint,extra_fields,literal,missing,type",
     "constraint:claims.item.evidence_ids,extra_fields:claims.item.extra,literal:status,"
     "missing:claims.item.evidence_ids,type:claims.item.text,type:schema_version"),
    (schema2_answer() | {"claims": [{"text": 42, "evidence_ids": [None]}] * 1000},
     "type", "type:claims.item.evidence_ids.item,type:claims.item.text"),
    ([CANARY], "type", "type:root"),
    (schema2_answer() | {"claims": CANARY}, "type", "type:claims"),
    (schema2_answer() | {"claims": [CANARY]}, "type", "type:claims.item"),
])
async def test_schema_diagnostic_preserves_sorted_unique_categories_and_fixed_paths(
    answer, categories, fields, caplog,
):
    with pytest.raises(GenerationProviderError) as caught:
        await invoke(completion(json.dumps(answer), message_overrides={"reasoning": CANARY}))
    assert caught.value.code == "provider_invalid_response"
    assert caught.value.retryable is False
    records = [record for record in caplog.records if record.name == LOGGER]
    assert len(records) == 1
    reason = "mixed" if "," in categories else categories
    assert records[0].getMessage() == (
        f"provider_response_rejected stage=answer_schema reason={reason} "
        f"correlation_id=unavailable categories={categories} fields={fields}"
    )
    assert len(records[0].getMessage()) < 4096
    assert CANARY not in repr(records[0].__dict__)
    assert records[0].exc_info is None


@pytest.mark.parametrize("location", [
    (CANARY,), ("claims", CANARY, "text"), ("claims", 0, CANARY),
    ("claims", 0, "evidence_ids", CANARY), ("status", CANARY),
    ("claims", -1, "text"), ("claims", 1, "text", CANARY),
])
async def test_unknown_schema_locations_are_redacted(monkeypatch, caplog, location):
    from pydantic import ValidationError
    from pydantic_core import PydanticCustomError

    from ai_workshop.labs.rag.generation.openai_compatible import _AnswerV2

    def reject(_value):
        raise ValidationError.from_exception_data(CANARY, [{
            "type": PydanticCustomError(CANARY, CANARY, {CANARY: CANARY}),
            "loc": location, "input": CANARY,
        }])

    monkeypatch.setattr(_AnswerV2, "model_validate", reject)
    with pytest.raises(GenerationProviderError):
        await invoke(completion())
    record, = [r for r in caplog.records if r.name == LOGGER]
    assert record.getMessage().endswith(" categories=invalid fields=invalid:unknown")
    assert CANARY not in repr(record.__dict__)


async def test_schema_diagnostic_bound_and_order_do_not_depend_on_error_count(monkeypatch, caplog):
    from pydantic import ValidationError
    from pydantic_core import PydanticCustomError

    from ai_workshop.labs.rag.generation.openai_compatible import _AnswerV2

    locations = [(), ("schema_version",), ("status",), ("claims",), ("claims", 999),
                 ("claims", 999, "text"), ("claims", 999, "evidence_ids"),
                 ("claims", 999, "evidence_ids", 999), (CANARY,), ("claims", 999, CANARY)]
    items = [{"type": PydanticCustomError(kind, CANARY, {CANARY: CANARY}),
              "loc": location, "input": CANARY}
             for kind in ["missing", "int_type", "extra_forbidden", "literal_error",
                          "too_short", CANARY] for location in locations] * 100

    def reject(_value):
        raise ValidationError.from_exception_data(CANARY, items)

    monkeypatch.setattr(_AnswerV2, "model_validate", reject)
    for _ in range(2):
        with pytest.raises(GenerationProviderError) as caught:
            await invoke(completion())
        assert caught.value.retryable is False
        assert_sanitized_error(caught.value, CANARY)
        items.reverse()
    first, second = [r for r in caplog.records if r.name == LOGGER]
    assert first.getMessage() == second.getMessage()
    message = first.getMessage()
    assert " categories=constraint,extra_fields,invalid,literal,missing,type " in message
    fields = message.split(" fields=", 1)[1].split(",")
    assert fields == sorted(set(fields))
    assert len(fields) <= 66
    assert len(message) < 4096
    assert "999" not in message
    assert CANARY not in repr(first.__dict__) + repr(second.__dict__)


@pytest.mark.parametrize("version", [-1, 0, 1, 2, 3, 99])
@pytest.mark.parametrize("status", ["answered", "insufficient_evidence"])
@pytest.mark.parametrize("count", [0, 1, 100])
async def test_contract_diagnostics_report_every_fixed_violation(version, status, count, caplog):
    answer = {"schema_version": version, "status": status, "claims": [
        {"text": CANARY, "evidence_ids": [str(evidence().evidence_id)]},
    ] * count}
    expected = []
    if version != 2:
        expected.append("schema_version")
    if status == "answered" and count == 0:
        expected.append("answered_without_claims")
    if status == "insufficient_evidence" and count > 0:
        expected.append("insufficient_with_claims")
    token = correlation_id_context.set(CORRELATION)
    try:
        if expected:
            with pytest.raises(GenerationProviderError) as caught:
                await invoke(completion(json.dumps(answer)))
            assert caught.value.code == "provider_invalid_response"
            assert caught.value.retryable is False
            assert_sanitized_error(caught.value, CANARY)
        else:
            result = await invoke(completion(json.dumps(answer)))
            assert result.status.value == status
            if status == "answered":
                assert len(result.generation.claims) == count
            else:
                assert result.generation is None
    finally:
        correlation_id_context.reset(token)
    records = [r for r in caplog.records if r.name == LOGGER]
    if expected:
        assert len(records) == 1
        assert records[0].getMessage() == (
            f"provider_response_rejected stage=answer_contract reason=invalid "
            f"correlation_id={CORRELATION} violations={','.join(sorted(expected))}"
        )
        assert records[0].exc_info is None
        assert CANARY not in repr(records[0].__dict__)
    else:
        assert records == []


@pytest.mark.parametrize("version", [2.0, True, "2"])
async def test_exact_version_schema_keeps_local_strict_integer_validation(version, caplog):
    with pytest.raises(GenerationProviderError) as caught:
        await invoke(completion(json.dumps(schema2_answer() | {"schema_version": version})))
    assert caught.value.retryable is False
    record, = [r for r in caplog.records if r.name == LOGGER]
    assert "stage=answer_schema reason=type" in record.getMessage()
    assert record.getMessage().endswith("categories=type fields=type:schema_version")
