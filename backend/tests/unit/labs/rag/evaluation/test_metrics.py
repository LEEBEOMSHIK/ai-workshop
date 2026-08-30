import math
from uuid import UUID

import pytest

from ai_workshop.labs.rag.evaluation.metrics import (
    AccessExposure,
    AnswerObservation,
    BoundingBox,
    CharacterSpan,
    HighlightObservation,
    StableObservation,
    bbox_iou,
    bbox_set_iou,
    count_access_leaks,
    false_grounding_rate,
    ndcg_at_k,
    percentile,
    recall_at_k,
    reciprocal_rank,
    reproducibility_rate,
    span_iou,
    structured_highlight_iou,
    supported_precision,
)
from ai_workshop.labs.rag.highlighting.domain import AnswerStatus, HighlightKind

E1 = UUID("00000000-0000-0000-0000-000000000001")
E2 = UUID("00000000-0000-0000-0000-000000000002")
E3 = UUID("00000000-0000-0000-0000-000000000003")
E4 = UUID("00000000-0000-0000-0000-000000000004")


def test_rank_metrics_use_unique_ordered_hits_and_hand_calculated_values() -> None:
    retrieved = (E2, E2, E3, E1, E4)
    relevant = frozenset({E1, E2, E4})

    assert recall_at_k(retrieved, relevant, k=3) == pytest.approx(2 / 3)
    assert reciprocal_rank(retrieved, relevant) == 1.0
    # Unique ranks are E2(relevant), E3, E1(relevant); IDCG has three relevant hits.
    expected = (1.0 + 1.0 / math.log2(4)) / (
        1.0 + 1.0 / math.log2(3) + 1.0 / math.log2(4)
    )
    assert ndcg_at_k(retrieved, relevant, k=3) == pytest.approx(expected)


def test_rank_metrics_do_not_invent_scores_for_no_relevant_evidence() -> None:
    assert recall_at_k((E1,), frozenset(), k=10) is None
    assert reciprocal_rank((E1,), frozenset()) is None
    assert ndcg_at_k((E1,), frozenset(), k=10) is None

    with pytest.raises(ValueError, match="positive"):
        recall_at_k((E1,), frozenset({E1}), k=0)


def test_supported_precision_and_false_grounding_require_direct_expected_evidence() -> None:
    observations = (
        AnswerObservation(
            expected_status=AnswerStatus.SUPPORTED,
            actual_status=AnswerStatus.SUPPORTED,
            expected_evidence_ids=frozenset({E1}),
            answer_evidence_ids=(E1,),
        ),
        AnswerObservation(
            expected_status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            actual_status=AnswerStatus.SUPPORTED,
            expected_evidence_ids=frozenset(),
            answer_evidence_ids=(E2,),
        ),
        # E3 may be related, but it is not an expected direct answer.
        AnswerObservation(
            expected_status=AnswerStatus.SUPPORTED,
            actual_status=AnswerStatus.SUPPORTED,
            expected_evidence_ids=frozenset({E4}),
            answer_evidence_ids=(E3,),
        ),
        AnswerObservation(
            expected_status=AnswerStatus.SUPPORTED,
            actual_status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            expected_evidence_ids=frozenset({E2}),
            answer_evidence_ids=(),
        ),
    )

    assert supported_precision(observations) == pytest.approx(1 / 3)
    assert false_grounding_rate(observations) == pytest.approx(2 / 3)


def test_supported_precision_is_undefined_without_a_supported_prediction() -> None:
    observation = AnswerObservation(
        expected_status=AnswerStatus.INSUFFICIENT_EVIDENCE,
        actual_status=AnswerStatus.INSUFFICIENT_EVIDENCE,
        expected_evidence_ids=frozenset(),
        answer_evidence_ids=(),
    )

    assert supported_precision((observation,)) is None
    assert false_grounding_rate((observation,)) is None


def test_highlight_iou_uses_truthful_character_union_and_bbox_area() -> None:
    assert span_iou(
        expected=(CharacterSpan(0, 10), CharacterSpan(20, 30)),
        actual=(CharacterSpan(5, 25),),
    ) == pytest.approx(10 / 30)
    assert bbox_iou(
        expected=BoundingBox(0, 0, 10, 10),
        actual=BoundingBox(5, 0, 15, 10),
    ) == pytest.approx(50 / 150)
    assert span_iou(expected=(), actual=()) is None
    assert bbox_iou(expected=None, actual=None) is None


