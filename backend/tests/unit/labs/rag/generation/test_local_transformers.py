import json
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest

from ai_workshop.labs.rag.deployments.domain import ProviderKind
from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    GenerationRequest,
    GenerationStatus,
)
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.local_model_host import (
    LocalModelHost,
    LocalModelOutput,
    LocalModelSpec,
)
from ai_workshop.labs.rag.generation.local_transformers import (
    LocalTransformersRuntime,
    TransformersEngine,
)
from tests.unit.labs.rag.generation.test_openai_compatible import evidence, profile


class Engine:
    def __init__(self, text: str, *, truncated: bool = False):
        self.text = text
        self.truncated = truncated
        self.inputs = []

    def generate(self, **kwargs):
        self.inputs.append(kwargs)
        return LocalModelOutput(self.text, 123, 45, self.truncated)


def setup(tmp_path: Path, engine: Engine):
    original = profile()
    deployment = replace(
        original.deployment, provider=ProviderKind.LOCAL_TRANSFORMERS,
        endpoint_ref=None, local_model_ref="synthetic-model",
    )
    selected = replace(
        original, deployment=deployment, response_schema_version=2, prompt_ref="rag-answer-v2",
    )
    model_spec = LocalModelSpec(
        model_id=deployment.provider_model_id, revision="a" * 40,
        snapshot_path=tmp_path, max_input_tokens=1024,
    )
    host = LocalModelHost(loader=lambda _: engine)
    runtime = LocalTransformersRuntime(deployment=deployment, spec=model_spec, host=host)
    request = GenerationRequest("question", "resolved", (), (evidence(),), selected, "synthetic")
    return runtime, request


async def test_health_loads_and_generation_preserves_evidence_and_token_counts(tmp_path):
    claim = {"text": "Supported answer.", "evidence_ids": [str(evidence().evidence_id)]}
    engine = Engine(json.dumps({"schema_version": 2, "status": "answered", "claims": [claim]}))
    runtime, request = setup(tmp_path, engine)
    assert (await runtime.health()).ready
    result = await runtime.generate(request)
    assert result.generation.claims[0].evidence_ids == (evidence().evidence_id,)
    assert result.execution.input_tokens == 123
    assert result.execution.output_tokens == 45
    payload = json.loads(engine.inputs[0]["user_content"])
    assert payload["evidence"][0]["text"] == evidence().text
    await runtime.host.aclose()


async def test_contextualization_and_explicit_abstention(tmp_path):
    engine = Engine('{"resolved_query":"standalone question"}')
    runtime, request = setup(tmp_path, engine)
    result = await runtime.contextualize(ContextualizationRequest("question", (), request.profile))
    assert result.resolved_query == "standalone question"
    engine.text = '{"schema_version":2,"status":"insufficient_evidence","claims":[]}'
    assert (await runtime.generate(request)).status is GenerationStatus.INSUFFICIENT_EVIDENCE
    await runtime.host.aclose()


@pytest.mark.parametrize("status,claims", [
    ("answered", [{"text": "Supported.", "evidence_ids": [str(evidence().evidence_id)]}]),
    ("insufficient_evidence", []),
])
async def test_schema_v2_explicit_status_matches_existing_contract(tmp_path, status, claims):
    engine = Engine(json.dumps({"schema_version": 2, "status": status, "claims": claims}))
    runtime, request = setup(tmp_path, engine)
    result = await runtime.generate(request)
    assert result.status.value == status
    await runtime.host.aclose()


@pytest.mark.parametrize("text,truncated", [
    ('{"schema_version":2,"status":"insufficient_evidence","claims":[]}', True),
    ('```json\n{"schema_version":2,"status":"insufficient_evidence","claims":[]}\n```', False),
    ('{"schema_version":2,"status":"insufficient_evidence","claims":[],"claims":[]}', False),
    ('{"schema_version":2,"status":"insufficient_evidence","claims":[],"extra":true}', False),
    ('{"schema_version":2,"status":"answered","claims":[{"text":7,"evidence_ids":[]}]}', False),
    ('{"schema_version":2,"status":"answered","claims":'
     '[{"text":"x","evidence_ids":["invalid"]}]}', False),
    ('{"schema_version":2.0,"status":"insufficient_evidence","claims":[]}', False),
    ('{"schema_version":2,"claims":[]}', False),
    ('{"schema_version":2,"status":"answered","claims":[]}', False),
    ('{"schema_version":2,"status":"insufficient_evidence","claims":'
     '[{"text":"x","evidence_ids":["30000000-0000-0000-0000-000000000001"]}]}', False),
])
async def test_malformed_or_truncated_output_fails_explicitly(tmp_path, text, truncated):
    runtime, request = setup(tmp_path, Engine(text, truncated=truncated))
    with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
        await runtime.generate(request)
    await runtime.host.aclose()


async def test_unsupported_schema_does_not_load_engine(tmp_path):
    engine = Engine("unused")
    runtime, request = setup(tmp_path, engine)
    request = replace(request, profile=replace(request.profile, response_schema_version=3))
    with pytest.raises(GenerationProviderError, match="generation_schema_not_supported"):
        await runtime.generate(request)
    assert not engine.inputs
    await runtime.host.aclose()


