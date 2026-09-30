"""Versioned generation observations and explicitly scoped correctness judgments."""

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_workshop.labs.rag.executions.domain import StageName

METRIC_VERSION: Literal["generative-v1"] = "generative-v1"
type JudgmentStatus = Literal["passed", "failed", "unreviewed"]
type AnswerStatus = Literal[
    "answered",
    "insufficient_evidence",
    "citation_validation_failed",
    "not_requested",
]


class FrozenValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()


class ExpectedAnswerRule(FrozenValue):
    version: int = Field(ge=1)
    expected_answer_status: Literal["answered", "insufficient_evidence"]
    required_evidence_groups: tuple[tuple[UUID, ...], ...] = ()
    required_propositions: tuple[str, ...] = ()
    forbidden_propositions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if any(
            not group or len(group) != len(set(group)) for group in self.required_evidence_groups
        ):
            raise ValueError("Evidence alternatives must be nonempty and unique.")
        if self.expected_answer_status == "answered" and not self.required_evidence_groups:
            raise ValueError("A positive case requires authoritative evidence groups.")
        if any(
            not text.strip() for text in (*self.required_propositions, *self.forbidden_propositions)
        ):
            raise ValueError("Propositions must not be empty.")
        return self


class GenerativeObservation(FrozenValue):
    execution_id: UUID
    retrieved_evidence_ids: tuple[UUID, ...] = ()
    selected_evidence_ids: tuple[UUID, ...] = ()
    cited_evidence_ids: tuple[UUID, ...] = ()
    generation_status: AnswerStatus | None = None
    citation_valid: bool | None = None
    failure_stage: StageName | None = None
    error_code: str | None = Field(default=None, max_length=100, pattern=r"^[a-z0-9_]+$")
    duration_ms: float | None = Field(default=None, ge=0)
    requested_model: str | None = None
    observed_model: str | None = None
    access_exposures: tuple[UUID, ...] = ()
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class ClaimCitation(FrozenValue):
    claim_index: int = Field(ge=0)
    evidence_ids: tuple[UUID, ...]


class PrivateGenerativeResult(FrozenValue):
    observation: GenerativeObservation
    answer: str | None = None
    citations: tuple[ClaimCitation, ...] = ()
    evidence: tuple[dict[str, object], ...] = ()


class CorrectnessJudgment(FrozenValue):
    status: JudgmentStatus
    provenance: Literal["rule", "reviewer"]
    rule_version: int = Field(ge=1)
    rule_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer_id: UUID | None = None
    reviewed_at: datetime | None = None
    reason: str = Field(max_length=1000)

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        if self.provenance == "reviewer" and (self.reviewer_id is None or self.reviewed_at is None):
            raise ValueError("Reviewer identity and time are required.")
        if self.provenance == "rule" and self.reviewer_id is not None:
            raise ValueError("A rule judgment cannot impersonate a reviewer.")
        return self


class GenerativeMetrics(FrozenValue):
    metric_version: Literal["generative-v1"] = METRIC_VERSION
    retrieval_coverage: float | None
    context_coverage: float | None
    required_group_count: int
    generation_completed: bool
    citation_valid: bool | None
    correctness: JudgmentStatus
    abstention_correct: bool | None
    access_leaks: int
    duration_ms: float | None


class GenerativeAcceptancePolicy(FrozenValue):
    version: int = Field(ge=1)
    min_context_coverage: float = Field(ge=0, le=1)
    min_correctness: float = Field(ge=0, le=1)
    min_abstention: float = Field(ge=0, le=1)
    max_p95_latency_ms: float = Field(gt=0)
    require_valid_citations: Literal[True] = True
    max_access_leaks: Literal[0] = 0


def _coverage(ids: tuple[UUID, ...], rule: ExpectedAnswerRule) -> float | None:
    groups = rule.required_evidence_groups
    if not groups:
        return None
    return sum(bool(set(group).intersection(ids)) for group in groups) / len(groups)


def evaluate_generative(
    observation: GenerativeObservation,
    rule: ExpectedAnswerRule,
    judgment: CorrectnessJudgment | None,
) -> GenerativeMetrics:
    # Digest/result ownership is checked by the repository before passing a judgment.
    if judgment and (
        judgment.rule_version != rule.version or judgment.rule_digest != rule.digest()
    ):
        raise ValueError("The judgment belongs to another expected rule.")
    negative = rule.expected_answer_status == "insufficient_evidence"
    finished = observation.generation_status in {"answered", "insufficient_evidence"}
    abstention = (
        observation.generation_status == "insufficient_evidence" if negative and finished else None
    )
    correctness: JudgmentStatus = judgment.status if judgment else "unreviewed"
    if abstention is False:
        correctness = "failed"
    failed = observation.failure_stage is not None or observation.error_code is not None
    return GenerativeMetrics(
        retrieval_coverage=(
            None
            if failed and not observation.retrieved_evidence_ids
            else _coverage(observation.retrieved_evidence_ids, rule)
        ),
        context_coverage=(
            None
            if failed and not observation.selected_evidence_ids
            else _coverage(observation.selected_evidence_ids, rule)
        ),
        required_group_count=len(rule.required_evidence_groups),
        generation_completed=finished and observation.failure_stage is None,
        citation_valid=observation.citation_valid,
        correctness=correctness,
        abstention_correct=abstention,
        access_leaks=len(set(observation.access_exposures)),
        duration_ms=observation.duration_ms,
    )


def _normalized(value: str) -> str:
    # Same locale-independent normalization as PostgreSQL rag_normalize_proposition.
    translated = unicodedata.normalize("NFKC", value).translate(
        str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
    )
    return re.sub(r"[ \t\r\n\f\v]+", " ", translated).strip(" ")


def judge_propositions(
    result: PrivateGenerativeResult,
    rule: ExpectedAnswerRule,
) -> CorrectnessJudgment:
    observed = result.observation
    status: JudgmentStatus = "unreviewed"
    reason = "No deterministic content rule; reviewer judgment required."
    if observed.generation_status in {"answered", "insufficient_evidence"}:
        if observed.generation_status != rule.expected_answer_status:
            status, reason = "failed", "Answer status differs from the expected status."
        elif rule.expected_answer_status == "insufficient_evidence":
            status, reason = "passed", "Expected abstention; no semantic content judgment."
        elif rule.required_propositions:
            answer = _normalized(result.answer or "")
            matched = all(_normalized(v) in answer for v in rule.required_propositions)
            prohibited = any(_normalized(v) in answer for v in rule.forbidden_propositions)
            status = "passed" if matched and not prohibited else "failed"
            reason = "Normalized proposition matching only; not general semantic correctness."
    return CorrectnessJudgment(
        status=status,
        provenance="rule",
        rule_version=rule.version,
        rule_digest=rule.digest(),
        result_digest=result.digest(),
        reason=reason,
    )
