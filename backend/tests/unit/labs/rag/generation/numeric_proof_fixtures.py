from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from ai_workshop.labs.rag.generation.numeric_proof_types import SourceValueCatalogue

from ai_workshop.labs.rag.generation.domain import (
    ContextPolicy,
    GenerationProfile,
    GroundingEvidence,
)


def numeric_profile() -> GenerationProfile:
    from ai_workshop.labs.rag.models.numeric_proof_policy import resolve_numeric_proof_policy

    policy = resolve_numeric_proof_policy(
        {
            "prompt_ref": "rag-codex-answer-v6",
            "generation": {
                "response_schema_version": 3,
                "numeric_proof_policy_ref": "source-numeric-proof-v1",
            },
        }
    )
    return GenerationProfile(
        profile_id=UUID(int=10),
        profile_name="synthetic numeric",
        profile_version=1,
        model_id=UUID(int=11),
        model_name="synthetic",
        model_version=1,
        runtime_model="synthetic",
        prompt_ref="rag-codex-answer-v6",
        context_prompt_ref="rag-codex-contextualize-v1",
        context_policy=ContextPolicy(4, 512),
        timeout_seconds=30,
        max_output_tokens=512,
        temperature=0,
        response_schema_version=3,
        numeric_proof_policy=policy,
    )


def numeric_evidence(text: str, *, identity: int = 100) -> GroundingEvidence:
    return GroundingEvidence(
        evidence_id=UUID(int=identity),
        text=text,
        document_id=UUID(int=identity + 1000),
        asset_version_id=UUID(int=identity + 2000),
        projection_id=UUID(int=identity + 3000),
        chunk_id=UUID(int=identity + 4000),
        element_id=UUID(int=identity + 5000),
        page=1,
        char_start=10,
        char_end=10 + len(text),
        bbox=None,
    )


@dataclass(frozen=True)
class NumericFixture:
    profile: GenerationProfile
    evidence: tuple[GroundingEvidence, ...]
    catalogue: SourceValueCatalogue


def numeric_fixture(
    source_texts: tuple[str, ...], *, request_id: UUID | None = None
) -> NumericFixture:
    from ai_workshop.labs.rag.generation.numeric_catalogue import build_source_value_catalogue

    profile = numeric_profile()
    evidence = tuple(
        numeric_evidence(value, identity=100 + n) for n, value in enumerate(source_texts)
    )
    catalogue = build_source_value_catalogue(
        evidence,
        request_id=request_id or uuid4(),
        configuration_version_id=UUID(int=20),
        profile=profile,
    )
    return NumericFixture(profile, evidence, catalogue)


def legacy_profile() -> GenerationProfile:
    return replace(
        numeric_profile(),
        response_schema_version=2,
        prompt_ref="rag-codex-answer-v5",
        numeric_proof_policy=None,
    )