async def test_health_does_not_claim_ready_when_loading_fails(tmp_path):
    runtime, _ = setup(tmp_path, Engine("unused"))
    await runtime.host.aclose()

    def failed_loader(spec):
        raise RuntimeError("private local file information")

    runtime.host = LocalModelHost(loader=failed_loader)
    with pytest.raises(GenerationProviderError, match="deployment_not_ready"):
        await runtime.health()
    await runtime.host.aclose()


class TokenBatch(list):
    @property
    def shape(self):
        return (1, len(self[0]))


def native_fakes(monkeypatch, tmp_path, *, input_count=2, generated=None):
    imports, calls = [], []

    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            assert messages[0]["role"] == "user"
            return "serialized chat"

        def __call__(self, prompt, **kwargs):
            assert kwargs["truncation"] is False
            return {"input_ids": TokenBatch([[1] * input_count])}

        def decode(self, values, **kwargs):
            return "decoded"

    class Model:
        config = SimpleNamespace(max_position_embeddings=2048)
        generation_config = SimpleNamespace(eos_token_id=9)

        def to(self, device):
            assert device == "cpu"
            return self

        def eval(self):
            calls.append("eval")
            return self

        def generate(self, **kwargs):
            calls.append(kwargs)
            return TokenBatch([[1] * input_count + (generated or [4, 9])])

    def tokenizer_loader(path, **kwargs):
        calls.append(("tokenizer", path, kwargs))
        return Tokenizer()

    def model_loader(path, **kwargs):
        calls.append(("model", path, kwargs))
        return Model()

    modules = {
        "torch": SimpleNamespace(float32="float32", inference_mode=nullcontext),
        "transformers": SimpleNamespace(
            AutoTokenizer=SimpleNamespace(from_pretrained=tokenizer_loader),
            AutoModelForCausalLM=SimpleNamespace(from_pretrained=model_loader),
            StoppingCriteriaList=list,
        ),
    }

    def import_module(name):
        imports.append(name)
        return modules[name]

    monkeypatch.setattr(
        "ai_workshop.labs.rag.generation.local_transformers.import_module", import_module,
    )
    snapshot = tmp_path / "models--synthetic--model" / "snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    spec = LocalModelSpec(
        model_id="synthetic/model", revision="a" * 40,
        snapshot_path=snapshot, max_input_tokens=8,
    )
    return spec, imports, calls


def test_native_backend_only_loads_pinned_local_safetensors(monkeypatch, tmp_path):
    spec, imports, calls = native_fakes(monkeypatch, tmp_path)
    engine = TransformersEngine(spec)
    result = engine.generate(
        system_prompt="rules", user_content="public fixture", max_output_tokens=4,
        temperature=0, stop=Event(), deadline=monotonic() + 5,
    )
    assert imports == ["torch", "transformers"]
    loads = [call for call in calls if isinstance(call, tuple)]
    assert len(loads) == 2
    for _, path, kwargs in loads:
        assert path == str(spec.snapshot_path)
        assert kwargs["local_files_only"] is True
        assert kwargs["trust_remote_code"] is False
    assert loads[1][2]["use_safetensors"] is True
    assert result.input_tokens == 2 and result.output_tokens == 2
    assert not result.truncated
    assert "eval" in calls
    options = next(call for call in calls if isinstance(call, dict))
    assert options["do_sample"] is False
    assert "temperature" not in options


def test_native_backend_rejects_unbound_revision_before_import(monkeypatch, tmp_path):
    spec, imports, _ = native_fakes(monkeypatch, tmp_path)
    wrong = spec.model_copy(update={"revision": "b" * 40})
    with pytest.raises(GenerationProviderError, match="deployment_not_ready"):
        TransformersEngine(wrong)
    assert not imports


def test_native_backend_rejects_oversized_prompt_without_truncation(monkeypatch, tmp_path):
    spec, _, calls = native_fakes(monkeypatch, tmp_path, input_count=9)
    engine = TransformersEngine(spec)
    with pytest.raises(GenerationProviderError, match="provider_input_too_large"):
        engine.generate(system_prompt="rules", user_content="fixture", max_output_tokens=4,
                        temperature=0, stop=Event(), deadline=monotonic() + 5)
    assert not any(isinstance(call, dict) for call in calls)


def test_native_backend_marks_token_limit_truncation(monkeypatch, tmp_path):
    spec, _, _ = native_fakes(monkeypatch, tmp_path, generated=[3, 4])
    engine = TransformersEngine(spec)
    result = engine.generate(system_prompt="rules", user_content="fixture", max_output_tokens=2,
                             temperature=0, stop=Event(), deadline=monotonic() + 5)
    assert result.truncated


@pytest.mark.parametrize("reason", ["cancel", "deadline"])
def test_native_stop_prevents_generation(monkeypatch, tmp_path, reason):
    spec, _, calls = native_fakes(monkeypatch, tmp_path)
    engine = TransformersEngine(spec)
    stop = Event()
    if reason == "cancel":
        stop.set()
    with pytest.raises(GenerationProviderError, match="provider_timeout"):
        engine.generate(
            system_prompt="rules", user_content="fixture", max_output_tokens=2,
            temperature=0, stop=stop,
            deadline=monotonic() + (5 if reason == "cancel" else -1),
        )
    assert not any(isinstance(call, dict) for call in calls)
