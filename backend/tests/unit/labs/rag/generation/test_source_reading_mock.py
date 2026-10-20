"""Run real prompt/serialization/parsing with a synchronous-completing fake I/O boundary.

No event loop or socket is opened. Authored responses prove compatibility, not
that a model will obey v4 or classify rules/conditions/examples correctly.
"""

import json
from typing import Any

import pytest

from ai_workshop.labs.rag.evaluation.offline_rubric import Answer, Claim, Evidence, Rubric, assess
from ai_workshop.labs.rag.generation.domain import GenerationRequest, GenerationStatus
from ai_workshop.labs.rag.generation.execution import ProviderGenerationResult
from ai_workshop.labs.rag.generation.openai_compatible import LocalOpenAICompatibleRuntime
from ai_workshop.labs.rag.generation.prompts import load_prompt
from tests.unit.labs.rag.generation.test_source_reading import (
    FIXTURE,
    fixture,
    request_for,
    source_units,
    stored_evidence,
)


class MockBoundaryRuntime(LocalOpenAICompatibleRuntime):
    def __init__(self, request: GenerationRequest, answer: dict[str, Any]) -> None:
        assert request.profile.deployment is not None
        super().__init__(
            deployment=request.profile.deployment,
            endpoint="http://127.0.0.1:11434",
            dialect="ollama",
        )
        self.answer = answer
        self.sent: list[dict[str, Any]] = []

    async def _request_json(
        self,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        strict_json: bool = False,
    ) -> dict[str, Any]:
        assert method == "POST" and path == "/v1/chat/completions"
        assert json_body is not None
        self.sent.append(json_body)
        return {
            "model": self.deployment.provider_model_id,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(self.answer, ensure_ascii=False),
                    },
                }
            ],
        }


def complete_without_io(
    runtime: MockBoundaryRuntime, request: GenerationRequest
) -> ProviderGenerationResult:
    operation = runtime.generate(request)
    try:
        operation.send(None)
    except StopIteration as done:
        assert isinstance(done.value, ProviderGenerationResult)
        return done.value
    finally:
        operation.close()
    raise AssertionError("Mock path unexpectedly suspended; no event loop/I/O is permitted.")


@pytest.mark.parametrize("schema", [1, 2])
@pytest.mark.parametrize("scenario", fixture()["scenarios"], ids=lambda c: c["name"])
def test_authored_mock_responses_preserve_schema_and_citations(
    schema: int, scenario: dict[str, Any]
) -> None:
    items = source_units(scenario["texts"])
    request = request_for(items, schema=schema, question=scenario["question"])
    text = scenario["mock_claim"]
    claims = (
        [{"text": text, "evidence_ids": [str(item.evidence_id) for item in items]}] if text else []
    )
    answer = {"schema_version": schema, "claims": claims}
    if schema == 2:
        answer["status"] = "answered" if claims else "insufficient_evidence"
    runtime = MockBoundaryRuntime(request, answer)
    result = complete_without_io(runtime, request)
    assert len(runtime.sent) == 1
    body = runtime.sent[0]
    assert load_prompt("rag-answer-v4") in body["messages"][0]["content"]
    assert (
        json.loads(body["messages"][1]["content"])["source_reading"]["semantic_roles"]
        == "not_assigned"
    )
    assert body["max_tokens"] == request.profile.max_output_tokens
    if text:
        assert result.generation is not None
        assert result.generation.schema_version == schema
        assert result.generation.claims[0].text == text
        assert result.generation.claims[0].evidence_ids == tuple(item.evidence_id for item in items)
    else:
        assert result.status is GenerationStatus.INSUFFICIENT_EVIDENCE
        assert result.generation is None


def test_replaying_old_bad_answer_through_v4_does_not_turn_it_into_a_good_answer() -> None:
    original = json.loads(
        (FIXTURE.parent / "offline_payment_rubric.json").read_text(encoding="utf-8")
    )
    observed = original["observed_answer"]
    request = request_for(stored_evidence())
    runtime = MockBoundaryRuntime(
        request,
        {
            "schema_version": 2,
            "status": "answered",
            "claims": observed["claims"],
        },
    )
    result = complete_without_io(runtime, request)
    assert result.generation is not None
    answer = Answer(
        status="answered",
        answer=" ".join(c.text for c in result.generation.claims),
        claims=tuple(
            Claim(text=c.text, evidence_ids=c.evidence_ids) for c in result.generation.claims
        ),
        citation_validation="passed",
    )
    assert answer.model_dump(mode="json") == observed
    report = assess(
        answer,
        Rubric.model_validate(original["rubric"]),
        tuple(Evidence.model_validate(e) for e in original["evidence"]),
    )
    assert {f.code for f in report.findings} == {
        "required_rule_missing",
        "example_condition_missing",
        "example_support_incomplete",
    }
    assert report.status == "failed"
