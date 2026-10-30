from datetime import datetime
from typing import Literal, Protocol, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_workshop.labs.rag.executions.contextualization import ContextualizationObservation
from ai_workshop.labs.rag.executions.history_selection import HistorySelectionObservation
from ai_workshop.labs.rag.models.budget_trace import BudgetTrace

StageName = Literal[
    "request",
    "history",
    "contextualization",
    "retrieval",
    "selection",
    "generation",
    "citation_validation",
    "persistence",
]
StageState = Literal["pending", "running", "completed", "failed", "skipped", "unrecorded"]
ExecutionState = Literal["running", "completed", "failed", "cancelled", "interrupted"]
STAGES: tuple[StageName, ...] = (
    "request",
    "history",
    "contextualization",
    "retrieval",
    "selection",
    "generation",
    "citation_validation",
    "persistence",
)
MAX_RECORDED_CANDIDATES = 200
OperationName = Literal[
    "keyword.normalize",
    "keyword.offsets",
    "embedding.model_load",
    "embedding.tokenize",
    "embedding.query",
    "embedding.documents",
    "embedding.result_reuse",
    "retrieval.authorize",
    "retrieval.bm25",
    "retrieval.dense",
    "retrieval.sources",
    "selection.extractive",
    "selection.context",
    "retrieval.describe",
    "retrieval.pit_open",
    "retrieval.pit_close",
]


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class OperationTiming(Metadata):
    """Inclusive elapsed totals; overlapping operations must not be added as wall time."""

    name: OperationName
    duration_ms: float = Field(ge=0, strict=True)
    calls: int = Field(gt=0, strict=True)
    failures: int = Field(ge=0, strict=True)
    items: int = Field(ge=0, strict=True)
    reused_items: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def bounded_counts(self) -> Self:
        if self.failures > self.calls or self.reused_items > self.items:
            raise ValueError("Operation counts exceed their totals")
        return self


class ExecutionIdentity(Metadata):
    execution_id: UUID = Field(default_factory=uuid4)
    actor_id: UUID
    turn_id: UUID | None = None
    evaluation_attempt_id: UUID | None = None

    @model_validator(mode="after")
    def one_parent(self) -> Self:
        if (self.turn_id is None) == (self.evaluation_attempt_id is None):
            raise ValueError("Exactly one execution parent is required")
        return self


class CandidateObservation(Metadata):
    document_id: UUID
    asset_version_id: UUID
    projection_id: UUID
    evidence_unit_id: UUID
    page: int | None = None
    chunk_id: UUID | None = None
    sparse_rank: int | None = None
    sparse_score: float | None = None
    dense_rank: int | None = None
    dense_score: float | None = None
    fused_rank: int | None = None
    fused_score: float | None = None
    semantic_score: float | None = None
    keyword_coverage: float | None = None
    selected: bool = False
    reason: str = Field(max_length=80, pattern=r"^[a-z0-9_]+$")
    budget_trace: BudgetTrace | None = Field(default=None, exclude_if=lambda value: value is None)


class SelectionObservation(Metadata):
    candidates: list[CandidateObservation] = Field(default_factory=list, max_length=200)
    candidate_count: int = Field(default=0, ge=0)
    truncated: bool = False
    selected_count: int = Field(default=0, ge=0)
    min_semantic_score: float | None = None
    min_keyword_coverage: float | None = None
    group_limit: int | None = None
    unit_limit: int | None = None
    character_limit: int | None = None
    serialized_bytes: int | None = None
    configuration_version_id: UUID | None = None
    indexing_profile_id: UUID | None = None
    retrieval_profile_id: UUID | None = None
    generation_profile_id: UUID | None = None
    answer_policy_version_id: UUID | None = None


class StageObservation(Metadata):
    stage: StageName
    state: StageState
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    reason: str | None = Field(default=None, max_length=100, pattern=r"^[a-z0-9_]+$")
    selection: SelectionObservation | None = None
    history_selection: HistorySelectionObservation | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    contextualization: ContextualizationObservation | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    operations: list[OperationTiming] | None = Field(
        default=None, max_length=16, exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def unique_operations(self) -> Self:
        if self.history_selection is not None and self.stage != "request":
            raise ValueError("Final history selection belongs to the request stage")
        if self.contextualization is not None and self.stage != "contextualization":
            raise ValueError("Contextualization content belongs to its own stage")
        if self.operations is not None:
            names = [item.name for item in self.operations]
            if len(set(names)) != len(names):
                raise ValueError("Each operation name must have one aggregate per stage")
        return self


class ExecutionOutcome(Metadata):
    state: ExecutionState
    answer_status: str | None = Field(default=None, max_length=40)
    error_code: str | None = Field(default=None, max_length=100, pattern=r"^[a-z0-9_]+$")
    complete: bool = True


def terminal_transition(current: ExecutionState, proposed: ExecutionState) -> ExecutionState:
    return proposed if current == "running" else current


class ExecutionRecorder(Protocol):
    async def start(self, identity: ExecutionIdentity) -> None: ...
    async def record(self, execution_id: UUID, observation: StageObservation) -> None: ...
    async def finish(self, execution_id: UUID, outcome: ExecutionOutcome) -> None: ...
