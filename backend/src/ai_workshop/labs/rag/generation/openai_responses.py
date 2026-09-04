from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from time import monotonic
from typing import Any, Self, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import SecretStr

from ai_workshop.labs.rag.deployments.domain import (
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    ConversationTurn,
    GenerationProfile,
    GenerationRequest,
    StructuredGeneration,
)
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    ProviderContextualizationResult,
    ProviderExecutionMetadata,
    ProviderGenerationResult,
    ProviderHealthResult,
)
from ai_workshop.labs.rag.generation.prompts import PromptNotFoundError, load_prompt
from ai_workshop.labs.rag.generation.structured_output import (
    CONTEXTUALIZATION_SCHEMA_V1,
    GROUNDED_GENERATION_SCHEMA_V1,
    StructuredOutputValidationError,
    parse_contextualization_v1,
    parse_grounded_generation_v1,
)

_MAX_REQUEST_HISTORY_TURNS = 20


class OpenAIResponsesRuntime:
    def __init__(
        self,
        *,
        deployment: ModelDeploymentVersion,
        endpoint: str,
        api_key: str,
    ) -> None:
        if deployment.provider is not ProviderKind.OPENAI_RESPONSES:
            raise ValueError("The OpenAI Responses runtime requires its exact Provider kind.")
        if deployment.location is not ExecutionLocation.EXTERNAL:
            raise ValueError("The OpenAI Responses runtime requires external execution.")
        if not api_key:
            raise ValueError("The OpenAI Responses runtime requires a resolved secret.")
        self._base_url = _validate_endpoint(endpoint)
        self.deployment = deployment
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
            raise ValueError("The test transport must be an exact MockTransport.")
        runtime = cls(
            deployment=deployment,
            endpoint=endpoint,
            api_key=api_key,
        )
        runtime._test_transport = transport
        return runtime

    async def health(self) -> ProviderHealthResult:
        started = monotonic()
        payload = await self._request_json(method="GET", resource="models")
        data = payload.get("data")
        if not isinstance(data, list):
            raise GenerationProviderError("provider_invalid_response", retryable=False)
        exact = any(
            isinstance(item, Mapping)
            and item.get("id") == self.deployment.provider_model_id
            for item in data
        )
        return ProviderHealthResult(
            ready=exact,
            observed_provider_model_id=(
                self.deployment.provider_model_id if exact else None
            ),
            execution=self._metadata(started),
        )

    async def contextualize(
        self,
        request: ContextualizationRequest,
    ) -> ProviderContextualizationResult:
        self._validate_profile(request.profile)
        started = monotonic()
        instructions = _safe_load_prompt(request.profile.context_prompt_ref)
        if instructions is None:
            raise GenerationProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        response = await self._create_response(
            profile=request.profile,
            instructions=instructions,
            input_items=_input_items(
                request.history,
                request.profile,
                current_content=request.question,
            ),
            schema_name="rag_contextualization_v1",
            schema=CONTEXTUALIZATION_SCHEMA_V1,
        )
        output_text, usage = _safe_normalize_response(
            response,
            expected_model=self.deployment.provider_model_id,
        )
        if output_text is None or usage is None:
            raise GenerationProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        resolved_query = _safe_contextualization(output_text)
        if resolved_query is None:
            raise GenerationProviderError(
                "structured_output_invalid", retryable=False
            ) from None
        return ProviderContextualizationResult(
            resolved_query=resolved_query,
            execution=self._metadata(
                started,
                input_tokens=usage[0],
                output_tokens=usage[1],
            ),
        )

    async def generate(self, request: GenerationRequest) -> ProviderGenerationResult:
        self._validate_profile(request.profile)
        started = monotonic()
        instructions = _safe_load_prompt(request.profile.prompt_ref)
        if instructions is None:
            raise GenerationProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        current_content = json.dumps(
            {
                "schema_version": request.profile.response_schema_version,
                "question": request.question,
                "resolved_query": request.resolved_query,
                "evidence": [
                    {"evidence_id": str(item.evidence_id), "text": item.text}
                    for item in request.evidence
                ],
            },
            ensure_ascii=False,
        )
        response = await self._create_response(
            profile=request.profile,
            instructions=instructions,
            input_items=_input_items(
                request.history,
                request.profile,
                current_content=current_content,
            ),
            schema_name="rag_grounded_generation_v1",
            schema=GROUNDED_GENERATION_SCHEMA_V1,
        )
        output_text, usage = _safe_normalize_response(
            response,
            expected_model=self.deployment.provider_model_id,
        )
        if output_text is None or usage is None:
            raise GenerationProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        generation = _safe_generation(
            output_text,
            allowed_evidence_ids={item.evidence_id for item in request.evidence},
        )
        if generation is None:
            raise GenerationProviderError(
                "structured_output_invalid", retryable=False
            ) from None
        return ProviderGenerationResult(
            generation=generation,
            execution=self._metadata(
                started,
                input_tokens=usage[0],
                output_tokens=usage[1],
            ),
        )

    async def _create_response(
        self,
        *,
        profile: GenerationProfile,
        instructions: str,
        input_items: list[dict[str, object]],
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._request_json(
            method="POST",
            resource="responses",
            json_body={
                "model": self.deployment.provider_model_id,
                "instructions": instructions,
                "input": input_items,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    }
                },
                "store": False,
                "max_output_tokens": profile.max_output_tokens,
                "temperature": profile.temperature,
            },
        )

    async def _request_json(
        self,
        *,
        method: str,
        resource: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempts = self.deployment.max_retries + 1
        async with httpx.AsyncClient(
            transport=self._test_transport,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            for attempt in range(attempts):
                response, transport_failure = await self._safe_request(
                    client=client,
                    method=method,
                    resource=resource,
                    json_body=json_body,
                )
                if transport_failure is not None:
                    error = GenerationProviderError(
                        transport_failure[0], retryable=transport_failure[1]
                    )
                else:
                    assert response is not None
                    if response.is_redirect:
                        error = GenerationProviderError(
                            "provider_invalid_response", retryable=False
                        )
                    elif response.status_code in {401, 403}:
                        error = GenerationProviderError(
                            "provider_authentication_failed", retryable=False
                        )
                    elif response.status_code == 429:
                        error = GenerationProviderError(
                            "provider_rate_limited", retryable=True
                        )
                    elif response.is_error:
                        error = GenerationProviderError(
                            "provider_invalid_response", retryable=False
                        )
                    else:
                        payload = _safe_response_json(response)
                        if payload is not None:
                            return payload
                        error = GenerationProviderError(
                            "provider_invalid_response", retryable=False
                        )
                if not error.retryable or attempt + 1 >= attempts:
                    raise error from None
                delay = self.deployment.retry_backoff_seconds * (2**attempt)
                if delay:
                    await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _safe_request(
        self,
        *,
        client: httpx.AsyncClient,
        method: str,
        resource: str,
        json_body: dict[str, Any] | None,
    ) -> tuple[httpx.Response | None, tuple[str, bool] | None]:
        try:
            return (
                await self._request(
                    client=client,
                    method=method,
                    resource=resource,
                    json_body=json_body,
                ),
                None,
            )
        except httpx.TimeoutException:
            return None, ("provider_timeout", True)
        except Exception:
            return None, ("provider_invalid_response", False)

    async def _request(
        self,
        *,
        client: httpx.AsyncClient,
        method: str,
        resource: str,
        json_body: dict[str, Any] | None,
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
        }
        url = f"{self._base_url}/{resource}"
        return await client.request(
            method,
            url,
            headers=headers,
            json=json_body,
            timeout=self.deployment.timeout_seconds,
        )

    def _metadata(
        self,
        started: float,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> ProviderExecutionMetadata:
        return ProviderExecutionMetadata(
            provider=self.deployment.provider,
            provider_model_id=self.deployment.provider_model_id,
            deployment_version_id=self.deployment.id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=max(0, int((monotonic() - started) * 1000)),
        )

    def _validate_profile(self, profile: GenerationProfile) -> None:
        if (
            profile.deployment is None
            or profile.deployment.id != self.deployment.id
            or profile.runtime_model != self.deployment.provider_model_id
            or profile.response_schema_version != 1
        ):
            raise GenerationProviderError("deployment_not_ready", retryable=False)


def _input_items(
    history: tuple[ConversationTurn, ...],
    profile: GenerationProfile,
    *,
    current_content: str,
) -> list[dict[str, object]]:
    bound = min(_MAX_REQUEST_HISTORY_TURNS, profile.context_policy.max_history_turns)
    selected_history = history[-bound:]
    input_items: list[dict[str, object]] = [
        {"role": turn.role.value, "content": turn.content}
        for turn in selected_history
    ]
    input_items.append({"role": "user", "content": current_content})
    return input_items


def _safe_load_prompt(reference: str) -> str | None:
    try:
        return load_prompt(reference)
    except PromptNotFoundError:
        return None


def _safe_response_json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return cast(dict[str, Any], payload)


def _safe_normalize_response(
    payload: Mapping[str, Any],
    *,
    expected_model: str,
) -> tuple[str | None, tuple[int, int] | None]:
    if (
        payload.get("object") != "response"
        or "error" not in payload
        or "incomplete_details" not in payload
        or payload.get("status") != "completed"
        or payload.get("error") is not None
        or payload.get("incomplete_details") is not None
        or payload.get("model") != expected_model
    ):
        return None, None
    output_text = _single_output_text(payload)
    usage = _exact_usage(payload.get("usage"))
    if output_text is None or usage is None:
        return None, None
    return output_text, usage


def _single_output_text(payload: Mapping[str, Any]) -> str | None:
    candidates: list[str] = []
    if "output_text" in payload:
        top_level = payload["output_text"]
        if not isinstance(top_level, str):
            return None
        candidates.append(top_level)
    output = payload.get("output")
    if not isinstance(output, list):
        return None
    for item in output:
        if not isinstance(item, Mapping):
            return None
        content = item.get("content")
        if content is None:
            continue
        if (
            item.get("type") != "message"
            or item.get("role") != "assistant"
            or item.get("status") != "completed"
            or not isinstance(content, list)
        ):
            return None
        for part in content:
            if not isinstance(part, Mapping):
                return None
            if part.get("type") == "refusal":
                return None
            if part.get("type") == "output_text":
                text = part.get("text")
                if not isinstance(text, str):
                    return None
                candidates.append(text)
    if len(candidates) != 1:
        return None
    return candidates[0]


def _exact_usage(value: object) -> tuple[int, int] | None:
    if not isinstance(value, Mapping):
        return None
    input_tokens = value.get("input_tokens")
    output_tokens = value.get("output_tokens")
    if (
        type(input_tokens) is not int
        or input_tokens < 0
        or type(output_tokens) is not int
        or output_tokens < 0
    ):
        return None
    return input_tokens, output_tokens


def _safe_contextualization(content: str) -> str | None:
    try:
        return parse_contextualization_v1(content)
    except StructuredOutputValidationError:
        return None


def _safe_generation(
    content: str,
    *,
    allowed_evidence_ids: set[UUID],
) -> StructuredGeneration | None:
    try:
        return parse_grounded_generation_v1(
            content,
            allowed_evidence_ids=allowed_evidence_ids,
        )
    except StructuredOutputValidationError:
        return None


def _validate_endpoint(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname
        _ = parsed.port
    except ValueError:
        raise ValueError("The OpenAI Responses endpoint is invalid.") from None
    if parsed.scheme not in {"http", "https"} or host is None:
        raise ValueError("The OpenAI Responses endpoint must use HTTP(S).")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("The OpenAI Responses endpoint is unsafe.")
    base = endpoint.rstrip("/")
    if not parsed.path.rstrip("/").endswith("/v1"):
        base = f"{base}/v1"
    return base


__all__ = ["OpenAIResponsesRuntime"]
