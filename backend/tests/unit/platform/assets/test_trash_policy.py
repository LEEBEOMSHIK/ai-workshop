from datetime import UTC, datetime, timedelta, timezone

import pytest

from ai_workshop.platform.assets.trash_policy import RetentionPolicy, purge_deadline


def test_deadline_uses_explicit_policy_and_remains_a_saved_value() -> None:
    deleted = datetime(2026, 1, 1, tzinfo=UTC)

    saved = purge_deadline(deleted, RetentionPolicy(version=1, days=7))
    changed = purge_deadline(deleted, RetentionPolicy(version=2, days=2))

    assert saved == datetime(2026, 1, 8, tzinfo=UTC)
    assert changed == datetime(2026, 1, 3, tzinfo=UTC)
    assert saved == datetime(2026, 1, 8, tzinfo=UTC)


@pytest.mark.parametrize("field", ["version", "days"])
@pytest.mark.parametrize("invalid_value", [True, False, 0, -1, 1.0, "1"])
def test_policy_rejects_values_that_are_not_positive_integers(
    field: str, invalid_value: object
) -> None:
    values = {"version": 1, "days": 7, field: invalid_value}

    with pytest.raises(ValueError):
        RetentionPolicy(**values)


def test_deadline_rejects_naive_trash_time() -> None:
    with pytest.raises(ValueError, match="^invalid_retention_deadline$"):
        purge_deadline(
            datetime(2026, 1, 1),
            RetentionPolicy(version=1, days=7),
        )


def test_deadline_normalizes_offset_time_to_utc_before_adding_days() -> None:
    deleted = datetime(2026, 1, 1, 9, tzinfo=timezone(timedelta(hours=9)))

    deadline = purge_deadline(deleted, RetentionPolicy(version=1, days=7))

    assert deadline == datetime(2026, 1, 8, tzinfo=UTC)
    assert deadline.tzinfo is UTC


def test_deadline_converts_addition_overflow_to_stable_error() -> None:
    with pytest.raises(ValueError, match="^invalid_retention_deadline$"):
        purge_deadline(
            datetime.max.replace(tzinfo=UTC),
            RetentionPolicy(version=1, days=1),
        )


def test_deadline_converts_utc_normalization_overflow_to_stable_error() -> None:
    behind_utc = timezone(timedelta(hours=-1))

    with pytest.raises(ValueError, match="^invalid_retention_deadline$"):
        purge_deadline(
            datetime.max.replace(tzinfo=behind_utc),
            RetentionPolicy(version=1, days=1),
        )
