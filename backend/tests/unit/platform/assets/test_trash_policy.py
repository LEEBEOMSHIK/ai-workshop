from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest

from ai_workshop.platform.assets.trash_policy import (
    RetentionPolicy,
    TrashAction,
    allows_trash_action,
    purge_deadline,
)
from ai_workshop.platform.workspaces.domain import WorkspaceCapabilities


def test_writer_cannot_reverse_another_members_deletion() -> None:
    capabilities = WorkspaceCapabilities(
        read=True,
        write=True,
        delete=False,
        manage_members=False,
    )

    assert not allows_trash_action(capabilities, TrashAction.RESTORE)


def test_delete_grant_does_not_require_member_management() -> None:
    capabilities = WorkspaceCapabilities(
        read=True,
        write=False,
        delete=True,
        manage_members=False,
    )

    assert allows_trash_action(capabilities, TrashAction.TRASH)
    assert not allows_trash_action(capabilities, TrashAction.RESTORE)


def test_member_management_alone_does_not_grant_trash_actions() -> None:
    capabilities = WorkspaceCapabilities(
        read=False,
        write=False,
        delete=False,
        manage_members=True,
    )

    assert not any(allows_trash_action(capabilities, action) for action in TrashAction)


def test_unregistered_action_is_denied() -> None:
    capabilities = WorkspaceCapabilities(
        read=True,
        write=True,
        delete=True,
        manage_members=True,
    )

    assert not allows_trash_action(capabilities, cast(TrashAction, "archive"))


@pytest.mark.parametrize(
    (
        "read",
        "write",
        "delete",
        "manage_members",
        "expected_list",
        "expected_trash",
        "expected_restore",
        "expected_purge",
    ),
    [
        (False, False, False, False, False, False, False, False),
        (False, False, False, True, False, False, False, False),
        (False, False, True, False, False, False, False, False),
        (False, False, True, True, False, False, False, False),
        (False, True, False, False, False, False, False, False),
        (False, True, False, True, False, False, False, False),
        (False, True, True, False, False, False, False, False),
        (False, True, True, True, False, False, False, False),
        (True, False, False, False, False, False, False, False),
        (True, False, False, True, False, False, False, False),
        (True, False, True, False, True, True, False, True),
        (True, False, True, True, True, True, False, True),
        (True, True, False, False, False, False, False, False),
        (True, True, False, True, False, False, False, False),
        (True, True, True, False, True, True, True, True),
        (True, True, True, True, True, True, True, True),
    ],
)
def test_each_capability_combination_has_an_explicit_action_matrix(
    read: bool,
    write: bool,
    delete: bool,
    manage_members: bool,
    expected_list: bool,
    expected_trash: bool,
    expected_restore: bool,
    expected_purge: bool,
) -> None:
    capabilities = WorkspaceCapabilities(read, write, delete, manage_members)

    assert (
        allows_trash_action(capabilities, TrashAction.LIST),
        allows_trash_action(capabilities, TrashAction.TRASH),
        allows_trash_action(capabilities, TrashAction.RESTORE),
        allows_trash_action(capabilities, TrashAction.PURGE),
    ) == (expected_list, expected_trash, expected_restore, expected_purge)


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
