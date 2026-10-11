from ai_workshop.labs.rag.generation.domain import (
    GeneratedCitation,
    GenerationOutcome,
    GenerationStatus,
    GroundingEvidence,
    StructuredGeneration,
)
from ai_workshop.labs.rag.generation.exact_values import exact_values


class CitationValidator:
    def validate(
        self,
        draft: StructuredGeneration,
        *,
        allowed_evidence: tuple[GroundingEvidence, ...],
    ) -> GenerationOutcome:
        if draft.schema_version not in (1, 2) or any(claim.calculations for claim in draft.claims):
            return _failed("structured_output_invalid")
        allowed = {item.evidence_id: item for item in allowed_evidence}
        if not draft.claims:
            return _failed("claim_missing")

        citations: list[GeneratedCitation] = []
        for claim_index, claim in enumerate(draft.claims):
            if not claim.evidence_ids:
                return _failed("claim_citation_missing")
            cited = []
            for evidence_id in claim.evidence_ids:
                item = allowed.get(evidence_id)
                if item is None:
                    return _failed("evidence_not_allowed")
                if item.projection_id is None or item.chunk_id is None:
                    return _failed("evidence_provenance_incomplete")
                cited.append(item)
            claimed_values = exact_values(claim.text)
            supported_values = {value for item in cited for value in exact_values(item.text)}
            if not claimed_values.issubset(supported_values):
                return _failed("exact_value_not_supported")
            citations.append(
                GeneratedCitation(
                    claim_index=claim_index,
                    evidence_ids=claim.evidence_ids,
                    claim_text=claim.text,
                )
            )

        return GenerationOutcome(
            status=GenerationStatus.ANSWERED,
            text=" ".join(claim.text for claim in draft.claims),
            citations=tuple(citations),
        )


def _failed(reason_code: str) -> GenerationOutcome:
    return GenerationOutcome(
        status=GenerationStatus.CITATION_VALIDATION_FAILED,
        reason_codes=(reason_code,),
    )
