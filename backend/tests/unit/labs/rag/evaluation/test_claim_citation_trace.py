import hashlib
import json
from uuid import UUID

from ai_workshop.labs.rag.evaluation.generative import (
    ClaimCitation,
    GenerativeObservation,
    PrivateGenerativeResult,
)
from ai_workshop.labs.rag.generation.citation_validation import CitationValidator
from ai_workshop.labs.rag.generation.domain import GeneratedClaim, StructuredGeneration
from ai_workshop.labs.rag.search.schemas import GeneratedCitationResponse
from tests.unit.labs.rag.generation.test_citation_validation import evidence


def test_validated_claims_keep_original_boundaries_instead_of_sentence_splitting():
    first = "No. A missing input cannot be estimated. Ask the operations team"
    second = "and record the pending status. Keep the source condition."
    identifier = UUID(int=2)
    outcome = CitationValidator().validate(
        StructuredGeneration(2, (
            GeneratedClaim(first, (identifier,)), GeneratedClaim(second, (identifier,)),
        )),
        allowed_evidence=(evidence(evidence_id=identifier),),
    )
    assert outcome.text == first + " " + second
    assert [citation.claim_text for citation in outcome.citations] == [first, second]
    assert [citation.claim_index for citation in outcome.citations] == [0, 1]


def test_legacy_private_result_keeps_exact_bytes_digest_and_unknown_claim_text():
    result = PrivateGenerativeResult(
        observation=GenerativeObservation(execution_id=UUID(int=1)),
        answer="One sentence. Another sentence.",
        citations=(ClaimCitation(claim_index=0, evidence_ids=(UUID(int=2),)),),
    )
    original = result.model_dump(mode="json")
    original["citations"] = [{
        "claim_index": 0, "evidence_ids": [str(UUID(int=2))],
    }]
    encoded = json.dumps(original, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    loaded = PrivateGenerativeResult.model_validate_json(encoded)
    assert loaded.model_dump(mode="json") == original
    assert loaded.digest() == hashlib.sha256(encoded.encode()).hexdigest()
    assert loaded.citations[0].claim_text is None
    assert "claim_text" not in loaded.model_dump(mode="json")["citations"][0]


def test_same_joined_answer_with_different_claim_boundaries_has_different_digest():
    observation = GenerativeObservation(execution_id=UUID(int=1))
    shared = {"observation": observation, "answer": "A. B. C."}
    left = PrivateGenerativeResult(**shared, citations=(
        ClaimCitation(claim_index=0, evidence_ids=(UUID(int=2),), claim_text="A. B."),
        ClaimCitation(claim_index=1, evidence_ids=(UUID(int=3),), claim_text="C."),
    ))
    right = PrivateGenerativeResult(**shared, citations=(
        ClaimCitation(claim_index=0, evidence_ids=(UUID(int=2),), claim_text="A."),
        ClaimCitation(claim_index=1, evidence_ids=(UUID(int=3),), claim_text="B. C."),
    ))
    assert left.answer == right.answer
    assert left.digest() != right.digest()
    reloaded = PrivateGenerativeResult.model_validate_json(left.model_dump_json())
    assert reloaded.digest() == left.digest()


def test_unanswered_result_does_not_invent_claim_text():
    result = PrivateGenerativeResult(
        observation=GenerativeObservation(
            execution_id=UUID(int=1), generation_status="insufficient_evidence",
        ),
    )
    assert result.answer is None and result.citations == ()


def test_legacy_search_citation_omits_unknown_text_instead_of_rewriting_shape():
    legacy = {"claim_index": 0, "evidence_ids": [str(UUID(int=2))]}
    loaded = GeneratedCitationResponse.model_validate(legacy)
    assert loaded.claim_text is None
    assert loaded.model_dump(mode="json") == legacy
