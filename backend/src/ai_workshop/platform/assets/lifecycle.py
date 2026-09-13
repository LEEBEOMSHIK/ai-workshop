from enum import StrEnum


class AssetLifecycle(StrEnum):
    ACTIVE = "active"
    TRASHED = "trashed"
    PURGE_PENDING = "purge_pending"
    PURGING = "purging"
    RETRY_WAIT = "retry_wait"
    BLOCKED = "blocked"
    PURGED = "purged"


class LifecycleAction(StrEnum):
    TRASH = "trash"
    RESTORE = "restore"
    REQUEST_PURGE = "request_purge"
    START_PURGE = "start_purge"
    RETRY_LATER = "retry_later"
    BLOCK = "block"
    RETRY = "retry"
    COMPLETE = "complete"


TRANSITIONS: dict[tuple[AssetLifecycle, LifecycleAction], AssetLifecycle] = {
    (AssetLifecycle.ACTIVE, LifecycleAction.TRASH): AssetLifecycle.TRASHED,
    (AssetLifecycle.TRASHED, LifecycleAction.RESTORE): AssetLifecycle.ACTIVE,
    (
        AssetLifecycle.TRASHED,
        LifecycleAction.REQUEST_PURGE,
    ): AssetLifecycle.PURGE_PENDING,
    (
        AssetLifecycle.PURGE_PENDING,
        LifecycleAction.START_PURGE,
    ): AssetLifecycle.PURGING,
    (
        AssetLifecycle.PURGING,
        LifecycleAction.RETRY_LATER,
    ): AssetLifecycle.RETRY_WAIT,
    (AssetLifecycle.PURGING, LifecycleAction.BLOCK): AssetLifecycle.BLOCKED,
    (AssetLifecycle.RETRY_WAIT, LifecycleAction.RETRY): AssetLifecycle.PURGING,
    (AssetLifecycle.BLOCKED, LifecycleAction.RETRY): AssetLifecycle.PURGING,
    (AssetLifecycle.PURGING, LifecycleAction.COMPLETE): AssetLifecycle.PURGED,
}


def transition(current: AssetLifecycle, action: LifecycleAction) -> AssetLifecycle:
    try:
        return TRANSITIONS[(current, action)]
    except KeyError:
        raise ValueError("invalid_lifecycle_transition") from None


def allows_normal_use(state: AssetLifecycle) -> bool:
    return state is AssetLifecycle.ACTIVE
