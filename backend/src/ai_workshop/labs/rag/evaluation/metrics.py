import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from ai_workshop.labs.rag.highlighting.domain import AnswerStatus, HighlightKind


@dataclass(frozen=True, slots=True, order=True)
class CharacterSpan:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("A character span requires 0 <= start < end.")


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        values = (self.x0, self.y0, self.x1, self.y1)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("A bounding box requires finite coordinates.")
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("A bounding box requires positive area.")


@dataclass(frozen=True, slots=True)
class AnswerObservation:
    expected_status: AnswerStatus
    actual_status: AnswerStatus
    expected_evidence_ids: frozenset[UUID]
    answer_evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class AccessExposure:
    surface: str
    source_id: UUID

    def __post_init__(self) -> None:
        if not self.surface.strip():
            raise ValueError("An access exposure requires a surface.")


@dataclass(frozen=True, slots=True)
class StableObservation:
    retrieved_evidence_ids: tuple[UUID, ...]
    answer_status: AnswerStatus
    answer_evidence_ids: tuple[UUID, ...]
    conflict_evidence_ids: tuple[UUID, ...]
    related_evidence_ids: tuple[UUID, ...]
    highlight_kind: HighlightKind | None
    highlight_spans: tuple[CharacterSpan, ...]
    highlight_bboxes: tuple[BoundingBox, ...]


def _unique(items: Iterable[UUID]) -> tuple[UUID, ...]:
    return tuple(dict.fromkeys(items))


def recall_at_k(
    retrieved: Sequence[UUID],
    relevant: frozenset[UUID],
    *,
    k: int,
) -> float | None:
    if k < 1:
        raise ValueError("Recall@K requires a positive K.")
    if not relevant:
        return None
    hits = relevant.intersection(_unique(retrieved)[:k])
    return len(hits) / len(relevant)


def reciprocal_rank(
    retrieved: Sequence[UUID],
    relevant: frozenset[UUID],
) -> float | None:
    if not relevant:
        return None
    for rank, evidence_id in enumerate(_unique(retrieved), start=1):
        if evidence_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    retrieved: Sequence[UUID],
    relevant: frozenset[UUID],
    *,
    k: int,
) -> float | None:
    if k < 1:
        raise ValueError("nDCG@K requires a positive K.")
    if not relevant:
        return None
    ranked = _unique(retrieved)[:k]
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, evidence_id in enumerate(ranked, start=1)
        if evidence_id in relevant
    )
    ideal_count = min(len(relevant), k)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / ideal


def _is_correct_supported(observation: AnswerObservation) -> bool:
    returned = frozenset(observation.answer_evidence_ids)
    return (
        observation.actual_status is AnswerStatus.SUPPORTED
        and observation.expected_status is AnswerStatus.SUPPORTED
        and bool(returned)
        and returned.issubset(observation.expected_evidence_ids)
    )


def supported_precision(observations: Sequence[AnswerObservation]) -> float | None:
    predicted = tuple(
        item for item in observations if item.actual_status is AnswerStatus.SUPPORTED
    )
    if not predicted:
        return None
    return sum(_is_correct_supported(item) for item in predicted) / len(predicted)


def false_grounding_rate(
    observations: Sequence[AnswerObservation],
) -> float | None:
    predicted = tuple(
        item for item in observations if item.actual_status is AnswerStatus.SUPPORTED
    )
    if not predicted:
        return None
    return sum(not _is_correct_supported(item) for item in predicted) / len(predicted)


def _merged_spans(spans: Sequence[CharacterSpan]) -> tuple[CharacterSpan, ...]:
    merged: list[CharacterSpan] = []
    for span in sorted(spans):
        if not merged or span.start > merged[-1].end:
            merged.append(span)
            continue
        previous = merged[-1]
        merged[-1] = CharacterSpan(previous.start, max(previous.end, span.end))
    return tuple(merged)


