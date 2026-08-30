import math
import re
import unicodedata
from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.embeddings.contracts import EmbeddingPort
from ai_workshop.labs.rag.highlighting.domain import (
    AnswerPolicy,
    AnswerStatus,
    ConflictState,
    EvidenceAnswer,
    EvidenceSelection,
    EvidenceSource,
    HighlightKind,
    HighlightSpan,
    KeywordHighlightResult,
)

_TOKEN_PATTERN = re.compile(r"\w+|[%]+", re.UNICODE)
_NUMERIC_VALUE_PATTERN = re.compile(
    r"([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
)
_RECOGNIZED_NUMERIC_UNITS = ("퍼센트", "억원", "만원", "개월", "%", "원", "년", "일")
_NUMERIC_UNIT_SUFFIXES = (
    "입니다",
    "으로",
    "에서",
    "부터",
    "까지",
    "보다",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "에",
    "로",
)
_POLARITY_PATTERNS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "possibility",
        (r"(?<!불)가능", r"할\s*수\s*있", r"\bcan\b"),
        (r"불가능", r"가능하지\s*않", r"할\s*수\s*없", r"\bcannot\b"),
    ),
    (
        "permission",
        (r"허용", r"\ballowed\b", r"\bpermitted\b"),
        (r"금지", r"허용되지\s*않", r"\bnot\s+allowed\b", r"\bprohibited\b"),
    ),
)


def _normalize_with_original_offsets(
    text: str,
) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    normalized = ""
    starts: list[int] = []
    ends: list[int] = []
    for source_end in range(1, len(text) + 1):
        updated = unicodedata.normalize("NFKC", text[:source_end]).casefold()
        if updated == normalized:
            if ends:
                ends[-1] = source_end
            continue
        common_prefix = 0
        while (
            common_prefix < len(normalized)
            and common_prefix < len(updated)
            and normalized[common_prefix] == updated[common_prefix]
        ):
            common_prefix += 1
        changed_start = (
            starts[common_prefix]
            if common_prefix < len(starts)
            else source_end - 1
        )
        replacement_length = len(updated) - common_prefix
        starts = starts[:common_prefix] + [changed_start] * replacement_length
        ends = ends[:common_prefix] + [source_end] * replacement_length
        normalized = updated

    collapsed: list[str] = []
    collapsed_starts: list[int] = []
    collapsed_ends: list[int] = []
    for character, start, end in zip(normalized, starts, ends, strict=True):
        if character.isspace():
            if collapsed and collapsed[-1] == " ":
                collapsed_ends[-1] = end
                continue
            collapsed.append(" ")
        else:
            collapsed.append(character)
        collapsed_starts.append(start)
        collapsed_ends.append(end)
    return "".join(collapsed), tuple(collapsed_starts), tuple(collapsed_ends)


def _query_terms(query: str) -> tuple[str, ...]:
    normalized, _, _ = _normalize_with_original_offsets(query)
    return tuple(dict.fromkeys(_TOKEN_PATTERN.findall(normalized)))


def find_keyword_highlights(
    *,
    query: str,
    text: str,
    location: SourceLocation,
    evidence_unit_id: UUID,
) -> KeywordHighlightResult:
    terms = _query_terms(query)
    if not terms:
        return KeywordHighlightResult(0.0, ())
    normalized_text, original_starts, original_ends = _normalize_with_original_offsets(
        text
    )
    matched_terms = 0
    spans: list[HighlightSpan] = []
    for term in terms:
        position = 0
        term_matched = False
        while True:
            start = normalized_text.find(term, position)
            if start < 0:
                break
            end = start + len(term)
            original_start = original_starts[start]
            original_end = original_ends[end - 1]
            absolute_start = location.char_start + original_start
            absolute_end = location.char_start + original_end
            is_whole_unit = original_start == 0 and original_end == len(text)
            bbox = location.bbox if is_whole_unit else None
            warnings = (
                ("pdf_keyword_bbox_unavailable",)
                if location.bbox is not None and not is_whole_unit
                else ()
            )
            spans.append(
                HighlightSpan(
                    kind=HighlightKind.KEYWORD,
                    evidence_unit_id=evidence_unit_id,
                    text=text[original_start:original_end],
                    char_start=absolute_start,
                    char_end=absolute_end,
                    page=location.page,
                    bbox=bbox,
                    warnings=warnings,
                )
            )
            term_matched = True
            position = end
        matched_terms += int(term_matched)
    spans.sort(key=lambda item: (item.char_start, item.char_end, item.text))
    return KeywordHighlightResult(matched_terms / len(terms), tuple(spans))


