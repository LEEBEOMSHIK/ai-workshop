"""Opt-in direct-answer prompt contract; not an actual model quality evaluation."""

import json
from dataclasses import replace

import httpx
import pytest

from ai_workshop.labs.rag.generation.domain import GenerationRequest
from ai_workshop.labs.rag.generation.openai_compatible import LocalOpenAICompatibleRuntime
from ai_workshop.labs.rag.generation.prompts import load_prompt, prompt_reference_version
from ai_workshop.labs.rag.models.context_evidence import EvidenceBudget, resolve_evidence_budget
from tests.unit.labs.rag.generation.test_openai_compatible import (
    client_for,
    evidence,
    local_deployment,
    ollama_completion,
    schema2_answer,
    schema2_profile,
)

REF = "rag-answer-v3"


def test_direct_answer_is_a_distinct_opt_in_version_with_general_rule_priority():
    text = load_prompt(REF)
    assert prompt_reference_version(REF) == 3
    assert text != load_prompt("rag-answer-v2")
    for requirement in ("일반 규칙", "먼저", "예시", "질문에 없는", "추정하지", "비신뢰"):
        assert requirement in text
    assert "T+4" not in text and "AM-SYN" not in text


def test_direct_answer_requires_an_explicit_context_budget():
    config = {"prompt_ref": REF, "context_evidence": {
        "version": 1, "max_groups": 8, "max_units": 32, "max_characters": 12000,
    }}
    assert resolve_evidence_budget(config) == EvidenceBudget(8, 32, 12000)
    with pytest.raises(ValueError, match="explicit evidence budget"):
        resolve_evidence_budget({"prompt_ref": REF})


async def test_http_request_uses_selected_v3_without_changing_schema_or_citation_ids():
    sent = []

    async def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=ollama_completion(json.dumps(schema2_answer())))

    selected = replace(schema2_profile(), prompt_ref=REF)
    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=selected.deployment, endpoint="http://127.0.0.1:11434",
            client=client, dialect="ollama",
        )
        result = await runtime.generate(GenerationRequest(
            "합성 상품의 지급 기간?", "합성 상품의 지급 기간?", (), (evidence(),), selected,
            "synthetic",
        ))
    assert len(sent) == 1
    assert load_prompt(REF) in sent[0]["messages"][0]["content"]
    assert sent[0]["model"] == local_deployment().provider_model_id
    assert sent[0]["max_tokens"] == selected.max_output_tokens
    assert result.generation.schema_version == 2
    assert result.generation.claims[0].evidence_ids == (evidence().evidence_id,)
