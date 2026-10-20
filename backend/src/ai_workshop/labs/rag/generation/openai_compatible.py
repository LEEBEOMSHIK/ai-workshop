from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import ip_address
from time import monotonic
from typing import Any, Literal, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_workshop.labs.rag.deployments.domain import (
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.generation.compact_evidence import pack_compact_evidence
from ai_workshop.labs.rag.generation.contracts import (
    GenerationRuntimeResponseError,
    GenerationRuntimeUnavailableError,
)
from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    GeneratedClaim,
    GenerationProfile,
    GenerationRequest,
    GenerationStatus,
    StructuredGeneration,
)
from ai_workshop.labs.rag.generation.evidence_payload import evidence_payload, is_context_abstention
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    ProviderContextualizationResult,
    ProviderExecutionMetadata,
    ProviderGenerationResult,
    ProviderHealthResult,
    track_local_http_attempt,
)
from ai_workshop.labs.rag.generation.http_evidence import GROUP_NOTICE, group_http_evidence
from ai_workshop.labs.rag.generation.input_inspection import (
    record_generation_input,
    record_generation_response,
)
from ai_workshop.labs.rag.generation.prompts import PromptNotFoundError, load_prompt
from ai_workshop.labs.rag.generation.source_reading import build_source_reading
from ai_workshop.shared.request_context import correlation_id_context


class _Rejection(StrEnum):
    HTTP_REDIRECT = "http.redirect"
    HTTP_ERROR = "http.error"
    TRANSPORT = "transport.unexpected"
    RESPONSE_JSON = "response_json.invalid"
    RESPONSE_OBJECT = "response_json.not_object"
    CHOICES = "envelope.choices"
    CHOICE = "envelope.choice"
    CHOICE_COUNT = "envelope.choice_count"
    FINISH_LENGTH = "finish.length"
    FINISH_OTHER = "finish.not_stop"
    MESSAGE = "envelope.message"
    MESSAGE_FIELDS = "message.unsupported_fields"
    REASONING_TYPE = "message.reasoning_type"
    ROLE = "message.role"
    OUTPUT = "message.unsupported_output"
    CONTENT = "message.content_type"
    PROMPT = "prompt.unavailable"
    HEALTH = "health.models_shape"
    CONTEXT_JSON = "context_json.invalid"
    CONTEXT_SCHEMA = "context_schema.invalid"
    CONTEXT_EMPTY = "context_query.empty"
    ANSWER_JSON = "answer_json.invalid"
    ANSWER_SCHEMA = "answer_schema.invalid"
    ANSWER_SCHEMA_MISSING = "answer_schema.missing"
    ANSWER_SCHEMA_TYPE = "answer_schema.type"
    ANSWER_SCHEMA_EXTRA = "answer_schema.extra_fields"
    ANSWER_SCHEMA_LITERAL = "answer_schema.literal"
    ANSWER_SCHEMA_CONSTRAINT = "answer_schema.constraint"
    ANSWER_SCHEMA_MIXED = "answer_schema.mixed"
    ANSWER_CONTRACT = "answer_contract.invalid"
    EVIDENCE_ID = "evidence_id.invalid"
    CLAIM = "claim.invalid"


class _SchemaPath(StrEnum):
    ROOT = "root"
    VERSION = "schema_version"
    STATUS = "status"
    CLAIMS = "claims"
    CLAIM = "claims.item"
    TEXT = "claims.item.text"
    IDS = "claims.item.evidence_ids"
    ID = "claims.item.evidence_ids.item"
    ROOT_EXTRA = "root.extra"
    CLAIM_EXTRA = "claims.item.extra"
    UNKNOWN = "unknown"


class _SchemaReason(StrEnum):
    INVALID = "invalid"
    MISSING = "missing"
    TYPE = "type"
    EXTRA = "extra_fields"
    LITERAL = "literal"
    CONSTRAINT = "constraint"


class _ContractViolation(StrEnum):
    VERSION = "schema_version"
    ANSWERED_EMPTY = "answered_without_claims"
    INSUFFICIENT_NONEMPTY = "insufficient_with_claims"


