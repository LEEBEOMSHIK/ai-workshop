from dataclasses import asdict
from uuid import UUID

from ai_workshop.labs.rag.evaluation.generative import (
    ClaimCitation,
    GenerativeObservation,
    PrivateGenerativeResult,
)
from ai_workshop.labs.rag.generation.domain import GeneratedClaim, StructuredGeneration
from ai_workshop.labs.rag.generation.numeric_proof_serialization import numeric_payload_digest
from ai_workshop.labs.rag.generation.numeric_proof_types import (
    CalculationProposal,
    NumericValidationBinding,
)
from ai_workshop.labs.rag.generation.numeric_validation import NumericProofValidator
from tests.unit.labs.rag.generation.numeric_proof_fixtures import numeric_fixture


def test_numeric_proof_roundtrip_and_digest_binding():
    from ai_workshop.labs.rag.generation.numeric_proof_schemas import (
        NumericValidationBindingView,
        VerifiedCalculationView,
        payload_from_views,
    )

    fixture = numeric_fixture(("0.30%", "0.20%"))
    claim = GeneratedClaim(
        "😀 차이 0.10%p",
        tuple(e.evidence_id for e in fixture.evidence),
        (
            CalculationProposal(
                "percentage_point_difference",
                tuple(t.token_id for t in fixture.catalogue.tokens),
                5,
                11,
            ),
        ),
    )
    validated = NumericProofValidator().validate(
        StructuredGeneration(3, (claim,)),
        evidence=fixture.evidence,
        catalogue=fixture.catalogue,
        profile=fixture.profile,
        request_id=fixture.catalogue.request_id,
        configuration_version_id=UUID(int=20),
    )
    assert validated.payload is not None
    payload = validated.payload
    binding = NumericValidationBinding(
        UUID(int=70),
        UUID(int=71),
        payload.request_id,
        UUID(int=20),
        fixture.profile.profile_id,
        3,
        payload.policy_ref,
        payload.policy_digest,
        payload.catalogue_digest,
        numeric_payload_digest(payload),
    )
    result = PrivateGenerativeResult(
        observation=GenerativeObservation(execution_id=UUID(int=72), generation_status="answered"),
        answer=payload.answer,
        citations=(
            ClaimCitation(
                claim_index=0,
                evidence_ids=claim.evidence_ids,
                claim_text=claim.text,
                calculations=tuple(
                    VerifiedCalculationView.model_validate(asdict(c))
                    for c in validated.outcome.citations[0].calculations
                ),
            ),
        ),
        numeric_validation=NumericValidationBindingView.model_validate(asdict(binding)),
    )
    restored = PrivateGenerativeResult.model_validate_json(result.model_dump_json())
    rebuilt = payload_from_views(
        status="answered",
        answer=restored.answer,
        claims=restored.citations,
        binding=restored.numeric_validation,
    )
    assert rebuilt == payload
    changed = restored.model_copy(
        update={"citations": (restored.citations[0].model_copy(update={"calculations": ()}),)}
    )
    assert changed.digest() != result.digest()


def test_legacy_absent_fields_keep_exact_bytes():
    original = {
        "observation": GenerativeObservation(execution_id=UUID(int=72)).model_dump(mode="json"),
        "answer": "old",
        "citations": [{"claim_index": 0, "evidence_ids": [str(UUID(int=73))]}],
        "evidence": [],
    }
    assert PrivateGenerativeResult.model_validate(original).model_dump(mode="json") == original


def test_expected_profile_comes_from_frozen_candidate_not_result_binding():
    from ai_workshop.labs.rag.evaluation.generative_read import frozen_generation_profile_id

    snapshot = {
        "candidates": [
            {
                "configuration_version_id": str(UUID(int=20)),
                "component_snapshot": {
                    "profiles": [
                        {"id": str(UUID(int=10)), "kind": "generation"},
                        {"id": str(UUID(int=99)), "kind": "indexing"},
                    ]
                },
            }
        ]
    }
    assert frozen_generation_profile_id(snapshot, UUID(int=20)) == UUID(int=10)