def semantic_highlight(evidence: EvidenceUnit, *, score: float) -> HighlightSpan:
    warnings: tuple[str, ...] = ()
    if evidence.location.page is not None and evidence.location.bbox is None:
        warnings = ("pdf_bbox_unavailable",)
    elif evidence.location.page is None and evidence.location.bbox is not None:
        warnings = ("page_number_unavailable",)
    return HighlightSpan(
        kind=HighlightKind.SEMANTIC,
        evidence_unit_id=evidence.id,
        text=evidence.text,
        char_start=evidence.location.char_start,
        char_end=evidence.location.char_end,
        page=evidence.location.page,
        bbox=evidence.location.bbox,
        score=score,
        warnings=warnings,
    )


class EvidenceSelector:
    def __init__(self, embedding: EmbeddingPort) -> None:
        self.embedding = embedding

    def select(
        self,
        *,
        query: str,
        sources: tuple[EvidenceSource, ...],
        policy: AnswerPolicy,
    ) -> EvidenceSelection:
        if policy.require_complete_provenance is not True:
            raise ValueError("The extractive V1 policy requires complete provenance.")
        candidates = tuple(
            (source, evidence, _provenance_warnings(source, evidence))
            for source in sources
            for evidence in source.chunk.evidence_units
        )
        eligible_items: list[tuple[EvidenceSource, EvidenceUnit]] = []
        seen_evidence_units: set[UUID] = set()
        for source, evidence, warnings in candidates:
            if warnings or evidence.id in seen_evidence_units:
                continue
            seen_evidence_units.add(evidence.id)
            eligible_items.append((source, evidence))
        eligible = tuple(eligible_items)
        selection_warnings = tuple(
            dict.fromkeys(
                warning
                for _, _, warnings in candidates
                for warning in warnings
            )
        )
        keyword_answers = self._keyword_answers(query, eligible, policy)
        keyword_evidence_ids = frozenset(
            answer.evidence.id for answer in keyword_answers
        )
        semantic_answers = self._semantic_answers(
            query,
            tuple(
                item for item in eligible if item[1].id not in keyword_evidence_ids
            ),
            policy,
        )
        answers = (*keyword_answers, *semantic_answers)
        if not answers:
            return EvidenceSelection(
                status=AnswerStatus.INSUFFICIENT_EVIDENCE,
                answer=None,
                conflict_state=ConflictState.NONE,
                conflicts=(),
                warnings=selection_warnings,
            )

        primary = answers[0]
        conflict_documents: set[UUID] = set()
        conflicts: list[EvidenceAnswer] = []
        for answer in answers[1:]:
            document_id = answer.source.document_id
            if (
                document_id == primary.source.document_id
                or document_id in conflict_documents
            ):
                continue
            if _directly_incompatible(query, primary, answer):
                conflicts.append(answer)
                conflict_documents.add(document_id)
        conflict_state = (
            ConflictState.SEPARATE_SOURCES if conflicts else ConflictState.NONE
        )
        return EvidenceSelection(
            status=AnswerStatus.SUPPORTED,
            answer=primary,
            conflict_state=conflict_state,
            conflicts=tuple(conflicts),
            warnings=selection_warnings,
        )

    @staticmethod
    def _keyword_answers(
        query: str,
        eligible: tuple[tuple[EvidenceSource, EvidenceUnit], ...],
        policy: AnswerPolicy,
    ) -> tuple[EvidenceAnswer, ...]:
        answers: list[EvidenceAnswer] = []
        for source, evidence in eligible:
            result = find_keyword_highlights(
                query=query,
                text=evidence.text,
                location=evidence.location,
                evidence_unit_id=evidence.id,
            )
            if not result.highlights or result.coverage < policy.min_keyword_coverage:
                continue
            answers.append(
                EvidenceAnswer(
                    source=source,
                    evidence=evidence,
                    excerpt=evidence.text,
                    highlights=result.highlights,
                    keyword_coverage=result.coverage,
                    semantic_score=None,
                    warnings=_provenance_warnings(source, evidence),
                )
            )
        return tuple(answers)

    def _semantic_answers(
        self,
        query: str,
        eligible: tuple[tuple[EvidenceSource, EvidenceUnit], ...],
        policy: AnswerPolicy,
    ) -> tuple[EvidenceAnswer, ...]:
        if not eligible:
            return ()
        query_vector = self.embedding.encode_query(query)
        document_vectors = self.embedding.encode_documents(
            [evidence.text for _, evidence in eligible]
        )
        if len(document_vectors) != len(eligible):
            raise ValueError("Evidence embedding count must match evidence units.")
        answers: list[EvidenceAnswer] = []
        for (source, evidence), vector in zip(eligible, document_vectors, strict=True):
            score = _cosine_similarity(query_vector, vector)
            if score < policy.min_semantic_score:
                continue
            answers.append(
                EvidenceAnswer(
                    source=source,
                    evidence=evidence,
                    excerpt=evidence.text,
                    highlights=(semantic_highlight(evidence, score=score),),
                    keyword_coverage=None,
                    semantic_score=score,
                    warnings=_provenance_warnings(source, evidence),
                )
            )
        answers.sort(
            key=lambda answer: (
                answer.semantic_score if answer.semantic_score is not None else -1.0,
                answer.source.fused_score,
            ),
            reverse=True,
        )
        return tuple(answers)


