"""Bounded, source-preserving context selection for grounded generation."""

from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID

from ai_workshop.labs.rag.documents.domain import EvidenceUnit
from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingPort,
    EmbeddingRuntimeUnavailableError,
)
from ai_workshop.labs.rag.highlighting.domain import (
    AnswerPolicy,
    EvidenceSelection,
    EvidenceSource,
)
from ai_workshop.labs.rag.highlighting.service import (
    _cosine_similarity,
    _provenance_warnings,
    find_keyword_highlights,
)
from ai_workshop.labs.rag.highlighting.structural_context import inspect_grid_candidate
from ai_workshop.labs.rag.highlighting.table_context import payment_table_units
from ai_workshop.labs.rag.models.budget_trace import BudgetConstraint, BudgetTrace
from ai_workshop.labs.rag.models.context_evidence import EvidenceBudget as EvidenceBudget


@dataclass(frozen=True, slots=True)
class ContextGroup:
    source: EvidenceSource
    units: tuple[EvidenceUnit, ...]
    keyword_coverage: float
    semantic_score: float | None


@dataclass(frozen=True, slots=True)
class CandidateDiagnostic:
    chunk_id: UUID
    evidence_id: UUID | None
    keyword_coverage: float | None
    semantic_score: float | None
    eligible: bool
    selected: bool
    reason: str
    budget_trace: BudgetTrace | None = None
    structure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ContextSelection:
    groups: tuple[ContextGroup, ...]
    diagnostics: tuple[CandidateDiagnostic, ...]
    blocked_reason: str | None = None
    diagnostic_warning: str | None = None
    observations: tuple[CandidateDiagnostic, ...] = ()


