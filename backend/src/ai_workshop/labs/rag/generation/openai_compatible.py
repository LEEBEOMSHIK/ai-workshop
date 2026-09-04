from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from ipaddress import ip_address
from time import monotonic
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from ai_workshop.labs.rag.deployments.domain import (
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.generation.contracts import (
    GenerationRuntimeResponseError,
    GenerationRuntimeUnavailableError,
)
from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    GeneratedClaim,
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


class LocalOpenAICompatibleRuntime:
    def __init__(
        self,
        *,
        deployment: ModelDeploymentVersion,
        endpoint: str,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if deployment.provider is not ProviderKind.LOCAL_OPENAI_COMPATIBLE:
            raise ValueError("The local runtime requires its exact Provider kind.")
        _validate_endpoint(endpoint, deployment.location)
        if client is not None:
            if getattr(client, "_trust_env", True) is not False:
                raise ValueError("Injected clients must not trust proxy environment settings.")
            if client.follow_redirects:
                raise ValueError("Injected clients must not follow redirects.")
        self.deployment = deployment
        self.base_url = endpoint.rstrip("/")
        self.api_key = api_key
        self.client = client

    async def health(self) -> ProviderHealthResult:
        started = monotonic()
        payload = await self._request_json(method="GET", path="/v1/models")
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
        self, request: ContextualizationRequest
    ) -> ProviderContextualizationResult:
        self._validate_profile(request.profile)
        started = monotonic()
        system_prompt = _safe_load_prompt(request.profile.context_prompt_ref)
        if system_prompt is None:
            raise GenerationProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        payload = await self._chat_completion(
            profile=request.profile,
            system_prompt=system_prompt,
            user_content=json.dumps(
                {
                    "history": [
                        {"role": turn.role.value, "content": turn.content}
                        for turn in request.history
                    ],
                    "question": request.question,
                },
                ensure_ascii=False,
            ),
        )
        content = self._message_content(payload)
        resolved_query = _safe_resolved_query(content)
        if resolved_query is None:
            raise GenerationProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        return ProviderContextualizationResult(
            resolved_query=resolved_query,
            execution=self._metadata(started),
        )

    async def generate(self, request: GenerationRequest) -> ProviderGenerationResult:
        self._validate_profile(request.profile)
        started = monotonic()
        system_prompt = _safe_load_prompt(request.profile.prompt_ref)
        if system_prompt is None:
            raise GenerationProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        payload = await self._chat_completion(
            profile=request.profile,
            system_prompt=system_prompt,
            user_content=json.dumps(
                {
                    "schema_version": request.profile.response_schema_version,
                    "question": request.question,
                    "resolved_query": request.resolved_query,
                    "history": [
                        {"role": turn.role.value, "content": turn.content}
                        for turn in request.history
                    ],
                    "evidence": [
                        {"evidence_id": str(item.evidence_id), "text": item.text}
                        for item in request.evidence
                    ],
                },
                ensure_ascii=False,
            ),
        )
        content = self._message_content(payload)
        generation = _safe_generation(
            content,
            expected_schema_version=request.profile.response_schema_version,
        )
        if generation is None:
            raise GenerationProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        return ProviderGenerationResult(
            generation=generation,
            execution=self._metadata(started),
        )

    async def _chat_completion(
        self,
        *,
        profile: GenerationProfile,
        system_prompt: str,
        user_content: str,
    ) -> dict[str, Any]:
        return await self._request_json(
            method="POST",
            path="/v1/chat/completions",
            json_body={
                "model": self.deployment.provider_model_id,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": profile.temperature,
                "max_tokens": profile.max_output_tokens,
                "response_format": {"type": "json_object"},
            },
        )

    async def _request_json(
        self,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        attempts = self.deployment.max_retries + 1
        for attempt in range(attempts):
            response, transport_failure = await self._safe_request(
                method=method,
                path=path,
                headers=headers,
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
            if self.deployment.retry_backoff_seconds:
                await asyncio.sleep(self.deployment.retry_backoff_seconds)
        raise AssertionError("unreachable")

    async def _safe_request(
        self,
        *,
        method: str,
        path: str,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
    ) -> tuple[httpx.Response | None, tuple[str, bool] | None]:
        try:
            return (
                await self._request(
                    method=method,
                    path=path,
                    headers=headers,
                    json_body=json_body,
                ),
                None,
            )
        except httpx.TimeoutException:
            return None, ("provider_timeout", True)
        except httpx.HTTPError:
            return None, ("deployment_not_ready", False)
        except Exception:
            return None, ("provider_invalid_response", False)

    async def _request(
        self,
        *,
        method: str,
        path: str,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        if self.client is not None:
            return await self.client.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=self.deployment.timeout_seconds,
            )
        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
        ) as client:
            return await client.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=self.deployment.timeout_seconds,
            )

    def _metadata(self, started: float) -> ProviderExecutionMetadata:
        return ProviderExecutionMetadata(
            provider=self.deployment.provider,
            provider_model_id=self.deployment.provider_model_id,
            deployment_version_id=self.deployment.id,
            input_tokens=None,
            output_tokens=None,
            latency_ms=max(0, int((monotonic() - started) * 1000)),
        )

    def _validate_profile(self, profile: GenerationProfile) -> None:
        if (
            profile.deployment is None
            or profile.deployment.id != self.deployment.id
            or profile.runtime_model != self.deployment.provider_model_id
        ):
            raise GenerationProviderError("deployment_not_ready", retryable=False)

    @staticmethod
    def _message_content(payload: Mapping[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise GenerationProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        first = choices[0]
        if not isinstance(first, Mapping):
            raise GenerationProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        message = first.get("message")
        if not isinstance(message, Mapping):
            raise GenerationProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        content = message.get("content")
        if not isinstance(content, str):
            raise GenerationProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        return content


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


def _safe_resolved_query(content: str) -> str | None:
    try:
        parsed = json.loads(content)
        resolved_query = parsed["resolved_query"]
        if not isinstance(resolved_query, str) or not resolved_query.strip():
            return None
        return resolved_query
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _safe_generation(
    content: str,
    *,
    expected_schema_version: int,
) -> StructuredGeneration | None:
    try:
        parsed = json.loads(content)
        schema_version = parsed["schema_version"]
        raw_claims = parsed["claims"]
        if not isinstance(schema_version, int) or not isinstance(raw_claims, list):
            return None
        claims = tuple(
            GeneratedClaim(
                text=raw_claim["text"],
                evidence_ids=tuple(UUID(value) for value in raw_claim["evidence_ids"]),
            )
            for raw_claim in raw_claims
        )
        generation = StructuredGeneration(schema_version=schema_version, claims=claims)
        if generation.schema_version != expected_schema_version:
            return None
        return generation
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _validate_endpoint(endpoint: str, location: ExecutionLocation) -> None:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("The generation runtime endpoint must use HTTP(S).")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
    ):
        raise ValueError("The generation runtime endpoint is unsafe.")
    if location is ExecutionLocation.EXTERNAL:
        raise ValueError("The local Provider cannot use an external endpoint.")
    if location is ExecutionLocation.ON_PREMISE:
        return
    host = parsed.hostname
    if host.lower() == "localhost":
        return
    if "%" in host:
        raise ValueError("The generation runtime endpoint must be a loopback URL.")
    try:
        address = ip_address(host)
    except ValueError:
        address = None
    if address is None:
        raise ValueError(
            "The generation runtime endpoint must be a loopback URL."
        ) from None
    if not address.is_loopback:
        raise ValueError("The generation runtime endpoint must be a loopback URL.")


__all__ = [
    "GenerationRuntimeResponseError",
    "GenerationRuntimeUnavailableError",
    "LocalOpenAICompatibleRuntime",
]
