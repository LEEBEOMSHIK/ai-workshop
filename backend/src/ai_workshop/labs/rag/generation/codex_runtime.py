"""Immutable request-scoped GenerationRuntimePort adapter, with passive readiness.

Requested model identity is metadata, never fabricated observed identity. The
Codex-only observed-None exception does not relax readiness or authorization.
"""

import json
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field, replace
from functools import wraps
from math import isfinite
from time import monotonic
from typing import Any, NoReturn, Protocol

from ai_workshop.labs.rag.deployments.domain import ProviderKind

from .codex_authorization import CodexAuthorizationErrorCode
from .codex_events import CodexEventResult, CodexTokenUsage
from .codex_execution import CodexRequestExecutor, _codex_deployment
from .codex_request import CodexRequestContext
from .codex_stream import CodexStreamResult
from .codex_wire import parse_codex_grounded_wire_v1
from .codex_workspace import CodexWorkspaceResult
from .domain import ContextualizationRequest, GenerationProfile, GenerationRequest
from .execution import (
    GenerationProviderError,
    ProviderContextualizationResult,
    ProviderExecutionMetadata,
    ProviderGenerationResult,
    ProviderHealthResult,
)
from .structured_output import StructuredOutputValidationError, parse_contextualization_v1
from .windows_process import ProcessFailure

_SAFE_CODES = frozenset(
    {
        "deployment_not_ready",
        "provider_invalid_response",
        "provider_model_mismatch",
        "structured_output_invalid",
        "provider_timeout",
        "provider_request_failed",
        "codex_workspace_cleanup_failed",
        "codex_workspace_failed",
        "codex_request_invalid",
        "codex_binding_mismatch",
        "codex_capacity_exhausted",
        "codex_execution_failed",
        "codex_audit_required",
        "codex_verification_unavailable",
        "codex_slot_invalid_input",
        "codex_slot_settings_mismatch",
        "codex_slot_lease_mismatch",
        "codex_slot_source_unavailable",
    }
    | {"codex_authorization_" + code.value for code in CodexAuthorizationErrorCode}
)


class CodexPassiveReadiness(Protocol):
    async def health(
        self,
        *,
        context: CodexRequestContext,
        profile: GenerationProfile,
    ) -> ProviderHealthResult: ...


def _safe_errors[**P, T](
    operation: Callable[P, Awaitable[T]],
) -> Callable[P, Coroutine[Any, Any, T]]:
    @wraps(operation)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        code = "provider_invalid_response"
        try:
            return await operation(*args, **kwargs)
        except GenerationProviderError as error:
            if type(error.code) is str and error.code in _SAFE_CODES:
                code = error.code
        except StructuredOutputValidationError:
            code = "structured_output_invalid"
        except Exception:
            pass
        raise GenerationProviderError(code, retryable=False)

    return wrapped