def _record_rejection(
    category: _Rejection, *,
    schema_errors: frozenset[tuple[_SchemaReason, _SchemaPath]] = frozenset(),
    contract_errors: frozenset[_ContractViolation] = frozenset(),
) -> None:
    # Never include provider text, field values, validation errors or tracebacks.
    try:
        correlation_id = str(UUID(correlation_id_context.get()))
    except (ValueError, TypeError, AttributeError):
        correlation_id = "unavailable"
    stage, reason = category.value.split(".", 1)
    if contract_errors:
        # Closed codes retain simultaneous violations without values or claim text.
        logging.getLogger(__name__).warning(
            "provider_response_rejected stage=%s reason=%s correlation_id=%s violations=%s",
            stage, reason, correlation_id,
            ",".join(sorted(item.value for item in contract_errors)),
        )
        return
    if schema_errors:
        # Closed enums bound the full deduplicated set to 6 * 11 = 66 pairs.
        # Keep every category; do not truncate based on untrusted error order/count.
        categories = ",".join(sorted({kind.value for kind, _ in schema_errors}))
        fields = ",".join(sorted(f"{kind.value}:{path.value}" for kind, path in schema_errors))
        logging.getLogger(__name__).warning(
            "provider_response_rejected stage=%s reason=%s correlation_id=%s "
            "categories=%s fields=%s", stage, reason, correlation_id, categories, fields,
        )
        return
    logging.getLogger(__name__).warning(
        "provider_response_rejected stage=%s reason=%s correlation_id=%s",
        stage, reason, correlation_id,
    )


def _invalid_response(category: _Rejection) -> GenerationProviderError:
    _record_rejection(category)
    return GenerationProviderError("provider_invalid_response", retryable=False)


def _response_usage(payload: Mapping[str, Any]) -> tuple[int | None, ...]:
    # PostgreSQL audit columns are signed Integer. Never coerce untrusted values.
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        usage = {}
    details = usage.get("completion_tokens_details")
    if not isinstance(details, Mapping):
        details = {}
    values = (usage.get("prompt_tokens"), usage.get("completion_tokens"),
              usage.get("total_tokens"), details.get("reasoning_tokens"))
    return tuple(value if type(value) is int and 0 <= value <= 2**31 - 1 else None
                 for value in values)


def _record_response_diagnostics(payload: Mapping[str, Any], *, contextualize: bool) -> None:
    choices = payload.get("choices")
    finish = None
    if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], Mapping):
        finish = choices[0].get("finish_reason")
    reason = (finish if type(finish) is str and finish in
              {"stop", "length", "content_filter", "tool_calls", "function_call"}
              else "missing" if finish is None else "other")
    try:
        correlation_id = str(UUID(correlation_id_context.get()))
    except (ValueError, TypeError, AttributeError):
        correlation_id = "unavailable"
    # Use the existing diagnostic level without changing server logging configuration.
    logging.getLogger(__name__ + ".response_diagnostics").warning(
        "provider_response_diagnostics operation=%s finish_reason=%s correlation_id=%s "
        "input_tokens=%s output_tokens=%s total_tokens=%s reasoning_tokens=%s",
        "contextualize" if contextualize else "generate", reason, correlation_id,
        *_response_usage(payload),
    )


def _schema_path(location: tuple[str | int, ...], *, extra: bool) -> _SchemaPath:
    # Match entire known shapes; never stringify/copy a provider-controlled loc.
    claim_item = (
        len(location) >= 2 and location[0] == "claims"
        and type(location[1]) is int and location[1] >= 0
    )
    if extra:
        if len(location) == 1:
            return _SchemaPath.ROOT_EXTRA
        if claim_item and len(location) == 3:
            return _SchemaPath.CLAIM_EXTRA
        return _SchemaPath.UNKNOWN
    roots: dict[tuple[str | int, ...], _SchemaPath] = {
        (): _SchemaPath.ROOT,
        ("schema_version",): _SchemaPath.VERSION,
        ("status",): _SchemaPath.STATUS,
        ("claims",): _SchemaPath.CLAIMS,
    }
    if location in roots:
        return roots[location]
    if claim_item:
        suffix = location[2:]
        if not suffix:
            return _SchemaPath.CLAIM
        if suffix == ("text",):
            return _SchemaPath.TEXT
        if suffix == ("evidence_ids",):
            return _SchemaPath.IDS
        if (len(suffix) == 2 and suffix[0] == "evidence_ids"
                and type(suffix[1]) is int and suffix[1] >= 0):
            return _SchemaPath.ID
    return _SchemaPath.UNKNOWN


