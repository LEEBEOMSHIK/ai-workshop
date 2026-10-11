"""Pure, immutable proof values. Source/answer content never appears in repr."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal
from uuid import UUID

type CalculationOperation = Literal["percentage_point_difference", "convert_krw_unit"]


@dataclass(frozen=True, slots=True)
class CalculationProposal:
    operation: CalculationOperation
    operand_token_ids: tuple[str, ...]
    result_start: int
    result_end: int


@dataclass(frozen=True, slots=True)
class VerifiedOperand:
    evidence_id: UUID
    document_id: UUID
    asset_version_id: UUID
    projection_id: UUID | None
    chunk_id: UUID | None
    element_id: UUID
    token_start: int
    token_end: int
    char_start: int
    char_end: int
    page: int | None
    unit: str


@dataclass(frozen=True, slots=True)
class VerifiedCalculation:
    operation: CalculationOperation
    result_start: int
    result_end: int
    operands: tuple[VerifiedOperand, ...]
    policy_ref: str


@dataclass(frozen=True, slots=True)
class SourceValueToken:
    token_id: str
    evidence_id: UUID
    start: int
    end: int
    unit: str
    value: Decimal = field(repr=False)


@dataclass(frozen=True, slots=True)
class SourceValueCatalogue:
    request_id: UUID
    configuration_version_id: UUID
    generation_profile_id: UUID
    policy_ref: str
    policy_digest: str
    evidence_digest: str
    digest: str
    tokens: tuple[SourceValueToken, ...] = field(repr=False)
    evidence_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidatedNumericClaim:
    claim_index: int
    text: str = field(repr=False)
    evidence_ids: tuple[UUID, ...]
    calculations: tuple[VerifiedCalculation, ...]


@dataclass(frozen=True, slots=True)
class ValidatedGenerationPayload:
    schema_version: int
    status: str
    answer: str | None = field(repr=False)
    claims: tuple[ValidatedNumericClaim, ...] = field(repr=False)
    request_id: UUID
    configuration_version_id: UUID
    generation_profile_id: UUID
    policy_ref: str
    policy_digest: str
    catalogue_digest: str


@dataclass(frozen=True, slots=True)
class NumericValidationBinding:
    validation_id: UUID
    audit_id: UUID
    request_id: UUID
    configuration_version_id: UUID
    generation_profile_id: UUID
    schema_version: int
    policy_ref: str
    policy_digest: str
    catalogue_digest: str
    payload_digest: str


@dataclass(frozen=True, slots=True)
class ExpectedNumericContext:
    actor_id: UUID
    execution_id: UUID
    request_id: UUID
    configuration_version_id: UUID
    generation_profile_id: UUID
    schema_version: int
    policy_ref: str
    policy_digest: str
    evidence_ids: tuple[UUID, ...]