@dataclass(frozen=True, slots=True)
class CodexExecRuntime:
    context: CodexRequestContext
    profile: GenerationProfile
    executor: CodexRequestExecutor = field(repr=False)
    readiness: CodexPassiveReadiness | None = field(default=None, repr=False)
    monotonic_clock: Callable[[], float] = field(default=monotonic, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.context) is not CodexRequestContext
            or type(self.profile) is not GenerationProfile
        ):
            raise GenerationProviderError("codex_request_invalid", retryable=False)
        object.__setattr__(self, "context", replace(self.context))
        _codex_deployment(self.profile)

    @_safe_errors
    async def health(self) -> ProviderHealthResult:
        started = self.monotonic_clock()
        if self.readiness is None:
            return ProviderHealthResult(False, None, self._metadata(started))
        health = await self.readiness.health(context=self.context, profile=self.profile)
        deployment = _codex_deployment(self.profile)
        if (
            type(health) is not ProviderHealthResult
            or type(health.ready) is not bool
            or type(health.execution) is not ProviderExecutionMetadata
            or health.execution.provider is not ProviderKind.DEVELOPMENT_CODEX_EXEC
            or health.execution.deployment_version_id != deployment.id
            or health.execution.provider_model_id != deployment.provider_model_id
        ):
            raise GenerationProviderError("provider_invalid_response", retryable=False)
        self._observed_identity(health.observed_provider_model_id)
        return ProviderHealthResult(
            health.ready, health.observed_provider_model_id, self._metadata(started)
        )

    @_safe_errors
    async def contextualize(
        self,
        request: ContextualizationRequest,
    ) -> ProviderContextualizationResult:
        started = self.monotonic_clock()
        if type(request) is not ContextualizationRequest:
            raise GenerationProviderError("codex_request_invalid", retryable=False)
        self._validate_profile(request.profile)
        if (await self.health()).ready is not True:
            raise GenerationProviderError("deployment_not_ready", retryable=False)
        events = self._validated_events(await self.executor.execute(self.context, request=request))
        try:
            # Existing contextual parser is retained; reject JSON duplicate keys/constants first.
            json.loads(
                events.final_text, object_pairs_hook=_unique_keys, parse_constant=_invalid_json
            )
        except (TypeError, ValueError, RecursionError):
            raise StructuredOutputValidationError("Invalid contextualization output.") from None
        query = parse_contextualization_v1(events.final_text)
        return ProviderContextualizationResult(
            query, self._metadata(started, events.usage, events.observed_model)
        )

    @_safe_errors
    async def generate(self, request: GenerationRequest) -> ProviderGenerationResult:
        started = self.monotonic_clock()
        if type(request) is not GenerationRequest:
            raise GenerationProviderError("codex_request_invalid", retryable=False)
        self._validate_profile(request.profile)
        if (await self.health()).ready is not True:
            raise GenerationProviderError("deployment_not_ready", retryable=False)
        events = self._validated_events(await self.executor.execute(self.context, request=request))
        result = parse_codex_grounded_wire_v1(
            events.final_text,
            allowed_evidence_ids={item.evidence_id for item in request.evidence},
        )
        return ProviderGenerationResult(
            result.generation,
            self._metadata(started, events.usage, events.observed_model),
            status=result.status,
        )

    def _validate_profile(self, profile: GenerationProfile) -> None:
        if type(profile) is not GenerationProfile or profile != self.profile:
            raise GenerationProviderError("codex_binding_mismatch", retryable=False)

    def _observed_identity(self, observed: object) -> None:
        if observed is not None and (
            type(observed) is not str or observed != self.profile.runtime_model
        ):
            raise GenerationProviderError("provider_model_mismatch", retryable=False)

    def _validated_events(self, result: CodexWorkspaceResult) -> CodexEventResult:
        if (
            type(result) is not CodexWorkspaceResult
            or result.cleanup_verified is not True
            or result.process_termination_verified is not True
        ):
            raise GenerationProviderError("codex_workspace_cleanup_failed", retryable=False)
        if result.failure is not None:
            raise GenerationProviderError("codex_workspace_failed", retryable=False)
        stream = result.stream
        if (
            type(stream) is not CodexStreamResult
            or stream.cleanup_verified is not True
            or type(stream.active_processes_after_cleanup) is not int
            or stream.active_processes_after_cleanup != 0
        ):
            raise GenerationProviderError("codex_workspace_cleanup_failed", retryable=False)
        if stream.process_failure is not None:
            code = (
                "provider_timeout"
                if stream.process_failure is ProcessFailure.TIMEOUT
                else "provider_request_failed"
            )
            raise GenerationProviderError(code, retryable=False)
        if stream.event_failure is not None:
            raise GenerationProviderError("structured_output_invalid", retryable=False)
        events = stream.events
        if type(events) is not CodexEventResult or type(events.final_text) is not str:
            raise GenerationProviderError("provider_invalid_response", retryable=False)
        self._observed_identity(events.observed_model)
        usage = events.usage
        if (
            type(usage) is not CodexTokenUsage
            or any(
                type(value) is not int or value < 0
                for value in (
                    usage.input_tokens,
                    usage.cached_input_tokens,
                    usage.output_tokens,
                )
            )
            or any(
                value is not None and (type(value) is not int or value < 0)
                for value in (
                    usage.reasoning_output_tokens,
                    usage.cache_write_input_tokens,
                )
            )
            or usage.cached_input_tokens > usage.input_tokens
            or (
                usage.reasoning_output_tokens is not None
                and usage.reasoning_output_tokens > usage.output_tokens
            )
            or usage.output_tokens > self.profile.max_output_tokens
        ):
            raise GenerationProviderError("provider_invalid_response", retryable=False)
        return events

    def _metadata(
        self,
        started: float,
        usage: CodexTokenUsage | None = None,
        observed_model: str | None = None,
    ) -> ProviderExecutionMetadata:
        elapsed = self.monotonic_clock() - started
        if not isfinite(elapsed) or elapsed < 0:
            raise GenerationProviderError("provider_invalid_response", retryable=False)
        deployment = _codex_deployment(self.profile)
        return ProviderExecutionMetadata(
            provider=ProviderKind.DEVELOPMENT_CODEX_EXEC,
            provider_model_id=deployment.provider_model_id,
            deployment_version_id=deployment.id,
            input_tokens=usage.input_tokens if usage is not None else None,
            output_tokens=usage.output_tokens if usage is not None else None,
            latency_ms=int(elapsed * 1000),
            observed_provider_model_id=observed_model,
        )


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _invalid_json(_value: str) -> NoReturn:
    raise ValueError("nonstandard constant")
