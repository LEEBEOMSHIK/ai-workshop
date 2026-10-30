"""Native Anthropic Messages, schema1 only; no model names or credential values in policy.

ADR-0053 pins the wire protocol. The existing schema1 wire schemas already use the
supported JSON subset; their local parsers and citation validation remain authoritative.
The key must be scoped to one workspace; organization/unbound keys are not configured here.
"""

import asyncio
import json
from collections.abc import Mapping
from contextlib import suppress
from time import monotonic
from typing import Any, Self, cast
from urllib.parse import quote, urlsplit

import httpx
from pydantic import SecretStr

from ai_workshop.labs.rag.deployments.domain import (
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    GenerationProfile,
    GenerationRequest,
)
from ai_workshop.labs.rag.generation.evidence_payload import evidence_payload
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    ProviderContextualizationResult,
    ProviderExecutionMetadata,
    ProviderGenerationResult,
    ProviderHealthResult,
    track_local_http_attempt,
)
from ai_workshop.labs.rag.generation.prompts import PromptNotFoundError, load_prompt
from ai_workshop.labs.rag.generation.structured_output import (
    CONTEXTUALIZATION_SCHEMA_V1,
    GROUNDED_GENERATION_SCHEMA_V1,
    StructuredOutputValidationError,
    parse_contextualization_v1,
    parse_grounded_generation_v1,
)
from ai_workshop.labs.rag.models.provider_policy import validate_provider_sampling

ANTHROPIC_API_VERSION = "2026-10-21"


class AnthropicMessagesRuntime:
    def __init__(self, *, deployment: ModelDeploymentVersion, endpoint: str, api_key: str) -> None:
        if (
            deployment.provider is not ProviderKind.ANTHROPIC_MESSAGES
            or deployment.location is not ExecutionLocation.EXTERNAL
            or not api_key.strip()
        ):
            raise ValueError("The Anthropic runtime requires its external Provider and credential.")
        self.deployment = deployment
        self._base_url = _endpoint(endpoint)
        self._api_key = SecretStr(api_key)
        self._test_transport: httpx.MockTransport | None = None

    @classmethod
    def _for_test(
        cls,
        *,
        deployment: ModelDeploymentVersion,
        endpoint: str,
        api_key: str,
        transport: httpx.MockTransport,
    ) -> Self:
        if type(transport) is not httpx.MockTransport:
            raise ValueError("Tests require an exact MockTransport.")
        runtime = cls(deployment=deployment, endpoint=endpoint, api_key=api_key)
        runtime._test_transport = transport
        return runtime

    def validate_profile(self, profile: GenerationProfile) -> None:
        try:
            validate_provider_sampling(
                self.deployment,
                profile.sampling_mode,
                profile.temperature,
                profile.response_schema_version,
            )
            valid = (
                profile.deployment is not None
                and profile.deployment.id == self.deployment.id
                and profile.runtime_model == self.deployment.provider_model_id
                and profile.prompt_ref == "rag-answer-v1"
                and profile.context_prompt_ref == "rag-contextualize-v1"
                and profile.evidence_budget is None
                and profile.numeric_proof_policy is None
                and profile.orchestration is None
                and profile.answer_reasoning_effort is None
            )
        except ValueError:
            valid = False
        if not valid:
            raise GenerationProviderError("generation_schema_not_supported", retryable=False)

    async def health(self) -> ProviderHealthResult:
        started = monotonic()
        payload = await self._request(
            "GET", "models/" + quote(self.deployment.provider_model_id, safe="")
        )
        if payload.get("type") != "model" or type(payload.get("id")) is not str:
            raise GenerationProviderError("provider_invalid_response", retryable=False)
        exact = payload["id"] == self.deployment.provider_model_id
        return ProviderHealthResult(
            exact, self.deployment.provider_model_id if exact else None, self._metadata(started)
        )

    async def contextualize(
        self, request: ContextualizationRequest
    ) -> ProviderContextualizationResult:
        self.validate_profile(request.profile)
        started = monotonic()
        text, usage = await self._message(
            request,
            request.question,
            request.profile.context_prompt_ref,
            CONTEXTUALIZATION_SCHEMA_V1,
        )
        resolved = None
        with suppress(StructuredOutputValidationError, RecursionError):
            resolved = parse_contextualization_v1(text)
        if resolved is None:
            raise GenerationProviderError("structured_output_invalid", retryable=False) from None
        return ProviderContextualizationResult(resolved, self._metadata(started, usage))

    async def generate(self, request: GenerationRequest) -> ProviderGenerationResult:
        self.validate_profile(request.profile)
        started = monotonic()
        content = json.dumps(
            {
                "schema_version": 1,
                "question": request.question,
                "resolved_query": request.resolved_query,
                "evidence": evidence_payload(request.evidence, contextual=False),
            },
            ensure_ascii=False,
        )
        text, usage = await self._message(
            request, content, request.profile.prompt_ref, GROUNDED_GENERATION_SCHEMA_V1
        )
        generation = None
        with suppress(StructuredOutputValidationError, RecursionError):
            generation = parse_grounded_generation_v1(
                text,
                allowed_evidence_ids={item.evidence_id for item in request.evidence},
            )
        if generation is None:
            raise GenerationProviderError("structured_output_invalid", retryable=False) from None
        return ProviderGenerationResult(generation, self._metadata(started, usage))

    async def _message(
        self,
        request: GenerationRequest | ContextualizationRequest,
        content: str,
        prompt_ref: str,
        schema: dict[str, Any],
    ) -> tuple[str, tuple[int, int]]:
        prompt = None
        with suppress(PromptNotFoundError):
            prompt = load_prompt(prompt_ref)
        if prompt is None:
            raise GenerationProviderError("generation_schema_not_supported", retryable=False)
        history = request.history[-request.profile.context_policy.max_history_turns :]
        payload = await self._request(
            "POST",
            "messages",
            {
                "model": self.deployment.provider_model_id,
                "system": prompt,
                "messages": [
                    *({"role": turn.role.value, "content": turn.content} for turn in history),
                    {"role": "user", "content": content},
                ],
                "max_tokens": request.profile.max_output_tokens,
                "output_config": {"format": {"type": "json_schema", "schema": schema}},
            },
            timeout=min(request.profile.timeout_seconds, self.deployment.timeout_seconds),
        )
        normalized = _normalize(payload, self.deployment.provider_model_id)
        if normalized is None:
            raise GenerationProviderError("provider_invalid_response", retryable=False)
        return normalized

    async def _request(
        self,
        method: str,
        resource: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=self._test_transport, trust_env=False, follow_redirects=False
        ) as client:
            for attempt in range(self.deployment.max_retries + 1):
                response, failure = await self._safe_request(
                    client, method, resource, body, timeout=timeout
                )
                if failure is None:
                    assert response is not None
                    failure = _http_failure(response)
                    if failure is None:
                        payload = _json_payload(response)
                        if payload is not None:
                            return payload
                        failure = ("provider_invalid_response", False)
                code, retryable = failure
                if not retryable or attempt == self.deployment.max_retries:
                    raise GenerationProviderError(code, retryable=retryable) from None
                delay = self.deployment.retry_backoff_seconds * (2**attempt)
                if delay:
                    await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _safe_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        resource: str,
        body: dict[str, Any] | None,
        *,
        timeout: float | None,
    ) -> tuple[httpx.Response | None, tuple[str, bool] | None]:
        try:
            operation = client.request(
                method,
                f"{self._base_url}/{resource}",
                json=body,
                headers={
                    "x-api-key": self._api_key.get_secret_value(),
                    "anthropic-version": ANTHROPIC_API_VERSION,
                },
                timeout=timeout if timeout is not None else self.deployment.timeout_seconds,
            )
            # Keep the shared HTTP attempt contract: cancellation cannot prove remote termination.
            response = (
                await track_local_http_attempt(operation) if method == "POST" else await operation
            )
            return response, None
        except httpx.TimeoutException:
            return None, ("provider_timeout", True)
        except httpx.TransportError:
            return None, ("provider_unavailable", True)
        except Exception:
            return None, ("provider_invalid_response", False)

    def _metadata(
        self, started: float, usage: tuple[int, int] | None = None
    ) -> ProviderExecutionMetadata:
        return ProviderExecutionMetadata(
            provider=self.deployment.provider,
            provider_model_id=self.deployment.provider_model_id,
            deployment_version_id=self.deployment.id,
            input_tokens=usage[0] if usage is not None else None,
            output_tokens=usage[1] if usage is not None else None,
            observed_provider_model_id=self.deployment.provider_model_id
            if usage is not None
            else None,
            latency_ms=max(0, int((monotonic() - started) * 1000)),
        )


