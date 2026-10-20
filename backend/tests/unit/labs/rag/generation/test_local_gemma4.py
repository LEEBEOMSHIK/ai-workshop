from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.local_model_host import LocalModelSpec
from ai_workshop.labs.rag.generation.local_transformers import TransformersEngine
from tests.unit.labs.rag.generation.test_local_transformers import native_fakes


def gemma_engine(monkeypatch, tmp_path):
    spec, _, calls = native_fakes(monkeypatch, tmp_path)
    engine = TransformersEngine(spec)
    engine.model.config = SimpleNamespace(
        model_type="gemma4", text_config=SimpleNamespace(max_position_embeddings=8),
    )
    captured = {}

    def template(messages, **kwargs):
        captured.update(messages=messages, template_options=kwargs)
        return "serialized Gemma4 prompt"

    def decode(tokens, **kwargs):
        captured["decode_options"] = kwargs
        return "final<turn|>"

    def parse(response, **kwargs):
        captured.update(response=response, parse_options=kwargs)
        return {"role": "assistant", "content": "final", "thinking": "", "tool_calls": []}

    engine.tokenizer.apply_chat_template = template
    engine.tokenizer.decode = decode
    engine.tokenizer.parse_response = parse
    engine.tokenizer.all_special_tokens = ["<|channel>", "<channel|>", "<|turn>", "<turn|>"]
    return engine, captured, calls


def generate(engine, *, max_output_tokens=4):
    return engine.generate(
        system_prompt="rules", user_content="public fixture", max_output_tokens=max_output_tokens,
        temperature=0, stop=Event(), deadline=monotonic() + 5,
    )


def test_explicit_bfloat16_reaches_loader_without_precision_fallback(monkeypatch, tmp_path):
    spec, _, calls = native_fakes(monkeypatch, tmp_path)
    spec = LocalModelSpec.model_validate({**spec.model_dump(), "dtype": "bfloat16"})
    from ai_workshop.labs.rag.generation import local_transformers

    # Only the native module boundary is fake; the production loading path executes.
    local_transformers.import_module("torch").bfloat16 = "bfloat16"
    TransformersEngine(spec)
    load = next(call for call in calls if isinstance(call, tuple) and call[0] == "model")
    assert load[2]["dtype"] == "bfloat16"


def test_unsupported_precision_remains_invalid(monkeypatch, tmp_path):
    spec, _, _ = native_fakes(monkeypatch, tmp_path)
    assert spec.dtype == "float32"
    with pytest.raises(ValidationError):
        LocalModelSpec.model_validate({**spec.model_dump(), "dtype": "auto"})


def test_gemma4_preserves_roles_disables_thinking_and_returns_final_only(monkeypatch, tmp_path):
    engine, captured, _ = gemma_engine(monkeypatch, tmp_path)
    output = generate(engine)
    assert output.text == "final"
    assert (output.input_tokens, output.output_tokens, output.truncated) == (2, 2, False)
    assert captured["messages"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "public fixture"},
    ]
    assert captured["template_options"]["enable_thinking"] is False
    assert captured["decode_options"]["skip_special_tokens"] is False
    assert captured["parse_options"] == {"prefix": "serialized Gemma4 prompt"}


@pytest.mark.parametrize("context_source", ["nested", "getter"])
def test_nested_text_context_limits_input_plus_output(monkeypatch, tmp_path, context_source):
    engine, _, calls = gemma_engine(monkeypatch, tmp_path)
    if context_source == "getter":
        engine.model.config = SimpleNamespace(
            model_type="gemma4", get_text_config=lambda: SimpleNamespace(max_position_embeddings=8),
        )
    with pytest.raises(GenerationProviderError, match="provider_input_too_large"):
        generate(engine, max_output_tokens=7)
    assert not any(isinstance(call, dict) for call in calls)


def test_configured_input_cap_still_applies_with_nested_context(monkeypatch, tmp_path):
    engine, _, calls = gemma_engine(monkeypatch, tmp_path)
    engine.spec = engine.spec.model_copy(update={"max_input_tokens": 1})
    with pytest.raises(GenerationProviderError, match="provider_input_too_large"):
        generate(engine)
    assert not any(isinstance(call, dict) for call in calls)


@pytest.mark.parametrize("parsed", [
    {"role": "assistant", "content": "final", "thinking": "synthetic hidden thought"},
    {"role": "assistant", "thinking": "synthetic hidden thought"},
    {"role": "assistant", "tool_calls": [{"type": "function"}]},
    {"role": "assistant", "content": "final", "tool_calls": [{"type": "function"}]},
    {"role": "user", "content": "final"},
    {"content": "final"},
    {"role": "assistant", "content": ["final"]},
    {"role": "assistant", "content": " "},
    {"role": "assistant", "content": "final", "thinking": []},
    {"role": "assistant", "content": "final", "tool_calls": ""},
    {"role": "assistant", "content": "final", "unknown": "value"},
    {"role": "assistant", "content": '<|channel>thought\nsynthetic hidden thought'},
    [{"role": "assistant", "content": "final"}],
])
def test_unexpected_channels_or_malformed_parsed_output_are_rejected(
    monkeypatch, tmp_path, parsed,
):
    engine, _, _ = gemma_engine(monkeypatch, tmp_path)
    engine.tokenizer.parse_response = lambda *args, **kwargs: parsed
    with pytest.raises(GenerationProviderError, match="provider_invalid_response") as error:
        generate(engine)
    assert "synthetic hidden thought" not in str(error.value)


def test_response_parser_failure_is_sanitized(monkeypatch, tmp_path):
    engine, _, _ = gemma_engine(monkeypatch, tmp_path)

    def broken_parser(*args, **kwargs):
        raise ValueError("synthetic hidden thought")

    engine.tokenizer.parse_response = broken_parser
    with pytest.raises(GenerationProviderError, match="provider_invalid_response") as error:
        generate(engine)
    assert error.value.__cause__ is None
    assert "synthetic hidden thought" not in str(error.value)


def test_missing_response_parser_fails_explicitly(monkeypatch, tmp_path):
    engine, _, _ = gemma_engine(monkeypatch, tmp_path)
    del engine.tokenizer.parse_response
    with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
        generate(engine)
