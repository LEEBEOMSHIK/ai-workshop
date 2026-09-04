from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from ai_workshop.labs.rag.embeddings.contracts import EmbeddingRuntimeUnavailableError
from ai_workshop.labs.rag.generation.citation_validation import CitationValidator
from ai_workshop.labs.rag.generation.contracts import (
    GenerationRuntimeResponseError,
    GenerationRuntimeUnavailableError,
)
from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    ConversationRole,
    ConversationTurn,
    GenerationOutcome,
    GenerationRequest,
    GenerationStatus,
    GroundingEvidence,
)
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.highlighting.domain import (
    EvidenceSelection,
    EvidenceSource,
)
from ai_workshop.labs.rag.highlighting.service import EvidenceSelector
from ai_workshop.labs.rag.retrieval.domain import FusedHit
from ai_workshop.labs.rag.retrieval.service import (
    DenseRetrieverPort,
    HybridRetrievalService,
    SearchScopeResolverPort,
    SparseRetrieverPort,
)
from ai_workshop.labs.rag.search.configuration_port import (
    ResolvedSearchConfiguration,
    SearchConfigurationResolverPort,
)
from ai_workshop.shared.errors import AppError
from ai_workshop.shared.request_context import correlation_id_context

if TYPE_CHECKING:
    from ai_workshop.labs.rag.search.schemas import SearchRequest


class SearchSourceResolverPort(Protocol):
    async def resolve(
        self,
        *,
        actor_id: UUID,
        indexing_profile_id: UUID,
        hits: tuple[FusedHit, ...],
    ) -> tuple[EvidenceSource, ...]: ...


@dataclass(frozen=True, slots=True)
class RelatedSource:
    source: EvidenceSource


@dataclass(frozen=True, slots=True)
class SearchResult:
    selection: EvidenceSelection
    configuration: ResolvedSearchConfiguration
    related_sources: tuple[RelatedSource, ...]
    retrieved_evidence_ids: tuple[UUID, ...] = ()
    resolved_query: str = ""
    generation: GenerationOutcome = GenerationOutcome(
        status=GenerationStatus.NOT_REQUESTED
    )


