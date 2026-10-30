from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_workshop.labs.rag.executions.agent_trace import AgentEvidenceRef, AgentTraceCollector
from ai_workshop.labs.rag.generation.domain import GenerationRequest, StructuredGeneration
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    ProviderExecutionMetadata,
)

MANAGER = "rag_manager"
SPECIALIST = "answer_specialist"
EVIDENCE_SPECIALIST = "evidence_specialist"
REVIEW_SPECIALIST = "review_specialist"
RAG_SPECIALISTS = (EVIDENCE_SPECIALIST, SPECIALIST, REVIEW_SPECIALIST)
ANSWER_TOOL = "write_grounded_answer"


class DelegationInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    task: str = Field(min_length=1, max_length=4000, pattern=r"\S")


@dataclass
class OrchestrationContext:
    request: GenerationRequest
    collector: AgentTraceCollector
    revalidate: Callable[[], Awaitable[None]] | None
    prior_model_calls: int = 0
    prior_reserved_output_tokens: int = 0
    started: float = field(default_factory=monotonic)
    agent_spans: dict[str, UUID] = field(default_factory=dict)
    agent_inputs: dict[str, str] = field(default_factory=dict)
    active_agent: str = MANAGER
    delegation_span: UUID | None = None
    model_calls: int = 0
    tool_calls: int = 0
    reserved_output_tokens: int = 0
    usages: list[tuple[int | None, int | None]] = field(default_factory=list)
    child_output: StructuredGeneration | None = None
    failure: Exception | None = None
    handoff_task: str | None = None

    @property
    def autonomous(self) -> bool:
        policy = self.request.profile.orchestration
        return policy is not None and policy.dispatch_mode == "autonomous_handoffs"

    def allowed_handoffs(self) -> tuple[str, ...]:
        if not self.autonomous or self.active_agent not in RAG_SPECIALISTS:
            return ()
        return tuple(f"transfer_to_{name}" for name in RAG_SPECIALISTS
                     if name != self.active_agent)

    def reserve_model(self, max_tokens: object) -> None:
        policy = self.request.profile.orchestration
        assert policy is not None
        if (
            type(max_tokens) is not int or max_tokens < 1
            or self.model_calls + self.prior_model_calls >= policy.max_model_calls
            or self.reserved_output_tokens + self.prior_reserved_output_tokens + max_tokens
            > policy.max_total_output_tokens
        ):
            raise GenerationProviderError("orchestration_budget_exceeded", retryable=False)
        self.model_calls += 1
        self.reserved_output_tokens += max_tokens

    def reserve_tool(self) -> None:
        policy = self.request.profile.orchestration
        assert policy is not None
        if self.tool_calls >= policy.max_tool_calls:
            raise GenerationProviderError("orchestration_budget_exceeded", retryable=False)
        self.tool_calls += 1

    def metadata(self) -> ProviderExecutionMetadata:
        profile = self.request.profile
        assert profile.deployment is not None

        def total(index: int) -> int | None:
            values = [usage[index] for usage in self.usages]
            if len(values) != self.model_calls or any(value is None for value in values):
                return None
            result = sum(value for value in values if value is not None)
            return result if result <= 2**31 - 1 else None

        return ProviderExecutionMetadata(
            profile.deployment.provider, profile.runtime_model, profile.deployment.id,
            total(0), total(1), max(0, int((monotonic() - self.started) * 1000)),
        )

    def evidence_refs(self) -> tuple[AgentEvidenceRef, ...]:
        refs = dict.fromkeys((e.document_id, e.asset_version_id, e.projection_id)
                             for e in self.request.evidence)
        result = []
        for document, version, projection in refs:
            if projection is None:
                raise GenerationProviderError("orchestration_not_supported", retryable=False)
            result.append(AgentEvidenceRef(document_id=document, asset_version_id=version,
                                           projection_id=projection))
        return tuple(result)
