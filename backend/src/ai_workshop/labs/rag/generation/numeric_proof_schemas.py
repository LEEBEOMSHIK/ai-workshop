"""Closed private proof DTOs and common canonical reconstruction."""

from collections.abc import Sequence
from dataclasses import asdict
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .numeric_proof_serialization import rebuild_validated_numeric_payload
from .numeric_proof_types import (
    CalculationOperation,
    NumericValidationBinding,
    ValidatedGenerationPayload,
    ValidatedNumericClaim,
    VerifiedCalculation,
    VerifiedOperand,
)


class ProofView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class VerifiedOperandView(ProofView):
    evidence_id: UUID
    document_id: UUID
    asset_version_id: UUID
    projection_id: UUID
    chunk_id: UUID
    element_id: UUID
    token_start: int = Field(ge=0, strict=True)
    token_end: int = Field(gt=0, strict=True)
    char_start: int = Field(ge=0, strict=True)
    char_end: int = Field(gt=0, strict=True)
    page: int | None
    unit: Literal["%", "원", "만원", "억원"]


class VerifiedCalculationView(ProofView):
    operation: CalculationOperation
    result_start: int = Field(ge=0, strict=True)
    result_end: int = Field(gt=0, strict=True)
    operands: tuple[VerifiedOperandView, ...] = Field(min_length=1, max_length=2)
    policy_ref: Literal["source-numeric-proof-v1"]


class NumericValidationBindingView(ProofView):
    validation_id: UUID
    audit_id: UUID
    request_id: UUID
    configuration_version_id: UUID
    generation_profile_id: UUID
    schema_version: Literal[3]
    policy_ref: Literal["source-numeric-proof-v1"]
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalogue_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_domain(
        cls, value: NumericValidationBinding | None
    ) -> "NumericValidationBindingView | None":
        return cls.model_validate(asdict(value)) if value is not None else None

    def domain(self) -> NumericValidationBinding:
        return NumericValidationBinding(**self.model_dump())


class ClaimView(Protocol):
    @property
    def claim_index(self) -> int: ...
    @property
    def evidence_ids(self) -> Sequence[UUID]: ...
    @property
    def claim_text(self) -> str | None: ...
    @property
    def calculations(self) -> tuple[VerifiedCalculationView, ...] | None: ...


def calculation_views(
    values: tuple[VerifiedCalculation, ...] | None,
) -> tuple[VerifiedCalculationView, ...] | None:
    return (
        tuple(VerifiedCalculationView.model_validate(asdict(value)) for value in values)
        if values is not None
        else None
    )


def payload_from_views(
    *,
    status: str,
    answer: str | None,
    claims: Sequence[ClaimView],
    binding: NumericValidationBindingView,
) -> ValidatedGenerationPayload:
    converted = []
    for claim in claims:
        if claim.claim_text is None or claim.calculations is None:
            raise ValueError("numeric_validation_binding_invalid")
        calculations = tuple(
            VerifiedCalculation(
                proof.operation,
                proof.result_start,
                proof.result_end,
                tuple(VerifiedOperand(**operand.model_dump()) for operand in proof.operands),
                proof.policy_ref,
            )
            for proof in claim.calculations
        )
        converted.append(
            ValidatedNumericClaim(
                claim.claim_index, claim.claim_text, tuple(claim.evidence_ids), calculations
            )
        )
    return rebuild_validated_numeric_payload(
        status=status, answer=answer, claims=tuple(converted), binding=binding.domain()
    )
