from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field

from ai_workshop.labs.rag.deployments.domain import ExecutionLocation, ProviderKind
from ai_workshop.labs.rag.highlighting.domain import (
    AnswerStatus,
    ConflictState,
    EvidenceAnswer,
    HighlightKind,
    HighlightSpan,
)
from ai_workshop.labs.rag.search.service import RelatedSource, SearchResult


class ConversationTurnRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)
    turn_id: UUID | None = None
    validation_token: str | None = Field(default=None, max_length=256)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    configuration_id: UUID
    workspace_ids: list[UUID] = Field(min_length=1)
    folder_ids: list[UUID] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=50)
    experimental: bool = False
    history: list[ConversationTurnRequest] = Field(default_factory=list, max_length=20)


class GeneratedCitationResponse(BaseModel):
    claim_index: int
    evidence_ids: list[UUID]


class GenerationExecutionResponse(BaseModel):
    provider: ProviderKind
    model_name: str
    model_version: int
    deployment_name: str
    location: ExecutionLocation
    external_transfer: bool
    disclosure: str


class GenerationResponse(BaseModel):
    status: Literal[
        "answered",
        "not_requested",
        "insufficient_evidence",
        "citation_validation_failed",
    ]
    text: str | None
    citations: list[GeneratedCitationResponse]
    reason_codes: list[str]
    turn_id: UUID | None
    validation_token: str | None
    execution: GenerationExecutionResponse | None


class SourceLocationResponse(BaseModel):
    element_id: UUID
    page: int | None
    char_start: int
    char_end: int
    bbox: tuple[float, float, float, float] | None


class HighlightSpanResponse(BaseModel):
    kind: HighlightKind
    evidence_unit_id: UUID
    text: str
    char_start: int
    char_end: int
    page: int | None
    bbox: tuple[float, float, float, float] | None
    score: float | None
    warnings: list[str]

    @classmethod
    def from_domain(cls, span: HighlightSpan) -> Self:
        return cls(
            kind=span.kind,
            evidence_unit_id=span.evidence_unit_id,
            text=span.text,
            char_start=span.char_start,
            char_end=span.char_end,
            page=span.page,
            bbox=span.bbox,
            score=span.score,
            warnings=list(span.warnings),
        )


class SourceReferenceResponse(BaseModel):
    document_id: UUID
    asset_version_id: UUID
    asset_version_number: int
    workspace_id: UUID
    folder_id: UUID | None
    projection_id: UUID
    chunk_id: UUID
    evidence_unit_id: UUID
    element_id: UUID
    title: str
    media_type: str
    section_path: list[str]
    location: SourceLocationResponse

    @classmethod
    def from_answer(cls, answer: EvidenceAnswer) -> Self:
        source = answer.source
        evidence = answer.evidence
        location = evidence.location
        return cls(
            document_id=source.document_id,
            asset_version_id=source.chunk.asset_version_id,
            asset_version_number=source.asset_version_number,
            workspace_id=source.chunk.workspace_id,
            folder_id=source.chunk.folder_id,
            projection_id=source.chunk.projection_id,
            chunk_id=source.chunk.chunk_id,
            evidence_unit_id=evidence.id,
            element_id=location.element_id,
            title=source.chunk.title,
            media_type=source.media_type,
            section_path=list(source.chunk.section_path),
            location=SourceLocationResponse(
                element_id=location.element_id,
                page=location.page,
                char_start=location.char_start,
                char_end=location.char_end,
                bbox=location.bbox,
            ),
        )


class EvidenceAnswerResponse(BaseModel):
    excerpt: str
    source: SourceReferenceResponse
    highlights: list[HighlightSpanResponse]
    keyword_coverage: float | None
    semantic_score: float | None
    warnings: list[str]

    @classmethod
    def from_domain(cls, answer: EvidenceAnswer) -> Self:
        return cls(
            excerpt=answer.excerpt,
            source=SourceReferenceResponse.from_answer(answer),
            highlights=[HighlightSpanResponse.from_domain(item) for item in answer.highlights],
            keyword_coverage=answer.keyword_coverage,
            semantic_score=answer.semantic_score,
            warnings=list(answer.warnings),
        )


