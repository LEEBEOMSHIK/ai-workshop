from typing import Protocol

from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    GenerationRequest,
)
from ai_workshop.labs.rag.generation.execution import (
    ProviderContextualizationResult,
    ProviderGenerationResult,
    ProviderHealthResult,
)


class GenerationRuntimeUnavailableError(RuntimeError):
    pass


class GenerationRuntimeResponseError(RuntimeError):
    pass


class GenerationRuntimePort(Protocol):
    async def health(self) -> ProviderHealthResult: ...

    async def contextualize(
        self, request: ContextualizationRequest
    ) -> ProviderContextualizationResult: ...

    async def generate(self, request: GenerationRequest) -> ProviderGenerationResult: ...


class TokenCounterPort(Protocol):
    def count_tokens(self, text: str) -> int: ...