def _normalize(
    payload: Mapping[str, Any], expected_model: str
) -> tuple[str, tuple[int, int]] | None:
    if (
        payload.get("type") != "message"
        or payload.get("role") != "assistant"
        or payload.get("model") != expected_model
        or payload.get("stop_reason") != "end_turn"
        or payload.get("stop_details") is not None
        or payload.get("stop_sequence") is not None
    ):
        return None
    blocks, usage = payload.get("content"), payload.get("usage")
    if not isinstance(blocks, list) or not isinstance(usage, Mapping):
        return None
    texts: list[str] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            return None
        block_type = block.get("type")
        if type(block_type) is not str:
            return None
        if block_type in {"thinking", "redacted_thinking"}:
            continue  # Never return, log, persist or replay provider reasoning/signatures.
        if (
            block_type != "text"
            or type(block.get("text")) is not str
            or block.get("citations")
        ):
            return None
        texts.append(block["text"])
    if len(texts) != 1:
        return None
    counts = [
        usage.get("input_tokens"),
        usage.get("output_tokens"),
        usage.get("cache_creation_input_tokens", 0),
        usage.get("cache_read_input_tokens", 0),
    ]
    if any(type(value) is not int or value < 0 for value in counts):
        return None
    values = cast(list[int], counts)
    # Official total input = uncached input + cache creation + cache reads; never double count
    # the nested per-TTL cache_creation breakdown. No inferred monetary cost is attached.
    return texts[0], (values[0] + values[2] + values[3], values[1])


def _http_failure(response: httpx.Response) -> tuple[str, bool] | None:
    if response.is_redirect:
        return "provider_invalid_response", False
    if response.status_code in {401, 403}:
        return "provider_authentication_failed", False
    if response.status_code == 429:
        return "provider_rate_limited", True
    if response.status_code >= 500:
        return "provider_unavailable", True
    if response.status_code != 200:
        return "provider_invalid_response", False
    return None


def _json_payload(response: httpx.Response) -> dict[str, Any] | None:
    try:
        value = response.json()
    except (ValueError, TypeError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _endpoint(endpoint: str) -> str:
    valid = False
    try:
        parsed = urlsplit(endpoint)
        valid = bool(
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and parsed.path.rstrip("/") in {"", "/v1"}
            and (parsed.port is None or parsed.port > 0)
        )
    except ValueError:
        pass
    if not valid:
        raise ValueError("The Anthropic endpoint must be a safe HTTPS API origin.") from None
    return (
        endpoint.rstrip("/") if parsed.path.rstrip("/") == "/v1" else endpoint.rstrip("/") + "/v1"
    )
