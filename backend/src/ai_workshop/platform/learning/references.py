from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from ai_workshop.platform.learning.schemas import ReferenceKey


class ReferenceStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ReferenceView:
    status: ReferenceStatus
    label: str | None
    href: str | None
    key: ReferenceKey | None

    @classmethod
    def unavailable(cls) -> ReferenceView:
        return cls(
            status=ReferenceStatus.UNAVAILABLE,
            label=None,
            href=None,
            key=None,
        )


class ReferenceResolver(Protocol):
    async def resolve(self, actor_id: UUID, key: ReferenceKey) -> ReferenceView: ...
