from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from ai_workshop.platform.workspaces.domain import WorkspaceCapabilities


class TrashAction(StrEnum):
    LIST = "list"
    TRASH = "trash"
    RESTORE = "restore"
    PURGE = "purge"


def allows_trash_action(
    capabilities: WorkspaceCapabilities,
    action: TrashAction,
) -> bool:
    allowed = capabilities.read and capabilities.delete
    if action is TrashAction.RESTORE:
        return allowed and capabilities.write
    return allowed and action in (TrashAction.LIST, TrashAction.TRASH, TrashAction.PURGE)


@dataclass(frozen=True)
class RetentionPolicy:
    version: int
    days: int

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version <= 0:
            raise ValueError("invalid_retention_policy")
        if type(self.days) is not int or self.days <= 0:
            raise ValueError("invalid_retention_policy")


def purge_deadline(trashed_at: datetime, policy: RetentionPolicy) -> datetime:
    try:
        if trashed_at.tzinfo is None or trashed_at.utcoffset() is None:
            raise ValueError
        return trashed_at.astimezone(UTC) + timedelta(days=policy.days)
    except (OverflowError, ValueError) as error:
        raise ValueError("invalid_retention_deadline") from error
