from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from ai_workshop.labs.rag.generation.integrity import ConversationScopeBinding
from ai_workshop.labs.rag.search.configuration_port import ResolvedSearchConfiguration
from ai_workshop.labs.rag.search.pipeline import (
    PipelineInput,
    RagExecutionPipeline,
)
from ai_workshop.labs.rag.search.pipeline import (
    RelatedSource as RelatedSource,
)
from ai_workshop.labs.rag.search.pipeline import (
    SearchResult as SearchResult,
)
from ai_workshop.labs.rag.search.pipeline import (
    SearchSourceResolverPort as SearchSourceResolverPort,
)
from ai_workshop.labs.rag.search.pipeline import (
    SelectedSearchScope as SelectedSearchScope,
)
from ai_workshop.shared.errors import AppError

if TYPE_CHECKING:
    from ai_workshop.labs.rag.search.schemas import SearchRequest


class SearchApplicationService(RagExecutionPipeline):
    async def search(self, *, actor_id: UUID, request: SearchRequest) -> SearchResult:
        configuration = await self.configuration_resolver.resolve(
            request.configuration_id,
            actor_id,
        )
        return await self.execute(
            PipelineInput(
                actor_id=actor_id,
                request=request,
                configuration=configuration,
                conversation_scope=None,
            )
        )

    async def search_exact(
        self,
        *,
        actor_id: UUID,
        configuration_version_id: UUID,
        request: SearchRequest,
    ) -> SearchResult:
        configuration = await self.configuration_resolver.resolve_version(
            configuration_version_id,
            actor_id,
        )
        if request.configuration_id != configuration.configuration_id:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return await self.execute(
            PipelineInput(
                actor_id=actor_id,
                request=request,
                configuration=configuration,
                conversation_scope=None,
            )
        )

    async def search_resolved(
        self,
        *,
        actor_id: UUID,
        request: SearchRequest,
        configuration: ResolvedSearchConfiguration,
        conversation_scope: ConversationScopeBinding,
    ) -> SearchResult:
        """Search an exact configuration after a domain boundary authorized it."""
        if request.configuration_id != configuration.configuration_id:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return await self.execute(
            PipelineInput(
                actor_id=actor_id,
                request=request,
                configuration=configuration,
                conversation_scope=conversation_scope,
            )
        )
