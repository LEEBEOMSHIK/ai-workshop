from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


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
