from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlparse
from uuid import UUID

import httpx

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
from ai_workshop.labs.rag.generation.prompts import PromptNotFoundError, load_prompt


class LocalOpenAICompatibleRuntime:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("The generation runtime endpoint must be a loopback URL.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("The generation runtime endpoint must not contain credentials.")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client

    async def health(self, profile: GenerationProfile) -> bool:
        try:
            payload = await self._request_json(
                method="GET",
                path="/v1/models",
                timeout=profile.timeout_seconds,
            )
            data = payload.get("data")
            if not isinstance(data, list):
                return False
            return any(
                isinstance(item, Mapping) and item.get("id") == profile.runtime_model
                for item in data
            )
        except (GenerationRuntimeUnavailableError, GenerationRuntimeResponseError):
            return False

    async def contextualize(self, request: ContextualizationRequest) -> str:
        try:
            system_prompt = load_prompt(request.profile.context_prompt_ref)
        except PromptNotFoundError as exc:
            raise GenerationRuntimeResponseError(
                "The generation runtime returned an invalid response."
            ) from exc
        user_content = json.dumps(
            {
                "history": [
                    {"role": turn.role.value, "content": turn.content}
                    for turn in request.history
                ],
                "question": request.question,
            },
            ensure_ascii=False,
        )
        payload = await self._chat_completion(
            profile=request.profile,
            system_prompt=system_prompt,
            user_content=user_content,
        )
        content = self._message_content(payload)
        try:
            parsed = json.loads(content)
            resolved_query = parsed["resolved_query"]
            if not isinstance(resolved_query, str) or not resolved_query.strip():
                raise ValueError
            return resolved_query.strip()
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GenerationRuntimeResponseError(
                "The generation runtime returned an invalid response."
            ) from exc

    async def generate(self, request: GenerationRequest) -> StructuredGeneration:
        try:
            system_prompt = load_prompt(request.profile.prompt_ref)
        except PromptNotFoundError as exc:
            raise GenerationRuntimeResponseError(
                "The generation runtime returned an invalid response."
            ) from exc
        user_content = json.dumps(
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
        )
        payload = await self._chat_completion(
            profile=request.profile,
            system_prompt=system_prompt,
            user_content=user_content,
        )
        content = self._message_content(payload)
        try:
            parsed = json.loads(content)
            schema_version = parsed["schema_version"]
            raw_claims = parsed["claims"]
            if not isinstance(schema_version, int) or not isinstance(raw_claims, list):
                raise ValueError
            claims = tuple(
                GeneratedClaim(
                    text=raw_claim["text"],
                    evidence_ids=tuple(UUID(value) for value in raw_claim["evidence_ids"]),
                )
                for raw_claim in raw_claims
            )
            result = StructuredGeneration(schema_version=schema_version, claims=claims)
            if result.schema_version != request.profile.response_schema_version:
                raise ValueError
            return result
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise GenerationRuntimeResponseError(
                "The generation runtime returned an invalid response."
            ) from exc

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
            timeout=profile.timeout_seconds,
            json_body={
                "model": profile.runtime_model,
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
        timeout: float,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            if self.client is not None:
                response = await self.client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    json=json_body,
                    timeout=timeout,
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=headers,
                        json=json_body,
                        timeout=timeout,
                    )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GenerationRuntimeUnavailableError(
                "The generation runtime is unavailable."
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise GenerationRuntimeResponseError(
                "The generation runtime returned an invalid response."
            ) from exc
        if not isinstance(payload, dict):
            raise GenerationRuntimeResponseError(
                "The generation runtime returned an invalid response."
            )
        return cast(dict[str, Any], payload)

    @staticmethod
    def _message_content(payload: Mapping[str, Any]) -> str:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GenerationRuntimeResponseError(
                "The generation runtime returned an invalid response."
            ) from exc
        if not isinstance(content, str):
            raise GenerationRuntimeResponseError(
                "The generation runtime returned an invalid response."
            )
        return content
