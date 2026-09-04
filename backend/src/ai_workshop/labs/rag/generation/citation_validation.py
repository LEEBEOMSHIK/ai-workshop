import re

from ai_workshop.labs.rag.generation.domain import (
    GeneratedCitation,
    GenerationOutcome,
    GenerationStatus,
    GroundingEvidence,
    StructuredGeneration,
)

_EXACT_VALUE = re.compile(
    r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일|"
    r"\d{4}-\d{1,2}-\d{1,2}|"
    r"\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:%|퍼센트|원|만원|억원|년|개월|회|명)"
)


class CitationValidator:
    def validate(
        self,
        draft: StructuredGeneration,
        *,
        allowed_evidence: tuple[GroundingEvidence, ...],
    ) -> GenerationOutcome:
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
            exact_values = set(_EXACT_VALUE.findall(claim.text))
            supported_values = {
                value
                for item in cited
                for value in _EXACT_VALUE.findall(item.text)
            }
            if not exact_values.issubset(supported_values):
                return _failed("exact_value_not_supported")
            citations.append(
                GeneratedCitation(
                    claim_index=claim_index,
                    evidence_ids=claim.evidence_ids,
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
