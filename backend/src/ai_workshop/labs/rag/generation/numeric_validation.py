"""Recompute only explicit, self-cited occurrences with isolated Decimal arithmetic."""

from dataclasses import dataclass
from decimal import Context, Decimal, DecimalException, Inexact, Overflow, Rounded, localcontext
from uuid import UUID

from ai_workshop.labs.rag.models.numeric_proof_policy import SOURCE_NUMERIC_PROOF_V1

from .domain import (
    GeneratedCitation,
    GenerationOutcome,
    GenerationProfile,
    GenerationStatus,
    GroundingEvidence,
    StructuredGeneration,
)
from .exact_values import _VALUE, exact_values
from .numeric_catalogue import (
    build_source_value_catalogue,
    numeric_occurrences,
    whole_numeric_occurrence,
)
from .numeric_proof_types import (
    SourceValueCatalogue,
    ValidatedGenerationPayload,
    ValidatedNumericClaim,
    VerifiedCalculation,
    VerifiedOperand,
)


@dataclass(frozen=True, slots=True)
class ValidatedNumericGeneration:
    outcome: GenerationOutcome
    payload: ValidatedGenerationPayload | None
    evidence_ids: tuple[UUID, ...] = ()


class _Rejected(ValueError):
    pass


def _payload(
    status: GenerationStatus,
    answer: str | None,
    claims: tuple[ValidatedNumericClaim, ...],
    catalogue: SourceValueCatalogue,
) -> ValidatedGenerationPayload:
    return ValidatedGenerationPayload(
        3,
        status.value,
        answer,
        claims,
        catalogue.request_id,
        catalogue.configuration_version_id,
        catalogue.generation_profile_id,
        catalogue.policy_ref,
        catalogue.policy_digest,
        catalogue.digest,
    )


def _check_context(
    catalogue: SourceValueCatalogue,
    profile: GenerationProfile,
    request_id: UUID,
    configuration_version_id: UUID,
) -> None:
    if (
        profile.response_schema_version != 3
        or profile.numeric_proof_policy != SOURCE_NUMERIC_PROOF_V1
        or catalogue.request_id != request_id
        or catalogue.configuration_version_id != configuration_version_id
        or catalogue.generation_profile_id != profile.profile_id
        or catalogue.policy_ref != SOURCE_NUMERIC_PROOF_V1.ref
        or catalogue.policy_digest != SOURCE_NUMERIC_PROOF_V1.digest
    ):
        raise _Rejected("calculation_operand_not_supported")


def validated_numeric_abstention(
    *,
    catalogue: SourceValueCatalogue,
    profile: GenerationProfile,
    request_id: UUID,
    configuration_version_id: UUID,
) -> ValidatedNumericGeneration:
    _check_context(catalogue, profile, request_id, configuration_version_id)
    status = GenerationStatus.INSUFFICIENT_EVIDENCE
    return ValidatedNumericGeneration(
        GenerationOutcome(status), _payload(status, None, (), catalogue), catalogue.evidence_ids
    )


