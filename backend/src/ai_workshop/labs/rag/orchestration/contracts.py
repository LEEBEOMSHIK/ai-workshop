from collections.abc import Awaitable, Callable
from typing import Protocol

from ai_workshop.labs.rag.generation.domain import GenerationRequest
from ai_workshop.labs.rag.generation.execution import ProviderGenerationResult
from ai_workshop.labs.rag.policies.domain import PolicyDecision


class GenerationOrchestratorPort(Protocol):
    async def generate(
        self, request: GenerationRequest, *, policy: PolicyDecision,
        revalidate: Callable[[], Awaitable[None]] | None = None,
        prior_model_calls: int = 0, prior_reserved_output_tokens: int = 0,
        prior_latency_ms: float = 0,
    ) -> ProviderGenerationResult: ...
