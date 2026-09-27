from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_workshop.labs.rag.evaluation.generative import (
    CorrectnessJudgment,
    ExpectedAnswerRule,
    GenerativeAcceptancePolicy,
    GenerativeMetrics,
    GenerativeObservation,
)
from ai_workshop.labs.rag.generation.codex_admin_api import CodexInputApprovalRequest
from ai_workshop.labs.rag.search.schemas import ConversationTurnRequest


class GenerativePolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    definition: GenerativeAcceptancePolicy


class GenerativePolicyView(GenerativePolicyCreate):
    id: UUID


class GenerativeRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    dataset_snapshot_id: UUID
    configuration_version_ids: list[UUID] = Field(min_length=1, max_length=10)
    policy_id: UUID
    expected_rules: dict[UUID, ExpectedAnswerRule]
    repetition_count: int = Field(default=2, ge=2, le=5)
    retrieval_k: int = Field(default=10, ge=1, le=50)
    case_histories: dict[UUID, list[ConversationTurnRequest]] = Field(default_factory=dict)
    input_approval: CodexInputApprovalRequest | None = None


class GenerativeSourceView(BaseModel):
    evidence_id: UUID
    document_id: UUID
    asset_version_id: UUID
    projection_id: UUID
    title: str
    page: int | None


class GenerativeAttemptView(BaseModel):
    id: UUID
    configuration_version_id: UUID
    case_id: UUID
    query: str
    repetition: int
    attempt_number: int
    status: str
    execution_id: UUID | None
    result_digest: str | None
    answer: str | None
    observation: GenerativeObservation | None
    metrics: GenerativeMetrics | None
    judgment: CorrectnessJudgment | None
    error_code: str | None
    sources: list[GenerativeSourceView]


class GenerativeRunView(BaseModel):
    id: UUID
    kind: Literal["generative"] = "generative"
    metric_version: Literal["generative-v1"] = "generative-v1"
    dataset_snapshot_id: UUID
    policy_id: UUID
    rules_digest: str
    status: str
    created_at: datetime
    repetition_count: int
    attempts: list[GenerativeAttemptView]


class GenerativeReviewRequest(BaseModel):
    result_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["passed", "failed", "unreviewed"]
    reason: str = Field(min_length=1, max_length=1000)


class GenerativeAcceptanceView(BaseModel):
    run_id: UUID
    configuration_version_id: UUID
    metric_version: Literal["generative-v1"] = "generative-v1"
    metrics: dict[str, object]