def test_bbox_set_iou_uses_geometric_unions_without_double_counting() -> None:
    expected = (BoundingBox(0, 0, 10, 10), BoundingBox(5, 0, 15, 10))
    actual = (BoundingBox(5, 0, 10, 10), BoundingBox(20, 0, 25, 10))

    # Expected union=150, actual union=100, intersection=50, combined union=200.
    assert bbox_set_iou(expected=expected, actual=actual) == pytest.approx(0.25)
    assert bbox_set_iou(expected=(), actual=()) is None
    assert bbox_set_iou(expected=expected, actual=()) == 0.0


def test_percentiles_use_linear_interpolation_without_rounding() -> None:
    values = (10.0, 20.0, 30.0, 40.0)

    assert percentile(values, 0.50) == 25.0
    assert percentile(values, 0.95) == pytest.approx(38.5)
    assert percentile((12.3456789,), 0.95) == 12.3456789

    with pytest.raises(ValueError, match="nonempty"):
        percentile((), 0.95)


def test_access_leaks_count_every_exposing_surface_including_case_logs() -> None:
    exposures = (
        AccessExposure("answer", E2),
        AccessExposure("conflict", E2),
        AccessExposure("related_source", E1),
        AccessExposure("highlight", E3),
        AccessExposure("case_output", E4),
    )

    assert count_access_leaks(
        exposures,
        authorized_source_ids=frozenset({E1, E4}),
        forbidden_source_ids=frozenset({E2}),
    ) == 3


def test_forbidden_sources_take_precedence_and_authorized_related_sources_are_safe() -> None:
    exposures = (
        AccessExposure("related_source", E1),
        AccessExposure("answer", E2),
        AccessExposure("log", E3),
    )

    assert count_access_leaks(
        exposures,
        authorized_source_ids=frozenset({E1, E2}),
        forbidden_source_ids=frozenset({E2}),
    ) == 2


def test_structured_highlight_iou_requires_source_kind_page_and_surface_identity() -> None:
    expected = HighlightObservation(
        surface="answer",
        document_id=E1,
        asset_version_id=E2,
        evidence_unit_id=E3,
        page=1,
        kind=HighlightKind.KEYWORD,
        spans=(CharacterSpan(10, 20),),
        bboxes=(),
    )
    same = expected
    wrong_source = HighlightObservation(
        surface="answer",
        document_id=E4,
        asset_version_id=E2,
        evidence_unit_id=E3,
        page=1,
        kind=HighlightKind.KEYWORD,
        spans=(CharacterSpan(10, 20),),
        bboxes=(),
    )
    wrong_kind = HighlightObservation(
        surface="answer",
        document_id=E1,
        asset_version_id=E2,
        evidence_unit_id=E3,
        page=1,
        kind=HighlightKind.SEMANTIC,
        spans=(CharacterSpan(10, 20),),
        bboxes=(),
    )
    conflict_same_coordinates = HighlightObservation(
        surface="conflict",
        document_id=E1,
        asset_version_id=E2,
        evidence_unit_id=E3,
        page=1,
        kind=HighlightKind.KEYWORD,
        spans=(CharacterSpan(10, 20),),
        bboxes=(),
    )

    assert structured_highlight_iou(expected, (same,)) == 1.0
    assert structured_highlight_iou(expected, (wrong_source,)) == 0.0
    assert structured_highlight_iou(expected, (wrong_kind,)) == 0.0
    assert structured_highlight_iou(expected, (conflict_same_coordinates,)) == 0.0


def test_reproducibility_compares_stable_outputs_and_ignores_latency() -> None:
    stable = StableObservation(
        retrieved_evidence_ids=(E1, E2),
        answer_status=AnswerStatus.SUPPORTED,
        answer_evidence_ids=(E1,),
        conflict_evidence_ids=(),
        related_evidence_ids=(E2,),
        highlight_kind=HighlightKind.KEYWORD,
        highlight_spans=(CharacterSpan(0, 4),),
        highlight_bboxes=(),
    )
    changed = StableObservation(
        retrieved_evidence_ids=(E2, E1),
        answer_status=AnswerStatus.SUPPORTED,
        answer_evidence_ids=(E1,),
        conflict_evidence_ids=(),
        related_evidence_ids=(E2,),
        highlight_kind=HighlightKind.KEYWORD,
        highlight_spans=(CharacterSpan(0, 4),),
        highlight_bboxes=(),
    )

    assert reproducibility_rate(((stable, stable), (stable, changed))) == 0.5
    assert reproducibility_rate(()) is None