class SearchApplicationService:
    def __init__(
        self,
        *,
        configuration_resolver: SearchConfigurationResolverPort,
        scope_resolver: SearchScopeResolverPort,
        sparse_retriever: SparseRetrieverPort,
        dense_retriever: DenseRetrieverPort,
        source_resolver: SearchSourceResolverPort,
        turn_signer: ConversationTurnSigner | None = None,
    ) -> None:
        self.configuration_resolver = configuration_resolver
        self.scope_resolver = scope_resolver
        self.sparse_retriever = sparse_retriever
        self.dense_retriever = dense_retriever
        self.source_resolver = source_resolver
        self.turn_signer = turn_signer

    async def search(self, *, actor_id: UUID, request: SearchRequest) -> SearchResult:
        configuration = await self.configuration_resolver.resolve(
            request.configuration_id,
            actor_id,
        )
        return await self._search(actor_id=actor_id, request=request, configuration=configuration)

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
        return await self._search(actor_id=actor_id, request=request, configuration=configuration)

    async def _search(
        self,
        *,
        actor_id: UUID,
        request: SearchRequest,
        configuration: ResolvedSearchConfiguration,
    ) -> SearchResult:
        if configuration.experimental and not request.experimental:
            raise AppError(
                "experimental_opt_in_required",
                "The selected configuration requires explicit experimental opt-in.",
                409,
            )
        policy = configuration.answer_policy
        if configuration.answer_policy_version_id is None or policy is None:
            raise AppError(
                "answer_policy_missing",
                "The selected search configuration has no answer policy version.",
                409,
            )
        if not set(request.workspace_ids).issubset(configuration.workspace_ids):
            raise AppError("not_found", "The requested resource was not found.", 404)

        generation_profile = configuration.generation_profile
        generation_runtime = configuration.generation_runtime
        if generation_profile is not None and (
            generation_runtime is None or self.turn_signer is None
        ):
            raise AppError(
                "llm_unavailable",
                "Answer generation is temporarily unavailable.",
                503,
            )
        history = self._validated_history(
            request=request,
            actor_id=actor_id,
            configuration=configuration,
        )
        bounded_history = history
        if generation_profile is not None:
            assert generation_runtime is not None
            bounded_history = generation_profile.context_policy.select(
                history,
                token_counter=configuration.embedding.count_tokens,
            )
            try:
                generation_ready = (await generation_runtime.health()).ready
            except (
                GenerationProviderError,
                GenerationRuntimeUnavailableError,
                GenerationRuntimeResponseError,
            ):
                generation_ready = False
            if not generation_ready:
                raise AppError(
                    "llm_unavailable",
                    "Answer generation is temporarily unavailable.",
                    503,
                )
        resolved_query = request.query.strip()
        if generation_profile is not None and bounded_history:
            assert generation_runtime is not None
            try:
                contextualization = await generation_runtime.contextualize(
                    ContextualizationRequest(
                        question=request.query.strip(),
                        history=bounded_history,
                        profile=generation_profile,
                    )
                )
                resolved_query = contextualization.resolved_query
            except (
                GenerationProviderError,
                GenerationRuntimeUnavailableError,
                GenerationRuntimeResponseError,
            ) as exc:
                raise AppError(
                    "query_contextualization_unavailable",
                    "Conversation context is temporarily unavailable.",
                    503,
                ) from exc

        retrieval = HybridRetrievalService(
            scope_resolver=self.scope_resolver,
            embedding=configuration.embedding,
            sparse_retriever=self.sparse_retriever,
            dense_retriever=self.dense_retriever,
        )
        hits = await retrieval.search(
            actor_id=actor_id,
            query=resolved_query,
            workspace_ids=tuple(request.workspace_ids),
            folder_ids=tuple(request.folder_ids),
            indexing_profile_id=configuration.indexing_profile_id,
            retrieval_profile=configuration.retrieval_profile,
            index_alias=configuration.active_index_alias,
            result_limit=request.top_k,
            query_max_tokens=configuration.query_max_tokens,
        )
        sources = await self.source_resolver.resolve(
            actor_id=actor_id,
            indexing_profile_id=configuration.indexing_profile_id,
            hits=hits,
        )
        try:
            selection = EvidenceSelector(configuration.embedding).select(
                query=resolved_query,
                sources=sources,
                policy=policy,
            )
        except EmbeddingRuntimeUnavailableError as exc:
            raise AppError(
                "evidence_embedding_unavailable",
                "Evidence selection is temporarily unavailable.",
                503,
            ) from exc
        generation = await self._generate(
            actor_id=actor_id,
            original_query=request.query.strip(),
            resolved_query=resolved_query,
            history=bounded_history,
            configuration=configuration,
            selection=selection,
        )
        return SearchResult(
            selection=selection,
            configuration=configuration,
            related_sources=_related_sources(sources, selection),
            retrieved_evidence_ids=tuple(
                evidence.id
                for source in sources
                for evidence in source.chunk.evidence_units
            ),
            resolved_query=resolved_query,
            generation=generation,
        )

    def _validated_history(
        self,
        *,
        request: SearchRequest,
        actor_id: UUID,
        configuration: ResolvedSearchConfiguration,
    ) -> tuple[ConversationTurn, ...]:
        history: list[ConversationTurn] = []
        for item in request.history:
            try:
                turn = ConversationTurn(
                    role=ConversationRole(item.role),
                    content=item.content,
                    turn_id=item.turn_id,
                    validation_token=item.validation_token,
                )
            except ValueError as exc:
                raise AppError(
                    "conversation_history_invalid",
                    "Conversation history is invalid.",
                    422,
                ) from exc
            if turn.role is ConversationRole.ASSISTANT:
                if self.turn_signer is None or not self.turn_signer.verify(
                    turn,
                    actor_id=actor_id,
                    configuration_version_id=configuration.configuration_version_id,
                ):
                    raise AppError(
                        "conversation_history_invalid",
                        "Conversation history is invalid.",
                        422,
                    )
            elif turn.turn_id is not None or turn.validation_token is not None:
                raise AppError(
                    "conversation_history_invalid",
                    "Conversation history is invalid.",
                    422,
                )
            history.append(turn)
        return tuple(history)

    async def _generate(
        self,
        *,
        actor_id: UUID,
        original_query: str,
        resolved_query: str,
        history: tuple[ConversationTurn, ...],
        configuration: ResolvedSearchConfiguration,
        selection: EvidenceSelection,
    ) -> GenerationOutcome:
        profile = configuration.generation_profile
        if profile is None:
            return GenerationOutcome(status=GenerationStatus.NOT_REQUESTED)
        if selection.status.value == "insufficient_evidence":
            return GenerationOutcome(status=GenerationStatus.INSUFFICIENT_EVIDENCE)
        generation_runtime = configuration.generation_runtime
        if generation_runtime is None or self.turn_signer is None:
            raise AppError(
                "llm_unavailable",
                "Answer generation is temporarily unavailable.",
                503,
            )
        evidence = _generation_evidence(selection)
        try:
            generation_result = await generation_runtime.generate(
                GenerationRequest(
                    question=original_query,
                    resolved_query=resolved_query,
                    history=history,
                    evidence=evidence,
                    profile=profile,
                    correlation_id=correlation_id_context.get(),
                )
            )
            draft = generation_result.generation
        except (
            GenerationProviderError,
            GenerationRuntimeUnavailableError,
            GenerationRuntimeResponseError,
        ) as exc:
            raise AppError(
                "llm_unavailable",
                "Answer generation is temporarily unavailable.",
                503,
            ) from exc
        outcome = CitationValidator().validate(draft, allowed_evidence=evidence)
        if outcome.status is not GenerationStatus.ANSWERED or outcome.text is None:
            return outcome
        turn_id = uuid4()
        return replace(
            outcome,
            turn_id=turn_id,
            validation_token=self.turn_signer.sign(
                content=outcome.text,
                actor_id=actor_id,
                turn_id=turn_id,
                configuration_version_id=configuration.configuration_version_id,
            ),
        )


