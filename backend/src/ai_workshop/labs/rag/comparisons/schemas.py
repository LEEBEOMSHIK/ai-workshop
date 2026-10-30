"""Bounded allowlist for immutable, imported model-comparison observations."""

import json
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

MAX_IMPORT_BYTES = 2 * 1024 * 1024
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=8000)]
Label = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=180)]
Note = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2000)]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
Money = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,12})?$"),
]
Seconds = Annotated[float, Field(strict=True, ge=0, le=10_000_000, allow_inf_nan=False)]
Count = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)]
Positive = Annotated[int, Field(strict=True, ge=1, le=100_000)]
Reference = Annotated[str, StringConstraints(strict=True, pattern=r"^e[1-9][0-9]{0,3}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComparisonEvidence(StrictModel):
    ref: Reference
    evidence_id: UUID
    document_id: UUID
    asset_version_id: UUID
    projection_id: UUID
    index_build_id: UUID
    retrieval_chunk_id: UUID
    element_id: UUID
    title: Label
    text: Text
    ordinal: Count
    page: Positive | None
    char_start: Count
    char_end: Count
    bbox: list[Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0, le=100_000)]] | None
    source_kind: Literal["normalized_text", "pdf_page", "docx_image"]

    @model_validator(mode="after")
    def valid_location(self) -> Self:
        if self.char_end < self.char_start:
            raise ValueError("invalid_evidence_range")
        if self.bbox is not None and (
            len(self.bbox) != 4 or self.bbox[0] > self.bbox[2] or self.bbox[1] > self.bbox[3]
        ):
            raise ValueError("invalid_evidence_bbox")
        return self


class ComparisonCitation(StrictModel):
    claim_index: Annotated[int, Field(strict=True, ge=0, le=199)]
    evidence_refs: list[Reference] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_references(self) -> Self:
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("duplicate_citation_reference")
        return self


class ComparisonCriterion(StrictModel):
    key: Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,79}$")]
    label: Label
    status: Literal["met", "not_met", "not_applicable", "unreviewed"]
    explanation: Note


class ComparisonQuality(StrictModel):
    schema_valid: StrictBool
    citation_validator_passed: StrictBool
    baseline_answer_equal: StrictBool | None
    baseline_citations_equal: StrictBool | None
    semantic_review: Literal["passed", "failed", "partial", "unreviewed"]
    review_summary: Text
    criteria: list[ComparisonCriterion] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_criteria(self) -> Self:
        if len({item.key for item in self.criteria}) != len(self.criteria):
            raise ValueError("duplicate_quality_criterion")
        return self


class ComparisonNativeTiming(StrictModel):
    load_seconds: Seconds | None
    input_seconds: Seconds | None
    output_seconds: Seconds | None
    total_seconds: Seconds | None

    @model_validator(mode="after")
    def valid_native_parts(self) -> Self:
        parts = (self.load_seconds, self.input_seconds, self.output_seconds)
        if (
            self.total_seconds is not None
            and sum(part for part in parts if part is not None) > self.total_seconds + 1e-6
        ):
            raise ValueError("native_parts_exceed_total")
        return self


class ComparisonUsage(StrictModel):
    input_tokens: Count | None
    output_tokens: Count | None
    cached_input_tokens: Count | None
    cache_write_tokens: Count | None
    reasoning_tokens: Count | None

    @model_validator(mode="after")
    def consistent_counts(self) -> Self:
        if (
            self.reasoning_tokens is not None
            and self.output_tokens is not None
            and self.reasoning_tokens > self.output_tokens
        ):
            raise ValueError("reasoning_exceeds_output")
        if self.input_tokens is not None:
            for value in (self.cached_input_tokens, self.cache_write_tokens):
                if value is not None and value > self.input_tokens:
                    raise ValueError("cache_exceeds_input")
        return self


class ComparisonRequest(StrictModel):
    sequence: Annotated[int, Field(strict=True, ge=1, le=40)]
    provider: Label
    model: Label
    repetition: Annotated[int, Field(strict=True, ge=1, le=20)]
    condition: Literal["first", "repeat"]
    duration_seconds: Seconds
    first_token_seconds: Seconds | None
    native_timing: ComparisonNativeTiming | None
    usage: ComparisonUsage
    estimated_cost_usd: Money | None
    actual_billed_cost_usd: Money | None
    cost_status: Literal["usage_estimate", "not_applicable", "unknown"]
    pricing_basis: Note | None
    answer: Text
    citations: list[ComparisonCitation] = Field(min_length=1, max_length=200)
    quality: ComparisonQuality

    @model_validator(mode="after")
    def consistent_observation(self) -> Self:
        if (
            self.first_token_seconds is not None
            and self.first_token_seconds > self.duration_seconds
        ):
            raise ValueError("first_token_exceeds_completion")
        if (self.condition == "first") != (self.repetition == 1):
            raise ValueError("condition_repetition_mismatch")
        if len({item.claim_index for item in self.citations}) != len(self.citations):
            raise ValueError("duplicate_claim_index")
        if (self.cost_status == "usage_estimate") != (self.estimated_cost_usd is not None):
            raise ValueError("cost_status_mismatch")
        if self.cost_status == "not_applicable" and self.actual_billed_cost_usd is not None:
            raise ValueError("inapplicable_billed_cost")
        return self


