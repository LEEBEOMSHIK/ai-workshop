from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from ai_workshop.labs.rag.deployments.domain import (
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.generation.domain import StructuredGeneration

if TYPE_CHECKING:
    from ai_workshop.labs.rag.generation.contracts import GenerationRuntimePort


class GenerationProviderError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ProviderExecutionMetadata:
    provider: ProviderKind
    provider_model_id: str
    deployment_version_id: UUID
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int

    def __post_init__(self) -> None:
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
    generation: StructuredGeneration
    execution: ProviderExecutionMetadata


@dataclass(frozen=True, slots=True)
class ProviderHealthResult:
    ready: bool
    observed_provider_model_id: str | None
    execution: ProviderExecutionMetadata


@dataclass(frozen=True, slots=True)
class ResolvedGenerationRuntime:
    deployment: ModelDeploymentVersion
    adapter: GenerationRuntimePort
