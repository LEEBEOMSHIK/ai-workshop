from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from ai_workshop.labs.rag.executions.domain import ExecutionState, StageName, StageObservation
from ai_workshop.labs.rag.search.schemas import (
    EvidenceAnswerResponse,
    GeneratedCitationResponse,
    GenerationExecutionResponse,
)


class ExecutionSearchRequest(BaseModel):
    query: str = Field(default="", max_length=500)
    domain_id: UUID | None = None
    kind: Literal["conversation", "evaluation"] | None = None
    status: ExecutionState | None = None
    answer_status: str | None = Field(default=None, max_length=40)
    failed_stage: StageName | None = None
    configuration_version_id: UUID | None = None
    started_after: AwareDatetime | None = None
    started_before: AwareDatetime | None = None
    cursor: str | None = Field(default=None, max_length=1024)
    limit: int = Field(default=25, ge=1, le=100)


class ExecutionSummary(BaseModel):
    id: UUID
    record_kind: Literal["execution", "legacy"]
    kind: Literal["conversation", "evaluation"] = "conversation"
    conversation_id: UUID | None
    turn_id: UUID | None
    domain_id: UUID | None
    domain_slug: str | None
    query: str
    created_at: datetime
    status: ExecutionState
    answer_status: str | None
    quality_status: Literal["unreviewed", "passed", "failed"] = "unreviewed"
    failed_stage: StageName | None = None
    error_code: str | None = None
    duration_ms: float | None = None
    document_count: int
    observation_complete: bool
    configuration_version_id: UUID | None = None


class ExecutionSearchResponse(BaseModel):
    items: list[ExecutionSummary]
    next_cursor: str | None
    total: int
    failed_count: int
    insufficient_count: int
    duration_count: int
    duration_missing: int
    median_ms: float | None
    p95_ms: float | None


class MonitoringGeneration(BaseModel):
    status: str
    text: str | None = None
    citations: list[GeneratedCitationResponse] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    execution: GenerationExecutionResponse | None = None


class ExecutionUsage(BaseModel):
    requested_model: str
    input_tokens: int | None
    output_tokens: int | None
    status: str
    error_code: str | None


class ExecutionDetailResponse(ExecutionSummary):
    stages: list[StageObservation]
    generation: MonitoringGeneration | None
    evidence: list[EvidenceAnswerResponse]
    usage: list[ExecutionUsage] = Field(default_factory=list)
    evaluation_run_id: UUID | None = None
    evaluation_case_id: UUID | None = None
