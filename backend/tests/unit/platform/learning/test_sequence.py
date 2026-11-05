from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.config import LearningLimits
from ai_workshop.platform.learning.repository import (
    LearningCursor,
    LearningListFilters,
    LearningOrderPosition,
)
from ai_workshop.platform.learning.schemas import ExperimentFields, LearningDraft, LearningSequence
from ai_workshop.platform.learning.service import LearningCursorCodec
from ai_workshop.shared.errors import AppError
from tests.unit.platform.learning.test_service import (
    MemoryLearningRepository,
    MutableReferenceResolver,
    service_for,
)


def test_sequence_is_explicit_trimmed_and_old_experiments_remain_compatible():
    assert ExperimentFields().learning_sequence is None
    sequence = LearningSequence(series="  Synthetic series  ", step=2, performed_on="2026-11-05")
    assert sequence.series == "Synthetic series"
    assert sequence.performed_on == date(2026, 11, 5)
    assert (
        ExperimentFields(status="completed", learning_sequence=sequence).learning_sequence
        == sequence
    )


@pytest.mark.parametrize("step", [0, -1, True, "2", 2.5, 2147483648])
def test_sequence_rejects_invalid_steps(step):
    with pytest.raises(ValidationError):
        LearningSequence(series="Synthetic", step=step)


def test_planned_sequence_has_no_claim_of_execution():
    assert ExperimentFields(learning_sequence=LearningSequence(series="Synthetic"))
    for payload in [{"step": 1}, {"performed_on": "2026-11-05"}]:
        with pytest.raises(ValidationError):
            ExperimentFields(learning_sequence=LearningSequence(series="Synthetic", **payload))
    with pytest.raises(ValidationError):
        LearningSequence(series="  ")


def test_sequence_cursor_roundtrip_binds_sort_and_preserves_unknown_position():
    actor = uuid4()
    codec = LearningCursorCodec("synthetic-test-secret", max_length=4096)
    filters = LearningListFilters(sort="learning_order")
    cursor = LearningCursor(
        updated_at=datetime.now(UTC),
        record_id=uuid4(),
        learning_order=LearningOrderPosition(
            series=None, phase=2, step=0, created_at=datetime.now(UTC)
        ),
    )
    encoded = codec.encode(actor, filters, cursor)
    assert codec.decode(encoded, actor, filters) == cursor
    with pytest.raises(AppError):
        codec.decode(encoded, actor, LearningListFilters())
    updated = LearningCursor(updated_at=datetime.now(UTC), record_id=uuid4())
    encoded_updated = codec.encode(actor, LearningListFilters(), updated)
    with pytest.raises(AppError):
        codec.decode(encoded_updated, actor, filters)


def test_maximum_korean_series_fits_default_signed_cursor():
    limits = LearningLimits()
    actor = uuid4()
    filters = LearningListFilters(sort="learning_order")
    codec = LearningCursorCodec("synthetic-test-secret", max_length=limits.cursor_max_chars)
    cursor = LearningCursor(
        updated_at=datetime.now(UTC),
        record_id=uuid4(),
        learning_order=LearningOrderPosition(
            series="학" * limits.title_max_chars,
            phase=0,
            step=2147483647,
            created_at=datetime.now(UTC),
        ),
    )
    assert codec.decode(codec.encode(actor, filters, cursor), actor, filters) == cursor


async def test_series_uses_configured_title_limit_before_persistence():
    repository = MemoryLearningRepository()
    service = service_for(
        repository, MutableReferenceResolver(), configured_limits=LearningLimits(title_max_chars=8)
    )
    draft = LearningDraft(
        title="Fixture",
        body="Synthetic",
        kind="experiment",
        experiment=ExperimentFields(learning_sequence=LearningSequence(series="학" * 9)),
    )
    with pytest.raises(AppError):
        await service.create(uuid4(), draft)
    assert repository.create_calls == 0


def test_lineage_defaults_do_not_infer_continuation_or_improvement():
    sequence = LearningSequence(series="Synthetic", step=3)
    assert sequence.start_mode == "unknown"
    assert sequence.outcome_status == "not_evaluated"
    assert sequence.source_label is None
    assert sequence.outcome is None


def test_lineage_preserves_explicit_source_and_result_text():
    payload = {
        "series": "Synthetic",
        "start_mode": "continued",
        "source_label": " Previous candidate ",
        "source_evidence": "artifact A -> B\nverified locally",
        "objective": "Improve a synthetic rule",
        "outcome_status": "mixed",
        "outcome": "One trained example improved; unused examples did not.",
        "remaining": " Generalization remains unproven. ",
    }
    sequence = LearningSequence.model_validate(payload)
    assert sequence.model_dump(include=set(payload)) == payload
    assert LearningSequence.model_validate(sequence.model_dump()) == sequence


@pytest.mark.parametrize("source", [None, "", "   "])
def test_continued_training_requires_named_source(source):
    with pytest.raises(ValidationError, match="source"):
        LearningSequence(series="Synthetic", start_mode="continued", source_label=source)


@pytest.mark.parametrize("status", ["improved", "no_improvement", "mixed"])
def test_evaluated_result_requires_actual_observation(status):
    with pytest.raises(ValidationError, match="outcome"):
        LearningSequence(series="Synthetic", outcome_status=status, outcome="  ")
    with pytest.raises(ValidationError, match="planned"):
        ExperimentFields(
            learning_sequence=LearningSequence(
                series="Synthetic", outcome_status=status, outcome="Synthetic observation"
            )
        )


@pytest.mark.parametrize("sort", ["learning_order", "learning_latest"])
def test_both_learning_sorts_bind_cursor_and_keep_positive_step(sort):
    actor = uuid4()
    codec = LearningCursorCodec("synthetic-test-secret", max_length=4096)
    filters = LearningListFilters(sort=sort)
    cursor = LearningCursor(
        updated_at=datetime.now(UTC),
        record_id=uuid4(),
        learning_order=LearningOrderPosition(
            series="Synthetic", phase=0, step=2147483647, created_at=datetime.now(UTC)
        ),
    )
    encoded = codec.encode(actor, filters, cursor)
    assert codec.decode(encoded, actor, filters) == cursor
    other = "learning_latest" if sort == "learning_order" else "learning_order"
    with pytest.raises(AppError):
        codec.decode(encoded, actor, LearningListFilters(sort=other))


@pytest.mark.parametrize(
    "field", ["source_label", "source_evidence", "objective", "outcome", "remaining"]
)
async def test_lineage_text_uses_existing_configured_field_limit(field):
    repository = MemoryLearningRepository()
    service = service_for(
        repository,
        MutableReferenceResolver(),
        configured_limits=LearningLimits(max_text_field_chars=20),
    )
    draft = LearningDraft(
        title="Fixture",
        body="Synthetic",
        kind="experiment",
        experiment=ExperimentFields(
            status="completed",
            learning_sequence=LearningSequence(series="Synthetic", **{field: "x" * 21}),
        ),
    )
    with pytest.raises(AppError):
        await service.create(uuid4(), draft)
    assert repository.create_calls == 0