def _generation_evidence(
    selection: EvidenceSelection,
) -> tuple[GroundingEvidence, ...]:
    answers = (
        *((selection.answer,) if selection.answer is not None else ()),
        *selection.conflicts,
    )
    return tuple(
        GroundingEvidence(
            evidence_id=answer.evidence.id,
            text=answer.evidence.text,
            document_id=answer.source.document_id,
            asset_version_id=answer.source.chunk.asset_version_id,
            projection_id=answer.evidence.projection_id,
            chunk_id=answer.evidence.chunk_id,
            element_id=answer.evidence.location.element_id,
            page=answer.evidence.location.page,
            char_start=answer.evidence.location.char_start,
            char_end=answer.evidence.location.char_end,
            bbox=answer.evidence.location.bbox,
        )
        for answer in answers
    )


def _related_sources(
    sources: tuple[EvidenceSource, ...],
    selection: EvidenceSelection,
) -> tuple[RelatedSource, ...]:
    selected_version_ids = {
        item.source.chunk.asset_version_id
        for item in (
            *((selection.answer,) if selection.answer is not None else ()),
            *selection.conflicts,
        )
    }
    seen: set[UUID] = set()
    related: list[RelatedSource] = []
    for source in sources:
        version_id = source.chunk.asset_version_id
        if version_id in selected_version_ids or version_id in seen:
            continue
        seen.add(version_id)
        related.append(RelatedSource(source))
    return tuple(related)
