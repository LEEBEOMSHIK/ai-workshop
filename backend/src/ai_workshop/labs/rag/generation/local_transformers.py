"""Local-only Transformers adapter; optional native modules load inside the host worker."""

from __future__ import annotations

import json
from contextlib import suppress
from importlib import import_module
from threading import Event
from time import monotonic
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_workshop.labs.rag.deployments.domain import ModelDeploymentVersion, ProviderKind
from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    GeneratedClaim,
    GenerationProfile,
    GenerationRequest,
    GenerationStatus,
    StructuredGeneration,
)
from ai_workshop.labs.rag.generation.evidence_payload import evidence_payload
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    ProviderContextualizationResult,
    ProviderExecutionMetadata,
    ProviderGenerationResult,
    ProviderHealthResult,
)
from ai_workshop.labs.rag.generation.local_model_host import (
    LocalModelHost,
    LocalModelOutput,
    LocalModelSpec,
)
from ai_workshop.labs.rag.generation.prompts import PromptNotFoundError, load_prompt


class _Claim(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class _Answer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    schema_version: int
    status: Literal["answered", "insufficient_evidence"]
    claims: list[_Claim]


class _Query(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    resolved_query: str


class LocalTransformersRuntime:
    def __init__(
        self, *, deployment: ModelDeploymentVersion, spec: LocalModelSpec, host: LocalModelHost,
    ) -> None:
        if deployment.provider is not ProviderKind.LOCAL_TRANSFORMERS:
            raise ValueError("The local Transformers runtime requires its exact provider.")
        if deployment.provider_model_id != spec.model_id:
            raise ValueError("The local snapshot must match the deployment model identity.")
        self.deployment = deployment
        self.spec = spec
        self.host = host

    async def health(self) -> ProviderHealthResult:
        started = monotonic()
        # Loading validates the configured snapshot and optional native dependencies.
        # This is a configured-snapshot binding, not a cryptographic weights audit.
        await self.host.run(self.spec, lambda *_: None, timeout=self.deployment.timeout_seconds)
        return ProviderHealthResult(True, self.spec.model_id, self._metadata(started))

    async def contextualize(
        self, request: ContextualizationRequest,
    ) -> ProviderContextualizationResult:
        self._validate_profile(request.profile)
        started = monotonic()
        output = await self._complete(
            request.profile, request.profile.context_prompt_ref,
            {"question": request.question, "history": [
                {"role": turn.role.value, "content": turn.content} for turn in request.history
            ]},
            'Return only JSON: {"resolved_query": "standalone question"}.',
        )
        query: str | None = None
        with suppress(TypeError, ValueError):
            query = _Query.model_validate(_json(output)).resolved_query.strip()
        if not query:
            raise GenerationProviderError("provider_invalid_response", retryable=False)
        return ProviderContextualizationResult(query, self._metadata(started, output))

    async def generate(self, request: GenerationRequest) -> ProviderGenerationResult:
        self._validate_profile(request.profile)
        started = monotonic()
        output = await self._complete(
            request.profile, request.profile.prompt_ref,
            {
                "schema_version": 2, "question": request.question,
                "resolved_query": request.resolved_query,
                "history": [{"role": turn.role.value, "content": turn.content}
                            for turn in request.history],
                "evidence": evidence_payload(request.evidence, contextual=True),
            },
            'Return only JSON: {"schema_version":2,"status":"answered",'
            '"claims":[{"text":"supported claim",'
            '"evidence_ids":["exact supplied evidence UUID"]}]}. '
            'When evidence is insufficient use status "insufficient_evidence" and claims []. '
            'An answered result requires claims and citations. No extra keys or Markdown.',
        )
        generation: StructuredGeneration | None = None
        try:
            parsed = _Answer.model_validate(_json(output))
            if (parsed.schema_version == 2
                    and (parsed.status == "answered") == bool(parsed.claims)):
                generation = StructuredGeneration(2, tuple(
                    GeneratedClaim(claim.text, tuple(UUID(value) for value in claim.evidence_ids))
                    for claim in parsed.claims
                ))
        except (TypeError, ValueError):
            pass
        if generation is None:
            raise GenerationProviderError("provider_invalid_response", retryable=False)
        metadata = self._metadata(started, output)
        if not generation.claims:
            return ProviderGenerationResult(
                None, metadata, status=GenerationStatus.INSUFFICIENT_EVIDENCE,
            )
        return ProviderGenerationResult(generation, metadata)

    async def _complete(
        self, profile: GenerationProfile, prompt_ref: str,
        payload: dict[str, object], wire_instruction: str,
    ) -> LocalModelOutput:
        prompt: str | None = None
        with suppress(PromptNotFoundError):
            prompt = load_prompt(prompt_ref)
        if prompt is None:
            raise GenerationProviderError("provider_invalid_response", retryable=False)
        system_prompt = prompt + "\n" + wire_instruction
        user_content = json.dumps(payload, ensure_ascii=False)
        return await self.host.run(
            self.spec,
            lambda engine, stop, deadline: engine.generate(
                system_prompt=system_prompt, user_content=user_content,
                max_output_tokens=profile.max_output_tokens, temperature=profile.temperature,
                stop=stop, deadline=deadline,
            ),
            timeout=min(profile.timeout_seconds, self.deployment.timeout_seconds),
        )

    def _validate_profile(self, profile: GenerationProfile) -> None:
        if profile.response_schema_version != 2:
            raise GenerationProviderError("generation_schema_not_supported", retryable=False)
        if (profile.deployment is None or profile.deployment.id != self.deployment.id
                or profile.runtime_model != self.spec.model_id):
            raise GenerationProviderError("deployment_not_ready", retryable=False)

    def _metadata(
        self, started: float, output: LocalModelOutput | None = None,
    ) -> ProviderExecutionMetadata:
        return ProviderExecutionMetadata(
            provider=self.deployment.provider, provider_model_id=self.spec.model_id,
            deployment_version_id=self.deployment.id,
            input_tokens=output.input_tokens if output else None,
            output_tokens=output.output_tokens if output else None,
            latency_ms=max(0, int((monotonic() - started) * 1000)),
            observed_provider_model_id=self.spec.model_id,
        )


def _json(output: LocalModelOutput) -> object:
    if output.truncated:
        raise ValueError("Truncated structured output.")
    return json.loads(
        output.text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate structured response key.")
        result[key] = value
    return result


def _invalid_constant(value: str) -> object:
    raise ValueError("Non-JSON numeric constant.")


class TransformersEngine:
    def __init__(self, spec: LocalModelSpec) -> None:
        path = spec.snapshot_path
        # HF's immutable snapshot layout binds both repo and commit selection.
        # Blob symlinks inside a snapshot are expected and supported by HF.
        if (path.name != spec.revision or path.parent.name != "snapshots"
                or path.parent.parent.name != "models--" + spec.model_id.replace("/", "--")
                or not path.is_dir()):
            raise GenerationProviderError("deployment_not_ready", retryable=False)
        self.spec = spec
        self.torch = import_module("torch")
        self.transformers = import_module("transformers")
        self.tokenizer = self.transformers.AutoTokenizer.from_pretrained(
            str(path), local_files_only=True, trust_remote_code=False, use_fast=True,
        )
        self.model = self.transformers.AutoModelForCausalLM.from_pretrained(
            str(path), local_files_only=True, trust_remote_code=False,
            use_safetensors=True, dtype=getattr(self.torch, spec.dtype),
        ).to(spec.device)
        self.model.eval()

    def generate(
        self, *, system_prompt: str, user_content: str, max_output_tokens: int,
        temperature: float, stop: Event, deadline: float,
    ) -> LocalModelOutput:
        _check_stop(stop, deadline)
        gemma4 = getattr(self.model.config, "model_type", None) == "gemma4"
        if gemma4:
            prompt = self.tokenizer.apply_chat_template(
                [{"role": "system", "content": system_prompt},
                 {"role": "user", "content": user_content}],
                tokenize=False, add_generation_prompt=True, enable_thinking=False,
            )
        else:
            # Preserve the original single-user template for models such as Gemma 3.
            prompt = self.tokenizer.apply_chat_template(
                [{"role": "user", "content": system_prompt + "\n\nInput JSON:\n" + user_content}],
                tokenize=False, add_generation_prompt=True,
            )
        inputs = self.tokenizer(
            prompt, return_tensors="pt", add_special_tokens=False, truncation=False,
        )
        input_tokens = int(inputs["input_ids"].shape[-1])
        config = self.model.config
        get_text_config = getattr(config, "get_text_config", None)
        text_config = (get_text_config() if callable(get_text_config)
                       else getattr(config, "text_config", config))
        context_limit = getattr(text_config, "max_position_embeddings", None)
        if (input_tokens > self.spec.max_input_tokens or (
            isinstance(context_limit, int) and input_tokens + max_output_tokens > context_limit
        )):
            raise GenerationProviderError("provider_input_too_large", retryable=False)
        _check_stop(stop, deadline)
        options: dict[str, Any] = {
            "max_new_tokens": max_output_tokens, "do_sample": temperature > 0,
            "stopping_criteria": self.transformers.StoppingCriteriaList([_Stop(stop, deadline)]),
        }
        if temperature > 0:
            options["temperature"] = temperature
        with self.torch.inference_mode():
            tokens = self.model.generate(**inputs, **options)[0][input_tokens:]
        _check_stop(stop, deadline)
        output_tokens = len(tokens)
        eos = self.model.generation_config.eos_token_id
        eos_ids = eos if isinstance(eos, list) else [eos]
        truncated = output_tokens >= max_output_tokens and (
            not output_tokens or int(tokens[-1]) not in eos_ids
        )
        if gemma4:
            text = self._gemma4_final_text(tokens, prompt)
        else:
            text = str(self.tokenizer.decode(
                tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False,
            ))
        return LocalModelOutput(text, input_tokens, output_tokens, truncated)

    def _gemma4_final_text(self, tokens: Any, prompt: str) -> str:
        parsed: object = None
        # Preserve channel delimiters for the snapshot's tokenizer response template.
        # Never propagate parser exceptions, which can include private generated text.
        with suppress(Exception):
            response = self.tokenizer.decode(
                tokens, skip_special_tokens=False, clean_up_tokenization_spaces=False,
            )
            parsed = self.tokenizer.parse_response(response, prefix=prompt)
        if (not isinstance(parsed, dict)
                or set(parsed) - {"role", "content", "thinking", "tool_calls"}
                or parsed.get("role") != "assistant"
                or parsed.get("thinking", "") != ""
                or parsed.get("tool_calls", []) != []):
            raise GenerationProviderError("provider_invalid_response", retryable=False)
        content = parsed.get("content")
        if (not isinstance(content, str) or not content.strip()
                or any(token in content for token in self.tokenizer.all_special_tokens)):
            raise GenerationProviderError("provider_invalid_response", retryable=False)
        return content


class _Stop:
    def __init__(self, stop: Event, deadline: float) -> None:
        self.stop = stop
        self.deadline = deadline

    def __call__(self, input_ids: Any, scores: Any, **kwargs: Any) -> bool:
        return self.stop.is_set() or monotonic() >= self.deadline


def _check_stop(stop: Event, deadline: float) -> None:
    if stop.is_set() or monotonic() >= deadline:
        raise GenerationProviderError("provider_timeout", retryable=True)
