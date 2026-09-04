from typing import Protocol

from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    GenerationProfile,
    GenerationRequest,
    StructuredGeneration,
)


class GenerationRuntimeUnavailableError(RuntimeError):
    pass


class GenerationRuntimeResponseError(RuntimeError):
    pass


class GenerationRuntimePort(Protocol):
    async def health(self, profile: GenerationProfile) -> bool: ...

    async def contextualize(self, request: ContextualizationRequest) -> str: ...

    async def generate(self, request: GenerationRequest) -> StructuredGeneration: ...


class TokenCounterPort(Protocol):
    def count_tokens(self, text: str) -> int: ...