class NumericProofValidator:
    def validate(
        self,
        draft: StructuredGeneration,
        *,
        evidence: tuple[GroundingEvidence, ...],
        catalogue: SourceValueCatalogue,
        profile: GenerationProfile,
        request_id: UUID,
        configuration_version_id: UUID,
    ) -> ValidatedNumericGeneration:
        try:
            _check_context(catalogue, profile, request_id, configuration_version_id)
            rebuilt = build_source_value_catalogue(
                evidence,
                request_id=request_id,
                configuration_version_id=configuration_version_id,
                profile=profile,
            )
            if rebuilt != catalogue:
                raise _Rejected("calculation_operand_not_supported")
            return self._validate(draft, evidence, catalogue)
        except ValueError as error:
            code = str(error)
            if code not in {
                "calculation_operand_not_supported",
                "calculation_result_span_invalid",
                "calculation_unit_not_supported",
                "calculation_result_mismatch",
                "calculation_limit_exceeded",
                "exact_value_not_supported",
                "claim_missing",
                "claim_citation_missing",
                "evidence_not_allowed",
                "evidence_provenance_incomplete",
                "structured_output_invalid",
            }:
                code = "structured_output_invalid"
            return ValidatedNumericGeneration(
                GenerationOutcome(
                    GenerationStatus.CITATION_VALIDATION_FAILED, reason_codes=(code,)
                ),
                None,
            )

    def _validate(
        self,
        draft: StructuredGeneration,
        evidence: tuple[GroundingEvidence, ...],
        catalogue: SourceValueCatalogue,
    ) -> ValidatedNumericGeneration:
        policy = SOURCE_NUMERIC_PROOF_V1
        if draft.schema_version != 3 or not draft.claims:
            raise _Rejected("claim_missing")
        if (
            len(draft.claims) > policy.max_claims
            or sum(len(c.calculations) for c in draft.claims) > policy.max_calculations
        ):
            raise _Rejected("calculation_limit_exceeded")
        allowed = {e.evidence_id: e for e in evidence}
        tokens = {t.token_id: t for t in catalogue.tokens}
        claims: list[ValidatedNumericClaim] = []
        citations: list[GeneratedCitation] = []
        for index, claim in enumerate(draft.claims):
            if not claim.evidence_ids or len(set(claim.evidence_ids)) != len(claim.evidence_ids):
                raise _Rejected("claim_citation_missing")
            if any(identity not in allowed for identity in claim.evidence_ids):
                raise _Rejected("evidence_not_allowed")
            cited = [allowed[identity] for identity in claim.evidence_ids]
            if any(e.projection_id is None or e.chunk_id is None for e in cited):
                raise _Rejected("evidence_provenance_incomplete")
            if (
                claim.text != claim.text.strip()
                or not claim.text
                or "\0" in claim.text
                or any(0xD800 <= ord(c) <= 0xDFFF for c in claim.text)
            ):
                raise _Rejected("structured_output_invalid")
            supported = {
                value
                for source in cited
                for occurrence in _VALUE.finditer(source.text)
                if occurrence.group("date") is not None
                or whole_numeric_occurrence(source.text, occurrence.start())
                for value in exact_values(occurrence.group())
            }
            occurrences = numeric_occurrences(claim.text, max_digits=policy.max_digits)
            if len(claim.calculations) > policy.max_calculations_per_claim:
                raise _Rejected("calculation_limit_exceeded")
            verified: list[VerifiedCalculation] = []
            spans: list[tuple[int, int]] = []
            for proof in claim.calculations:
                span = (proof.result_start, proof.result_end)
                if (
                    type(span[0]) is not int
                    or type(span[1]) is not int
                    or any(span[0] < end and start < span[1] for start, end in spans)
                ):
                    raise _Rejected("calculation_result_span_invalid")
                result = next((value for value in occurrences if value[:2] == span), None)
                if result is None:
                    raise _Rejected("calculation_result_span_invalid")
                if len(set(proof.operand_token_ids)) != len(proof.operand_token_ids):
                    raise _Rejected("calculation_operand_not_supported")
                operands = []
                for token_id in proof.operand_token_ids:
                    token = tokens.get(token_id)
                    if token is None or token.evidence_id not in claim.evidence_ids:
                        raise _Rejected("calculation_operand_not_supported")
                    operands.append(token)
                with localcontext(Context(prec=policy.precision)) as context:
                    for signal in (Inexact, Rounded, Overflow):
                        context.traps[signal] = True
                    try:
                        if proof.operation == "percentage_point_difference":
                            if (
                                len(operands) != 2
                                or any(t.unit != "%" for t in operands)
                                or result[2] != "%p"
                            ):
                                raise _Rejected("calculation_unit_not_supported")
                            calculated = operands[0].value - operands[1].value
                        elif proof.operation == "convert_krw_unit":
                            scales = {
                                "원": Decimal(1),
                                "만원": Decimal(10000),
                                "억원": Decimal(100000000),
                            }
                            if (
                                len(operands) != 1
                                or operands[0].unit not in scales
                                or result[2] not in scales
                            ):
                                raise _Rejected("calculation_unit_not_supported")
                            calculated = (
                                operands[0].value * scales[operands[0].unit] / scales[result[2]]
                            )
                        else:
                            raise _Rejected("calculation_unit_not_supported")
                    except DecimalException:
                        raise _Rejected("calculation_result_mismatch") from None
                if calculated != result[3]:
                    raise _Rejected("calculation_result_mismatch")
                sources = []
                for token in operands:
                    source = allowed[token.evidence_id]
                    if source.char_start + token.end > source.char_end:
                        raise _Rejected("evidence_provenance_incomplete")
                    sources.append(
                        VerifiedOperand(
                            source.evidence_id,
                            source.document_id,
                            source.asset_version_id,
                            source.projection_id,
                            source.chunk_id,
                            source.element_id,
                            token.start,
                            token.end,
                            source.char_start + token.start,
                            source.char_start + token.end,
                            source.page,
                            token.unit,
                        )
                    )
                verified.append(
                    VerifiedCalculation(
                        proof.operation, span[0], span[1], tuple(sources), policy.ref
                    )
                )
                spans.append(span)
            for occurrence in _VALUE.finditer(claim.text):
                if occurrence.group("number") is not None and not whole_numeric_occurrence(
                    claim.text, occurrence.start()
                ):
                    raise _Rejected("exact_value_not_supported")
                if (occurrence.start(), occurrence.end()) not in spans and not exact_values(
                    occurrence.group()
                ).issubset(supported):
                    raise _Rejected("exact_value_not_supported")
            claims.append(
                ValidatedNumericClaim(index, claim.text, claim.evidence_ids, tuple(verified))
            )
            citations.append(
                GeneratedCitation(index, claim.evidence_ids, claim.text, tuple(verified))
            )
        answer = " ".join(c.text for c in claims)
        return ValidatedNumericGeneration(
            GenerationOutcome(GenerationStatus.ANSWERED, answer, tuple(citations)),
            _payload(GenerationStatus.ANSWERED, answer, tuple(claims), catalogue),
            catalogue.evidence_ids,
        )
