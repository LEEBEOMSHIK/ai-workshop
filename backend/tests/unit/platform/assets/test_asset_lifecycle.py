from itertools import product

import pytest

from ai_workshop.platform.assets.lifecycle import AssetLifecycle as S
from ai_workshop.platform.assets.lifecycle import LifecycleAction as A
from ai_workshop.platform.assets.lifecycle import allows_normal_use, transition

ALLOWED_TRANSITIONS = {
    (S.ACTIVE, A.TRASH): S.TRASHED,
    (S.TRASHED, A.RESTORE): S.ACTIVE,
    (S.TRASHED, A.REQUEST_PURGE): S.PURGE_PENDING,
    (S.PURGE_PENDING, A.START_PURGE): S.PURGING,
    (S.PURGING, A.RETRY_LATER): S.RETRY_WAIT,
    (S.PURGING, A.BLOCK): S.BLOCKED,
    (S.RETRY_WAIT, A.RETRY): S.PURGING,
    (S.BLOCKED, A.RETRY): S.PURGING,
    (S.PURGING, A.COMPLETE): S.PURGED,
}


def test_lifecycle_values_are_stable_lowercase_contracts() -> None:
    assert [state.value for state in S] == [
        "active",
        "trashed",
        "purge_pending",
        "purging",
        "retry_wait",
        "blocked",
        "purged",
    ]


def test_action_values_are_stable_lowercase_contracts() -> None:
    assert [action.value for action in A] == [
        "trash",
        "restore",
        "request_purge",
        "start_purge",
        "retry_later",
        "block",
        "retry",
        "complete",
    ]


@pytest.mark.parametrize(
    ("current", "action", "expected"),
    [(*pair, expected) for pair, expected in ALLOWED_TRANSITIONS.items()],
)
def test_transition_accepts_only_defined_lifecycle_progressions(
    current: S,
    action: A,
    expected: S,
) -> None:
    assert transition(current, action) is expected


@pytest.mark.parametrize(
    ("current", "action"),
    [pair for pair in product(S, A) if pair not in ALLOWED_TRANSITIONS],
)
def test_transition_rejects_every_undefined_enum_pair(current: S, action: A) -> None:
    with pytest.raises(ValueError, match="^invalid_lifecycle_transition$"):
        transition(current, action)


def test_pending_purge_cannot_be_restored() -> None:
    with pytest.raises(ValueError, match="invalid_lifecycle_transition"):
        transition(S.PURGE_PENDING, A.RESTORE)


def test_trash_restore_is_distinct_from_version_readiness() -> None:
    assert transition(S.ACTIVE, A.TRASH) is S.TRASHED
    assert not allows_normal_use(S.TRASHED)
    assert transition(S.TRASHED, A.RESTORE) is S.ACTIVE


def test_only_active_assets_allow_normal_use() -> None:
    assert {state: allows_normal_use(state) for state in S} == {
        S.ACTIVE: True,
        S.TRASHED: False,
        S.PURGE_PENDING: False,
        S.PURGING: False,
        S.RETRY_WAIT: False,
        S.BLOCKED: False,
        S.PURGED: False,
    }


@pytest.mark.parametrize("action", list(A))
def test_purged_is_terminal(action: A) -> None:
    with pytest.raises(ValueError, match="^invalid_lifecycle_transition$"):
        transition(S.PURGED, action)