def _span_length(spans: Sequence[CharacterSpan]) -> int:
    return sum(span.end - span.start for span in _merged_spans(spans))


def span_iou(
    *,
    expected: Sequence[CharacterSpan],
    actual: Sequence[CharacterSpan],
) -> float | None:
    if not expected and not actual:
        return None
    expected_merged = _merged_spans(expected)
    actual_merged = _merged_spans(actual)
    intersections: list[CharacterSpan] = []
    for expected_span in expected_merged:
        for actual_span in actual_merged:
            start = max(expected_span.start, actual_span.start)
            end = min(expected_span.end, actual_span.end)
            if end > start:
                intersections.append(CharacterSpan(start, end))
    intersection = _span_length(intersections)
    union = _span_length(expected_merged) + _span_length(actual_merged) - intersection
    return intersection / union if union else None


def bbox_iou(
    *,
    expected: BoundingBox | None,
    actual: BoundingBox | None,
) -> float | None:
    if expected is None and actual is None:
        return None
    if expected is None or actual is None:
        return 0.0
    x0 = max(expected.x0, actual.x0)
    y0 = max(expected.y0, actual.y0)
    x1 = min(expected.x1, actual.x1)
    y1 = min(expected.y1, actual.y1)
    intersection = max(x1 - x0, 0.0) * max(y1 - y0, 0.0)
    expected_area = (expected.x1 - expected.x0) * (expected.y1 - expected.y0)
    actual_area = (actual.x1 - actual.x0) * (actual.y1 - actual.y0)
    return intersection / (expected_area + actual_area - intersection)


def _bbox_union_and_intersection_area(
    first: Sequence[BoundingBox],
    second: Sequence[BoundingBox],
) -> tuple[float, float, float]:
    boxes = tuple(first) + tuple(second)
    if not boxes:
        return 0.0, 0.0, 0.0
    xs = sorted({coordinate for box in boxes for coordinate in (box.x0, box.x1)})
    ys = sorted({coordinate for box in boxes for coordinate in (box.y0, box.y1)})
    first_area = 0.0
    second_area = 0.0
    intersection = 0.0
    for left, right in zip(xs, xs[1:], strict=False):
        x = (left + right) / 2.0
        for top, bottom in zip(ys, ys[1:], strict=False):
            y = (top + bottom) / 2.0
            area = (right - left) * (bottom - top)
            in_first = any(
                box.x0 <= x < box.x1 and box.y0 <= y < box.y1 for box in first
            )
            in_second = any(
                box.x0 <= x < box.x1 and box.y0 <= y < box.y1 for box in second
            )
            if in_first:
                first_area += area
            if in_second:
                second_area += area
            if in_first and in_second:
                intersection += area
    return first_area, second_area, intersection


def bbox_set_iou(
    *,
    expected: Sequence[BoundingBox],
    actual: Sequence[BoundingBox],
) -> float | None:
    if not expected and not actual:
        return None
    expected_area, actual_area, intersection = _bbox_union_and_intersection_area(
        expected, actual
    )
    union = expected_area + actual_area - intersection
    return intersection / union if union else None


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("A percentile requires a nonempty sample.")
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("A percentile quantile must be between zero and one.")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("A percentile sample must contain only finite values.")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    weight = position - lower_index
    return ordered[lower_index] + weight * (
        ordered[upper_index] - ordered[lower_index]
    )


def count_access_leaks(
    exposures: Sequence[AccessExposure],
    *,
    allowed_source_ids: frozenset[UUID],
) -> int:
    return sum(item.source_id not in allowed_source_ids for item in exposures)


def reproducibility_rate(
    repeated_observations: Sequence[Sequence[StableObservation]],
) -> float | None:
    if not repeated_observations:
        return None
    stable_cases = 0
    for observations in repeated_observations:
        if not observations:
            continue
        first = observations[0]
        stable_cases += all(item == first for item in observations[1:])
    return stable_cases / len(repeated_observations)
