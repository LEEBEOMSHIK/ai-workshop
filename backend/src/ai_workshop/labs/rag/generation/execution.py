from __future__ import annotations

import re
from collections.abc import Awaitable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from ai_workshop.labs.rag.deployments.domain import (
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.generation.domain import GenerationStatus, StructuredGeneration

if TYPE_CHECKING:
    from ai_workshop.labs.rag.generation.contracts import GenerationRuntimePort


PROVIDER_TERMINATION_UNCONFIRMED = "provider_termination_unconfirmed"


@dataclass
class GenerationTermination:
    """Per-conversation HTTP attempts; completing a retry cannot settle an earlier attempt."""

    pending: set[object] = field(default_factory=set)

    @property
    def confirmed(self) -> bool:
        return not self.pending


_termination: ContextVar[GenerationTermination | None] = ContextVar(
    "generation_termination", default=None,
)


async def tracked_generation_call[T](
    operation: Awaitable[T], termination: GenerationTermination,
) -> T:
    token = _termination.set(termination)
    try:
        return await operation
    finally:
        _termination.reset(token)


async def track_local_http_attempt[T](operation: Awaitable[T]) -> T:
    """A cancelled/failed transport is not evidence of remote inference termination.

    A full non-streaming HTTP response settles only its own attempt. No process-exit
    or unload claim is made, and ambiguous earlier attempts remain pending.
    """
    termination = _termination.get()
    attempt = object()
    if termination is not None:
        termination.pending.add(attempt)
    result = await operation
    if termination is not None:
        termination.pending.discard(attempt)
    return result


class GenerationProviderError(RuntimeError):
    execution: ProviderExecutionMetadata | None = None

    def __init__(
        self, code: str, *, retryable: bool,
        execution: ProviderExecutionMetadata | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        if execution is not None:
            self.execution = execution


@dataclass(frozen=True, slots=True)
class ProviderExecutionMetadata:
    provider: ProviderKind
    provider_model_id: str
    deployment_version_id: UUID
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    observed_provider_model_id: str | None = None

    def __post_init__(self) -> None:
        if self.observed_provider_model_id is not None and (
            type(self.observed_provider_model_id) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", self.observed_provider_model_id)
            is None
        ):
            raise ValueError("Invalid observed Provider model ID.")
        if not isinstance(self.provider, ProviderKind):
            raise ValueError("Execution metadata requires a named Provider.")
        if not self.provider_model_id.strip():
            raise ValueError("Execution metadata requires a Provider model ID.")
        if self.latency_ms < 0:
            raise ValueError("Execution latency cannot be negative.")
        if self.input_tokens is not None and self.input_tokens < 0:
            raise ValueError("Execution input tokens cannot be negative.")
        if self.output_tokens is not None and self.output_tokens < 0:
            raise ValueError("Execution output tokens cannot be negative.")


@dataclass(frozen=True, slots=True)
class ProviderContextualizationResult:
    resolved_query: str
    execution: ProviderExecutionMetadata

    def __post_init__(self) -> None:
        clean_query = self.resolved_query.strip()
        if not clean_query:
            raise ValueError("Contextualization requires a resolved query.")
        object.__setattr__(self, "resolved_query", clean_query)


@dataclass(frozen=True, slots=True)
class ProviderGenerationResult:
    generation: StructuredGeneration | None
    execution: ProviderExecutionMetadata
    status: GenerationStatus = GenerationStatus.ANSWERED

    def __post_init__(self) -> None:
        if self.status is GenerationStatus.ANSWERED:
            if not isinstance(self.generation, StructuredGeneration) or not self.generation.claims:
                raise ValueError("Invalid provider generation result.")
        elif self.status is GenerationStatus.INSUFFICIENT_EVIDENCE:
            if self.generation is not None:
                raise ValueError("Invalid provider generation result.")
        else:
            raise ValueError("Invalid provider generation result.")


@dataclass(frozen=True, slots=True)
class ProviderHealthResult:
    ready: bool
    observed_provider_model_id: str | None
    execution: ProviderExecutionMetadata


@dataclass(frozen=True, slots=True)
class ResolvedGenerationRuntime:
    deployment: ModelDeploymentVersion
    adapter: GenerationRuntimePort