def _provenance_warnings(
    source: EvidenceSource,
    evidence: EvidenceUnit,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if evidence.chunk_id != source.chunk.chunk_id:
        warnings.append("chunk_provenance_incomplete")
    if evidence.projection_id != source.chunk.projection_id:
        warnings.append("projection_provenance_incomplete")
    if evidence.location.char_end <= evidence.location.char_start:
        warnings.append("text_offsets_incomplete")
    if source.media_type == "application/pdf":
        if evidence.location.page is None:
            warnings.append("pdf_page_incomplete")
        if evidence.location.bbox is None:
            warnings.append("pdf_bbox_incomplete")
    elif evidence.location.bbox is not None and evidence.location.page is None:
        warnings.append("page_number_incomplete")
    return tuple(warnings)


def _directly_incompatible(
    query: str,
    left: EvidenceAnswer,
    right: EvidenceAnswer,
) -> bool:
    if not _same_claim_key(query, left.excerpt, right.excerpt):
        return False
    left_number = _single_numeric_claim(left.excerpt)
    right_number = _single_numeric_claim(right.excerpt)
    if (
        left_number is not None
        and right_number is not None
        and bool(left_number[1])
        and left_number[1] == right_number[1]
        and left_number[0] != right_number[0]
    ):
        return True
    left_polarity = _explicit_polarity(left.excerpt)
    right_polarity = _explicit_polarity(right.excerpt)
    return (
        left_polarity is not None
        and right_polarity is not None
        and left_polarity[0] == right_polarity[0]
        and left_polarity[1] is not right_polarity[1]
    )


def _same_claim_key(query: str, left: str, right: str) -> bool:
    left_normalized, _, _ = _normalize_with_original_offsets(left)
    right_normalized, _, _ = _normalize_with_original_offsets(right)
    subject_terms = tuple(
        term
        for term in _query_terms(query)
        if len(term) >= 2
        and not any(character.isdigit() for character in term)
    )
    return any(
        f"{first} {second}" in left_normalized
        and f"{first} {second}" in right_normalized
        for first, second in zip(subject_terms, subject_terms[1:], strict=False)
    )


def _single_numeric_claim(text: str) -> tuple[Decimal, str] | None:
    normalized, _, _ = _normalize_with_original_offsets(text)
    matches = tuple(_NUMERIC_VALUE_PATTERN.finditer(normalized))
    if len(matches) != 1:
        return None
    match = matches[0]
    unit = _recognized_unit_after(normalized, match.end())
    if unit is None:
        return None
    normalized_unit = "%" if unit == "퍼센트" else unit
    return Decimal(match.group(1).replace(",", "")), normalized_unit


def _recognized_unit_after(text: str, value_end: int) -> str | None:
    unit_start = value_end
    while unit_start < len(text) and text[unit_start].isspace():
        unit_start += 1
    for unit in _RECOGNIZED_NUMERIC_UNITS:
        if not text.startswith(unit, unit_start):
            continue
        if _has_numeric_unit_boundary(text, unit_start + len(unit)):
            return unit
    return None


def _has_numeric_unit_boundary(text: str, unit_end: int) -> bool:
    if unit_end == len(text) or not _is_unicode_token_character(text[unit_end]):
        return True
    for suffix in _NUMERIC_UNIT_SUFFIXES:
        if not text.startswith(suffix, unit_end):
            continue
        suffix_end = unit_end + len(suffix)
        if suffix_end == len(text) or not _is_unicode_token_character(text[suffix_end]):
            return True
    return False


def _is_unicode_token_character(character: str) -> bool:
    category = unicodedata.category(character)
    return category[0] in {"L", "M", "N"} or category == "Pc"


def _explicit_polarity(text: str) -> tuple[str, bool] | None:
    normalized, _, _ = _normalize_with_original_offsets(text)
    claims: list[tuple[str, bool]] = []
    for predicate, positive_patterns, negative_patterns in _POLARITY_PATTERNS:
        negative = any(re.search(pattern, normalized) for pattern in negative_patterns)
        positive = any(re.search(pattern, normalized) for pattern in positive_patterns)
        if negative:
            claims.append((predicate, False))
        elif positive:
            claims.append((predicate, True))
    if len(claims) != 1:
        return None
    return claims[0]


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        raise ValueError("Evidence vectors must have matching non-zero dimensions.")
    dot = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(float(item) ** 2 for item in left))
    right_norm = math.sqrt(sum(float(item) ** 2 for item in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)
