import json

from ai_workshop.labs.rag.executions.domain import (
    MAX_RECORDED_CANDIDATES,
    CandidateObservation,
    SelectionObservation,
)
from ai_workshop.labs.rag.generation.domain import GroundingEvidence
from ai_workshop.labs.rag.generation.evidence_payload import serialize_evidence
from ai_workshop.labs.rag.highlighting.context import ContextSelection
from ai_workshop.labs.rag.highlighting.domain import EvidenceSource
from ai_workshop.labs.rag.retrieval.domain import FusedHit
from ai_workshop.labs.rag.search.configuration_port import ResolvedSearchConfiguration


def selection_observation(
    sources: tuple[EvidenceSource, ...],
    hits: tuple[FusedHit, ...],
    context: ContextSelection | None,
    configuration: ResolvedSearchConfiguration,
    selected_count: int,
    evidence: tuple[GroundingEvidence, ...],
    top_k: int,
) -> SelectionObservation:
    by_source = {s.chunk.chunk_id: s for s in sources}
    by_hit = {h.chunk_id: (rank, h) for rank, h in enumerate(hits, 1)}
    items = context.observations if context else ()
    candidates = []
    for item in items[: min(top_k, MAX_RECORDED_CANDIDATES)]:
        source = by_source[item.chunk_id]
        rank, hit = by_hit[item.chunk_id]
        unit = source.chunk.evidence_units[0]
        candidates.append(
            CandidateObservation(
                document_id=source.document_id,
                chunk_id=source.chunk.chunk_id,
                asset_version_id=source.chunk.asset_version_id,
                projection_id=source.chunk.projection_id,
                evidence_unit_id=unit.id,
                page=unit.location.page,
                sparse_rank=hit.sparse_rank,
                sparse_score=hit.sparse_score,
                dense_rank=hit.dense_rank,
                dense_score=hit.dense_score,
                fused_rank=rank,
                fused_score=hit.score,
                semantic_score=item.semantic_score,
                keyword_coverage=item.keyword_coverage,
                selected=item.selected,
                reason=item.reason,
            )
        )
    profile = configuration.generation_profile
    budget = profile.evidence_budget if profile else None
    return SelectionObservation(
        candidates=candidates,
        candidate_count=len(items),
        truncated=len(candidates) < len(items),
        selected_count=selected_count,
        min_semantic_score=configuration.answer_policy.min_semantic_score
        if configuration.answer_policy
        else None,
        min_keyword_coverage=configuration.answer_policy.min_keyword_coverage
        if configuration.answer_policy
        else None,
        group_limit=budget.max_groups if budget else None,
        unit_limit=budget.max_units if budget else None,
        character_limit=budget.max_characters if budget else None,
        serialized_bytes=len(json.dumps(serialize_evidence(evidence), ensure_ascii=False).encode()),
        configuration_version_id=configuration.configuration_version_id,
        indexing_profile_id=configuration.indexing_profile_id,
        retrieval_profile_id=configuration.retrieval_profile.id,
        generation_profile_id=profile.profile_id if profile else None,
        answer_policy_version_id=configuration.answer_policy_version_id,
    )