class ComparisonAnalysis(StrictModel):
    title: Label
    body: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=16000)]


class ComparisonImport(StrictModel):
    schema_version: Literal[1]
    source_key: Annotated[
        str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
    ]
    title: Label
    question: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4000)]
    completed_at: AwareDatetime
    unique_question_count: Literal[1]
    measurement_scope: Literal["complete_nonstream_generation_response"]
    source_result_sha256: Digest
    source_ledger_sha256: Digest
    source_input_sha256: Digest
    controls: list[Note] = Field(min_length=1, max_length=30)
    evidence: list[ComparisonEvidence] = Field(min_length=1, max_length=200)
    requests: list[ComparisonRequest] = Field(min_length=2, max_length=40)
    estimated_total_usd: Money | None
    actual_billed_total_usd: Money | None
    billing_status: Literal["not_reconciled", "reconciled", "not_applicable"]
    analysis: list[ComparisonAnalysis] = Field(min_length=1, max_length=20)
    limitations: list[Note] = Field(min_length=1, max_length=30)

    @field_validator("schema_version", "unique_question_count", mode="before")
    @classmethod
    def strict_literal_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("integer_required")
        return value

    @model_validator(mode="after")
    def consistent_report(self) -> Self:
        refs = {item.ref for item in self.evidence}
        if len(refs) != len(self.evidence) or len({e.evidence_id for e in self.evidence}) != len(
            refs
        ):
            raise ValueError("duplicate_evidence")
        if [item.sequence for item in self.requests] != list(range(1, len(self.requests) + 1)):
            raise ValueError("invalid_request_order")
        identities = {(item.provider, item.model, item.repetition) for item in self.requests}
        if len(identities) != len(self.requests):
            raise ValueError("duplicate_model_repetition")
        for request in self.requests:
            if any(not set(c.evidence_refs) <= refs for c in request.citations):
                raise ValueError("unknown_citation_reference")
        self._validate_costs()
        if len(self.model_dump_json().encode("utf-8")) > MAX_IMPORT_BYTES:
            raise ValueError("comparison_too_large")
        return self

    def _validate_costs(self) -> None:
        applicable = [r for r in self.requests if r.cost_status != "not_applicable"]
        with localcontext() as context:
            context.prec = 50
            known = [
                Decimal(r.estimated_cost_usd)
                for r in applicable
                if r.estimated_cost_usd is not None
            ]
            expected = (
                sum(known, Decimal(0)) if applicable and len(known) == len(applicable) else None
            )
            supplied = (
                Decimal(self.estimated_total_usd) if self.estimated_total_usd is not None else None
            )
            if supplied != expected:
                raise ValueError("estimated_total_mismatch")
            if self.billing_status == "not_applicable":
                if applicable or self.actual_billed_total_usd is not None:
                    raise ValueError("billing_status_mismatch")
            elif not applicable:
                raise ValueError("billing_status_mismatch")
            if self.billing_status != "reconciled":
                if self.actual_billed_total_usd is not None or any(
                    r.actual_billed_cost_usd is not None for r in self.requests
                ):
                    raise ValueError("unreconciled_actual_cost")
            else:
                if self.actual_billed_total_usd is None or any(
                    r.actual_billed_cost_usd is None for r in applicable
                ):
                    raise ValueError("missing_billed_cost")
                billed = sum(
                    (
                        Decimal(r.actual_billed_cost_usd)
                        for r in applicable
                        if r.actual_billed_cost_usd is not None
                    ),
                    Decimal(0),
                )
                if Decimal(self.actual_billed_total_usd) != billed:
                    raise ValueError("billed_total_mismatch")

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")


class ComparisonDetail(StrictModel):
    id: UUID
    record_kind: Literal["imported_comparison"] = "imported_comparison"
    created_at: datetime
    content_sha256: Digest
    report: ComparisonImport


class ComparisonSummary(StrictModel):
    id: UUID
    record_kind: Literal["imported_comparison"] = "imported_comparison"
    source_key: str
    title: str
    question: str
    completed_at: datetime
    created_at: datetime
    unique_question_count: Literal[1] = 1
    request_count: int
    models: list[str]
    estimated_total_usd: Money | None
    billing_status: Literal["not_reconciled", "reconciled", "not_applicable"]


class ComparisonList(StrictModel):
    items: list[ComparisonSummary]