def _record_answer_schema_rejection(error: ValidationError) -> None:
    categories = {
        "missing": _SchemaReason.MISSING,
        "int_type": _SchemaReason.TYPE,
        "string_type": _SchemaReason.TYPE,
        "list_type": _SchemaReason.TYPE,
        "model_type": _SchemaReason.TYPE,
        "extra_forbidden": _SchemaReason.EXTRA,
        "literal_error": _SchemaReason.LITERAL,
        "too_short": _SchemaReason.CONSTRAINT,
    }
    errors = frozenset(
        (categories.get(item["type"], _SchemaReason.INVALID),
         _schema_path(item["loc"], extra=item["type"] == "extra_forbidden"))
        for item in error.errors(include_input=False, include_context=False, include_url=False)
    ) or frozenset({(_SchemaReason.INVALID, _SchemaPath.UNKNOWN)})
    reasons = {kind for kind, _ in errors}
    category = (
        _Rejection.ANSWER_SCHEMA_MIXED if len(reasons) > 1
        else _Rejection(f"answer_schema.{next(iter(reasons)).value}")
    )
    _record_rejection(category, schema_errors=errors)


class _ClaimV2(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    text: str
    evidence_ids: list[str] = Field(min_length=1)


_ANSWER_VERSION = 2


@dataclass(frozen=True)
class _StatusClaimRule:
    status: Literal["answered", "insufficient_evidence"]
    min_items: int
    max_items: int | None
    violation: _ContractViolation


_ANSWER_RULES = (
    _StatusClaimRule("answered", 1, None, _ContractViolation.ANSWERED_EMPTY),
    _StatusClaimRule("insufficient_evidence", 0, 0, _ContractViolation.INSUFFICIENT_NONEMPTY),
)


def _answer_contract_schema(schema: dict[str, Any]) -> None:
    # Keep Pydantic field shapes/$refs and add the post-validation business rules.
    # Full object alternatives avoid properties + anyOf at the same level and
    # if/then/else, unsupported by upstream llama.cpp's schema-to-grammar converter.
    branches = []
    for rule in _ANSWER_RULES:
        branch = deepcopy(schema)
        properties = branch["properties"]
        properties["schema_version"]["const"] = _ANSWER_VERSION
        properties["status"].pop("enum", None)
        properties["status"]["const"] = rule.status
        properties["claims"]["minItems"] = rule.min_items
        if rule.max_items is not None:
            properties["claims"]["maxItems"] = rule.max_items
        branches.append(branch)
    schema.clear()
    schema["anyOf"] = branches


def _answer_contract_prompt() -> str:
    requirements = [f"schema_version must be exactly {_ANSWER_VERSION} (integer)."]
    for rule in _ANSWER_RULES:
        bound = (f"exactly {rule.min_items} items" if rule.min_items == rule.max_items
                 else f"at least {rule.min_items} item")
        requirements.append(f'status "{rule.status}": claims must contain {bound}.')
    return "\n" + " ".join(requirements)


class _AnswerV2(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", json_schema_extra=_answer_contract_schema,
    )
    schema_version: int
    status: Literal["answered", "insufficient_evidence"]
    claims: list[_ClaimV2]

    def contract_violations(self) -> frozenset[_ContractViolation]:
        errors = set()
        if self.schema_version != _ANSWER_VERSION:
            errors.add(_ContractViolation.VERSION)
        for rule in _ANSWER_RULES:
            if self.status == rule.status and (
                len(self.claims) < rule.min_items
                or (rule.max_items is not None and len(self.claims) > rule.max_items)
            ):
                errors.add(rule.violation)
        return frozenset(errors)


class _QueryV2(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    resolved_query: str


class LocalOpenAICompatibleRuntime:
    def __init__(
        self,
        *,
        deployment: ModelDeploymentVersion,
        endpoint: str,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        dialect: Literal["openai", "ollama"] = "openai",
    ) -> None:
        if deployment.provider is not ProviderKind.LOCAL_OPENAI_COMPATIBLE:
            raise ValueError("The local runtime requires its exact Provider kind.")
        if dialect not in {"openai", "ollama"}:
            raise ValueError("Unsupported local HTTP dialect.")
        self.dialect = dialect
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
            raise _invalid_response(_Rejection.HEALTH)
        exact = any(
            isinstance(item, Mapping) and item.get("id") == self.deployment.provider_model_id
            for item in data
        )
        return ProviderHealthResult(
            ready=exact,
            observed_provider_model_id=(self.deployment.provider_model_id if exact else None),
            execution=self._metadata(started),
        )

    async def contextualize(
        self, request: ContextualizationRequest
    ) -> ProviderContextualizationResult:
        self._validate_profile(request.profile)
        started = monotonic()
        system_prompt = _safe_load_prompt(request.profile.context_prompt_ref)
        if system_prompt is None:
            raise _invalid_response(_Rejection.PROMPT) from None
        payload = await self._chat_completion(
            profile=request.profile,
            system_prompt=system_prompt,
            contextualize=True,
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
        try:
            schema2 = request.profile.response_schema_version == 2
            content = self._message_content(payload, strict=schema2)
            resolved_query = _safe_resolved_query(content, strict=schema2)
            if resolved_query is None:
                raise GenerationProviderError(
                    "provider_invalid_response", retryable=False,
                ) from None
            return ProviderContextualizationResult(
                resolved_query=resolved_query,
                execution=self._metadata(started, payload),
            )

        except GenerationProviderError as error:
            error.execution = self._metadata(started, payload)
            raise

    async def generate(self, request: GenerationRequest) -> ProviderGenerationResult:
        self._validate_profile(request.profile)
        started = monotonic()
        system_prompt = _safe_load_prompt(request.profile.prompt_ref)
        if system_prompt is None:
            raise _invalid_response(_Rejection.PROMPT) from None
        if request.profile.response_schema_version == 2:
            system_prompt += (
                '\nReturn only JSON: {"schema_version":2,"status":"answered",'
                '"claims":[{"text":"supported claim",'
                '"evidence_ids":["exact supplied evidence UUID"]}]}. '
                'When evidence is insufficient use status "insufficient_evidence" and claims []. '
                'An answered result requires claims and citations. No extra keys or Markdown.'
            )
        payload = await self._chat_completion(
            profile=request.profile,
            system_prompt=system_prompt,
            user_content=_generation_user_content(request),
        )
        try:
            schema2 = request.profile.response_schema_version == 2
            content = self._message_content(payload, strict=schema2)
            if (request.profile.response_schema_version == 1
                    and request.profile.evidence_budget is not None
                    and is_context_abstention(content)):
                return ProviderGenerationResult(
                    None,
                    self._metadata(started, payload),
                    status=GenerationStatus.INSUFFICIENT_EVIDENCE,
                )
            generation = _safe_generation(
                content,
                expected_schema_version=request.profile.response_schema_version,
            )
            if generation is None:
                raise GenerationProviderError(
                    "provider_invalid_response", retryable=False,
                ) from None
            if not schema2 and not generation.claims:
                raise _invalid_response(_Rejection.ANSWER_CONTRACT) from None
            if not generation.claims:
                return ProviderGenerationResult(
                    None, self._metadata(started, payload),
                    status=GenerationStatus.INSUFFICIENT_EVIDENCE,
                )
            return ProviderGenerationResult(
                generation=generation,
                execution=self._metadata(started, payload),
            )

        except GenerationProviderError as error:
            error.execution = self._metadata(started, payload)
            raise

    async def _chat_completion(
        self,
        *,
        profile: GenerationProfile,
        system_prompt: str,
        user_content: str,
        contextualize: bool = False,
    ) -> dict[str, Any]:
        ollama_schema2 = self.dialect == "ollama" and profile.response_schema_version == 2
        if ollama_schema2 and contextualize:
            system_prompt += (
                '\nReturn only {"resolved_query":"one short standalone search query"}. '
                'Preserve the subject and constraints; do not answer the question or explain.'
            )
        if ollama_schema2 and not contextualize:
            system_prompt += _answer_contract_prompt()
        body: dict[str, Any] = {
            "model": self.deployment.provider_model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": profile.temperature,
            "max_tokens": profile.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        if ollama_schema2:
            contract = _QueryV2 if contextualize else _AnswerV2
            body["response_format"] = {
                "type": "json_schema", "json_schema": {"schema": contract.model_json_schema()},
            }
        if ollama_schema2 and (contextualize or profile.answer_reasoning_effort == "none"):
            # Ollama v0.40.3 maps this compatibility value to think=false.
            # Keep the configured output budget; length remains a hard failure.
            body["reasoning_effort"] = "none"
        if not contextualize:
            record_generation_input(
                body, provider=self.deployment.provider.value, dialect=self.dialect,
                prompt_ref=profile.prompt_ref, profile_version=profile.profile_version,
                evidence_budget=profile.evidence_budget,
                model_name=profile.model_name, model_version=profile.model_version,
            )
        payload = await self._request_json(
            method="POST", path="/v1/chat/completions", json_body=body,
            strict_json=ollama_schema2,
        )
        if not contextualize:
            record_generation_response()
        _record_response_diagnostics(payload, contextualize=contextualize)
        return payload

    async def _request_json(
        self,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        strict_json: bool = False,
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
                    error = _invalid_response(_Rejection.HTTP_REDIRECT)
                elif response.status_code in {401, 403}:
                    error = GenerationProviderError(
                        "provider_authentication_failed", retryable=False
                    )
                elif response.status_code == 429:
                    error = GenerationProviderError("provider_rate_limited", retryable=True)
                elif response.is_error:
                    error = _invalid_response(_Rejection.HTTP_ERROR)
                else:
                    payload = _safe_response_json(response, strict=strict_json)
                    if payload is not None:
                        return payload
                    error = GenerationProviderError("provider_invalid_response", retryable=False)
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
            operation = self._request(
                method=method, path=path, headers=headers, json_body=json_body,
            )
            return (
                await track_local_http_attempt(operation) if method == "POST" else await operation,
                None,
            )
        except httpx.TimeoutException:
            return None, ("provider_timeout", True)
        except httpx.HTTPError:
            return None, ("deployment_not_ready", False)
        except Exception:
            _record_rejection(_Rejection.TRANSPORT)
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

    def _metadata(
        self, started: float, payload: Mapping[str, Any] | None = None,
    ) -> ProviderExecutionMetadata:
        input_tokens, output_tokens, *_ = _response_usage(payload or {})
        return ProviderExecutionMetadata(
            provider=self.deployment.provider,
            provider_model_id=self.deployment.provider_model_id,
            deployment_version_id=self.deployment.id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=max(0, int((monotonic() - started) * 1000)),
        )

    def _validate_profile(self, profile: GenerationProfile) -> None:
        if profile.answer_reasoning_effort is not None and self.dialect != "ollama":
            raise GenerationProviderError("generation_schema_not_supported", retryable=False)
        if profile.response_schema_version == 3:
            raise GenerationProviderError("generation_schema_not_supported", retryable=False)
        if (
            profile.deployment is None
            or profile.deployment.id != self.deployment.id
            or profile.runtime_model != self.deployment.provider_model_id
        ):
            raise GenerationProviderError("deployment_not_ready", retryable=False)

    def _message_content(self, payload: Mapping[str, Any], *, strict: bool = False) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise _invalid_response(_Rejection.CHOICES) from None
        first = choices[0]
        if not isinstance(first, Mapping):
            raise _invalid_response(_Rejection.CHOICE) from None
        if strict and len(choices) != 1:
            raise _invalid_response(_Rejection.CHOICE_COUNT) from None
        if strict and first.get("finish_reason") != "stop":
            category = (_Rejection.FINISH_LENGTH if first.get("finish_reason") == "length"
                        else _Rejection.FINISH_OTHER)
            raise _invalid_response(category) from None
        message = first.get("message")
        if not isinstance(message, Mapping):
            raise _invalid_response(_Rejection.MESSAGE) from None
        if strict and self.dialect == "ollama":
            # Only this documented string metadata is discarded. It is never
            # parsed as answer content, returned, or retained in execution records.
            if set(message) - {"role", "content", "reasoning", "tool_calls"}:
                raise _invalid_response(_Rejection.MESSAGE_FIELDS) from None
            if "reasoning" in message and not isinstance(message["reasoning"], str):
                raise _invalid_response(_Rejection.REASONING_TYPE) from None
            message = {key: value for key, value in message.items() if key != "reasoning"}
        if strict and message.get("role") != "assistant":
            raise _invalid_response(_Rejection.ROLE) from None
        if strict and any(
            message.get(field) not in (None, "", [])
            for field in ("thinking", "reasoning", "reasoning_content", "tool_calls",
                          "function_call", "refusal")
        ):
            raise _invalid_response(_Rejection.OUTPUT) from None
        content = message.get("content")
        if not isinstance(content, str):
            raise _invalid_response(_Rejection.CONTENT) from None
        return content


def _safe_load_prompt(reference: str) -> str | None:
    try:
        return load_prompt(reference)
    except PromptNotFoundError:
        return None


def _safe_response_json(
    response: httpx.Response, *, strict: bool = False,
) -> dict[str, Any] | None:
    try:
        payload = _strict_json(response.text) if strict else response.json()
    except (TypeError, ValueError):
        _record_rejection(_Rejection.RESPONSE_JSON)
        return None
    if not isinstance(payload, dict):
        _record_rejection(_Rejection.RESPONSE_OBJECT)
        return None
    return cast(dict[str, Any], payload)


def _safe_resolved_query(content: str, *, strict: bool = False) -> str | None:
    failure = _Rejection.CONTEXT_JSON
    try:
        parsed: Any = _strict_json(content) if strict else json.loads(content)
        failure = _Rejection.CONTEXT_SCHEMA
        if strict:
            resolved_query = _QueryV2.model_validate(parsed).resolved_query
        else:
            resolved_query = parsed["resolved_query"]
        if not isinstance(resolved_query, str) or not resolved_query.strip():
            _record_rejection(_Rejection.CONTEXT_EMPTY)
            return None
        return resolved_query
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        _record_rejection(failure)
        return None


def _safe_generation(
    content: str,
    *,
    expected_schema_version: int,
) -> StructuredGeneration | None:
    failure = _Rejection.ANSWER_JSON
    try:
        parsed: Any = _strict_json(content) if expected_schema_version == 2 else json.loads(content)
        failure = _Rejection.ANSWER_SCHEMA
        if expected_schema_version == 2:
            answer = _AnswerV2.model_validate(parsed)
            violations = answer.contract_violations()
            if violations:
                _record_rejection(_Rejection.ANSWER_CONTRACT, contract_errors=violations)
                return None
            schema_version = 2
            raw_claims = [claim.model_dump() for claim in answer.claims]
        else:
            schema_version = parsed["schema_version"]
            raw_claims = parsed["claims"]
            if not isinstance(schema_version, int) or not isinstance(raw_claims, list):
                _record_rejection(_Rejection.ANSWER_SCHEMA)
                return None
        claims: list[GeneratedClaim] = []
        for raw_claim in raw_claims:
            failure = _Rejection.ANSWER_SCHEMA
            claim_text, raw_ids = raw_claim["text"], raw_claim["evidence_ids"]
            failure = _Rejection.EVIDENCE_ID
            evidence_ids = tuple(UUID(value) for value in raw_ids)
            failure = _Rejection.CLAIM
            claims.append(GeneratedClaim(text=claim_text, evidence_ids=evidence_ids))
        failure = _Rejection.ANSWER_CONTRACT
        generation = StructuredGeneration(schema_version=schema_version, claims=tuple(claims))
        if generation.schema_version != expected_schema_version:
            _record_rejection(_Rejection.ANSWER_CONTRACT)
            return None
        return generation
    except ValidationError as error:
        _record_answer_schema_rejection(error)
        return None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        _record_rejection(failure)
        return None


def _strict_json(content: str) -> object:
    return json.loads(content, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate structured response key.")
        result[key] = value
    return result


def _invalid_constant(value: str) -> object:
    raise ValueError("Non-JSON numeric constant.")


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
        raise ValueError("The generation runtime endpoint must be a loopback URL.") from None
    if not address.is_loopback:
        raise ValueError("The generation runtime endpoint must be a loopback URL.")


__all__ = [
    "GenerationRuntimeResponseError",
    "GenerationRuntimeUnavailableError",
    "LocalOpenAICompatibleRuntime",
]


def _generation_user_content(request: GenerationRequest) -> str:
    """Compact contextual HTTP input without changing shared or server evidence."""
    contextual = request.profile.evidence_budget is not None
    payload: dict[str, object] = {
        "schema_version": request.profile.response_schema_version,
        "question": request.question,
        "resolved_query": request.resolved_query,
        "history": [
            {"role": turn.role.value, "content": turn.content} for turn in request.history
        ],
    }
    if request.profile.prompt_ref == "rag-answer-v5":
        if not contextual:
            raise ValueError("Compact source reading requires an explicit evidence budget.")
        payload.update(pack_compact_evidence(request.evidence))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    evidence = evidence_payload(request.evidence, contextual=contextual)
    payload["evidence"] = evidence
    if contextual and evidence:
        payload["context_notice"] = evidence[0]["context_notice"]
        for item in evidence:
            # group_id retains these exact source identities in their original order.
            for key in ("document_id", "asset_version_id", "projection_id", "chunk_id",
                        "context_notice"):
                item.pop(key)
        payload["evidence"], payload["evidence_groups"] = group_http_evidence(evidence)
        payload["evidence_format_notice"] = GROUP_NOTICE
    if request.profile.prompt_ref == "rag-answer-v4":
        if not contextual:
            raise ValueError("Source reading requires an explicit evidence budget.")
        payload["source_reading"] = build_source_reading(request.evidence)
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":") if contextual else None,
    )