class RelatedSourceResponse(BaseModel):
    document_id: UUID
    asset_version_id: UUID
    asset_version_number: int
    workspace_id: UUID
    folder_id: UUID | None
    projection_id: UUID
    chunk_id: UUID
    title: str
    media_type: str
    section_path: list[str]
    fused_score: float

    @classmethod
    def from_domain(cls, related: RelatedSource) -> Self:
        source = related.source
        return cls(
            document_id=source.document_id,
            asset_version_id=source.chunk.asset_version_id,
            asset_version_number=source.asset_version_number,
            workspace_id=source.chunk.workspace_id,
            folder_id=source.chunk.folder_id,
            projection_id=source.chunk.projection_id,
            chunk_id=source.chunk.chunk_id,
            title=source.chunk.title,
            media_type=source.media_type,
            section_path=list(source.chunk.section_path),
            fused_score=source.fused_score,
        )


class ConfigurationVersionResponse(BaseModel):
    configuration_id: UUID
    version_id: UUID
    version: int


class SearchResponse(BaseModel):
    status: AnswerStatus
    answer: EvidenceAnswerResponse | None
    conflict_state: ConflictState
    conflicts: list[EvidenceAnswerResponse]
    warnings: list[str]
    related_sources: list[RelatedSourceResponse]
    configuration_version: ConfigurationVersionResponse
    experimental: bool
    resolved_query: str
    generation: GenerationResponse

    @classmethod
    def from_domain(cls, result: SearchResult) -> Self:
        selection = result.selection
        configuration = result.configuration
        return cls(
            status=selection.status,
            answer=(
                EvidenceAnswerResponse.from_domain(selection.answer)
                if selection.answer is not None
                else None
            ),
            conflict_state=selection.conflict_state,
            conflicts=[EvidenceAnswerResponse.from_domain(item) for item in selection.conflicts],
            warnings=list(selection.warnings),
            related_sources=[
                RelatedSourceResponse.from_domain(item) for item in result.related_sources
            ],
            configuration_version=ConfigurationVersionResponse(
                configuration_id=configuration.configuration_id,
                version_id=configuration.configuration_version_id,
                version=configuration.configuration_version,
            ),
            experimental=configuration.experimental,
            resolved_query=result.resolved_query,
            generation=GenerationResponse(
                status=result.generation.status.value,
                text=result.generation.text,
                citations=[
                    GeneratedCitationResponse(
                        claim_index=item.claim_index,
                        evidence_ids=list(item.evidence_ids),
                    )
                    for item in result.generation.citations
                ],
                reason_codes=list(result.generation.reason_codes),
                turn_id=result.generation.turn_id,
                validation_token=result.generation.validation_token,
                execution=(
                    GenerationExecutionResponse(
                        provider=result.generation.execution.provider,
                        model_name=result.generation.execution.model_name,
                        model_version=result.generation.execution.model_version,
                        deployment_name=result.generation.execution.deployment_name,
                        location=result.generation.execution.location,
                        external_transfer=(
                            result.generation.execution.external_transfer
                        ),
                        disclosure=result.generation.execution.disclosure,
                    )
                    if result.generation.execution is not None
                    else None
                ),
            ),
        )


class NormalizedElementResponse(BaseModel):
    id: UUID
    ordinal: int
    kind: str
    text: str
    section_path: list[str]
    location: SourceLocationResponse
    confidence: float | None


class NormalizedTextResponse(BaseModel):
    document_id: UUID
    asset_version_id: UUID
    asset_version_number: int
    workspace_id: UUID
    folder_id: UUID | None
    projection_id: UUID
    title: str
    media_type: str
    parser_name: str
    parser_version: str
    elements: list[NormalizedElementResponse]