def select_context(
    *, query: str, sources: tuple[EvidenceSource, ...], extractive: EvidenceSelection,
    policy: AnswerPolicy, budget: EvidenceBudget, embedding: EmbeddingPort,
    include_diagnostics: bool,
    table_strategy: Literal["payment-v1", "structure-v1"] = "payment-v1",
) -> ContextSelection:
    if table_strategy not in {"payment-v1", "structure-v1"}:
        raise ValueError("Unknown context table strategy.")
    groups: list[ContextGroup] = []
    seen: dict[UUID, tuple[UUID, UUID, EvidenceUnit]] = {}
    seen_chunks: dict[UUID, EvidenceSource] = {}
    diagnostics: list[CandidateDiagnostic] = []
    diagnostic_warnings: list[str] = []
    for source in sources:
        previous = seen_chunks.get(source.chunk.chunk_id)
        if previous is not None:
            if previous != source:
                raise ValueError("Conflicting context source identity.")
            continue
        seen_chunks[source.chunk.chunk_id] = source
        valid: list[EvidenceUnit] = []
        for unit in sorted(source.chunk.evidence_units,
                           key=lambda item: (item.ordinal, item.location.char_start)):
            identity = (source.document_id, source.chunk.asset_version_id, unit)
            if unit.id in seen and seen[unit.id] != identity:
                raise ValueError("Conflicting evidence identity.")
            if unit.id in seen:
                continue
            seen[unit.id] = identity
            if _provenance_warnings(source, unit) or not unit.text.strip():
                # Do not return even IDs for malformed source units in diagnostics.
                continue
            valid.append(unit)
        if valid:
            body = "\n".join(unit.text for unit in valid)
            coverage = find_keyword_highlights(
                query=query, text=body, location=valid[0].location,
                evidence_unit_id=valid[0].id,
            ).coverage
            groups.append(ContextGroup(source, tuple(valid), coverage, None))
        elif table_strategy == "structure-v1":
            warning = "structural_context_incomplete_source"
            if warning not in diagnostic_warnings:
                # No malformed evidence IDs/text, including when all groups vanish.
                diagnostic_warnings.append(warning)
    if not groups:
        return ContextSelection((), (), diagnostic_warning=",".join(diagnostic_warnings) or None)
    query_vector = embedding.encode_query(query)
    texts = [_context_text(group) for group in groups]
    vectors = embedding.encode_documents(texts)
    if len(vectors) != len(groups):
        raise ValueError("Context embedding count must match groups.")
    groups = [replace(group, semantic_score=_cosine_similarity(query_vector, vector))
              for group, vector in zip(groups, vectors, strict=True)]
    anchors = (*((extractive.answer,) if extractive.answer else ()), *extractive.conflicts)
    anchor_ids = {answer.evidence.id for answer in anchors}
    qualified_ids = anchor_ids | {answer.evidence.id for answer in extractive.candidates}
    eligible: list[ContextGroup] = []
    structured_ids: set[UUID] = set()
    grid_ids: set[UUID] = set()
    structure_reasons: dict[UUID, str] = {}
    for group in groups:
        if table_strategy == "structure-v1":
            candidate = inspect_grid_candidate(query, group.source, group.units)
            structure_reasons[group.source.chunk.chunk_id] = candidate.reason
            if candidate.eligible:
                eligible.append(group)
                grid_ids.add(group.source.chunk.chunk_id)
                continue
        projected = (payment_table_units(query, group.source, group.units)
                     if table_strategy == "payment-v1" else None)
        if projected is not None:
            removed_ids = {u.id for u in group.units} - {u.id for u in projected}
            # Never discard already-qualified evidence, including conflict anchors.
            if not removed_ids & qualified_ids:
                eligible.append(replace(group, units=projected))
                structured_ids.add(group.source.chunk.chunk_id)
                continue
        if (any(unit.id in qualified_ids for unit in group.units)
                or group.keyword_coverage >= policy.min_keyword_coverage
                and group.keyword_coverage > 0
                or group.semantic_score is not None
                and group.semantic_score >= policy.min_semantic_score):
            eligible.append(group)
    eligible.sort(key=lambda group: (
        0 if group.keyword_coverage >= policy.min_keyword_coverage else 1,
        -(group.keyword_coverage if group.keyword_coverage >= policy.min_keyword_coverage
          else group.semantic_score or 0),
        -group.source.fused_score, str(group.source.chunk.chunk_id),
    ))
    chosen: list[ContextGroup] = []
    count = characters = 0
    budget_traces: dict[UUID, BudgetTrace] = {}
    for group in eligible:
        size = sum(len(unit.text) for unit in group.units)
        violations: list[BudgetConstraint] = []
        if len(chosen) >= budget.max_groups:
            violations.append("groups")
        if count + len(group.units) > budget.max_units:
            violations.append("units")
        if characters + size > budget.max_characters:
            violations.append("characters")
        budget_traces[group.source.chunk.chunk_id] = BudgetTrace(
            incoming_units=len(group.units), incoming_characters=size,
            before_groups=len(chosen), before_units=count, before_characters=characters,
            group_limit=budget.max_groups, unit_limit=budget.max_units,
            character_limit=budget.max_characters, violated=tuple(violations),
        )
        if violations:
            continue
        chosen.append(group)
        count += len(group.units)
        characters += size
    chosen_ids = {unit.id for group in chosen for unit in group.units}
    blocked = None
    if extractive.conflicts and not anchor_ids <= chosen_ids:
        chosen = []
        chosen_ids = set()
        blocked = "conflict_context_budget_exceeded"
    eligible_chunks = {group.source.chunk.chunk_id for group in eligible}
    chosen_chunks = {group.source.chunk.chunk_id for group in chosen}

    def group_reason(group: ContextGroup) -> str:
        chunk_id = group.source.chunk.chunk_id
        if blocked:
            return blocked
        if chunk_id in chosen_chunks:
            if chunk_id in grid_ids:
                return "structural_grid_selected"
            return "structured_table_selected" if chunk_id in structured_ids else "selected"
        return "budget_exceeded" if chunk_id in eligible_chunks else "below_threshold"

    observations = tuple(CandidateDiagnostic(
        group.source.chunk.chunk_id, None, group.keyword_coverage, group.semantic_score,
        group.source.chunk.chunk_id in eligible_chunks,
        group.source.chunk.chunk_id in chosen_chunks, group_reason(group),
        budget_traces.get(group.source.chunk.chunk_id),
        structure_reason=structure_reasons.get(group.source.chunk.chunk_id),
    ) for group in groups)
    if include_diagnostics:
        unit_pairs = [(group, unit) for group in groups for unit in group.units]
        unit_scores: list[float | None]
        try:
            unit_vectors = embedding.encode_documents([unit.text for _, unit in unit_pairs])
            if len(unit_vectors) != len(unit_pairs):
                raise ValueError("Diagnostic embedding count must match units.")
            unit_scores = [_cosine_similarity(query_vector, vector) for vector in unit_vectors]
        except (EmbeddingRuntimeUnavailableError, ValueError):
            diagnostic_warnings.append("diagnostic_embedding_unavailable")
            unit_scores = [None] * len(unit_pairs)
        for group in groups:
            selected = group.source.chunk.chunk_id in chosen_chunks
            qualifies = group.source.chunk.chunk_id in eligible_chunks
            reason = group_reason(group)
            diagnostics.append(CandidateDiagnostic(
                group.source.chunk.chunk_id, None, group.keyword_coverage,
                group.semantic_score, qualifies, selected, reason,
                budget_traces.get(group.source.chunk.chunk_id),
                structure_reason=structure_reasons.get(group.source.chunk.chunk_id),
            ))
        for (group, unit), score in zip(unit_pairs, unit_scores, strict=True):
            coverage = find_keyword_highlights(query=query, text=unit.text,
                location=unit.location, evidence_unit_id=unit.id).coverage
            qualifies = unit.id in qualified_ids or (
                coverage > 0 and coverage >= policy.min_keyword_coverage
            )
            qualifies = qualifies or (score is not None and score >= policy.min_semantic_score)
            selected = unit.id in chosen_ids
            diagnostics.append(CandidateDiagnostic(
                group.source.chunk.chunk_id, unit.id, coverage, score,
                qualifies, selected, "context_member" if selected and not qualifies else
                "selected" if selected else "not_transmitted",
            ))
    return ContextSelection(
        tuple(chosen), tuple(diagnostics), blocked,
        ",".join(diagnostic_warnings) or None, observations,
    )


def _context_text(group: ContextGroup) -> str:
    # Metadata guides relevance, but only original units become citable evidence.
    return "\n".join((*group.source.chunk.section_path,
                       *(unit.text for unit in group.units)))
