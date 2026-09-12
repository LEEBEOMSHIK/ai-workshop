from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from ai_workshop.shared.errors import AppError


class Capability(StrEnum):
    VIEW = "view"
    CONFIGURE = "configure"
    EXECUTE = "execute"


@dataclass(frozen=True, slots=True)
class TechnologyDefinition:
    key: str
    label: str

    def __post_init__(self) -> None:
        if not self.key or not self.key.isascii() or not self.key.replace("-", "").isalnum():
            raise ValueError("technology key must be a non-empty ASCII identifier")
        if not self.label.strip():
            raise ValueError("technology label must not be empty")


class TechnologyRegistry:
    def __init__(self, technologies: Iterable[TechnologyDefinition]) -> None:
        ordered = tuple(technologies)
        by_key = {technology.key: technology for technology in ordered}
        if len(by_key) != len(ordered):
            raise ValueError("technology keys must be unique")
        self._technologies = ordered
        self._by_key = by_key

    @property
    def technologies(self) -> tuple[TechnologyDefinition, ...]:
        return self._technologies

    def get(self, key: str) -> TechnologyDefinition | None:
        return self._by_key.get(key)

    def validate_capabilities(
        self,
        technology_key: str,
        capabilities: frozenset[Capability],
    ) -> frozenset[Capability]:
        if technology_key not in self._by_key:
            raise AppError(
                "unknown_technology",
                "The requested technology is not registered.",
                422,
            )
        if Capability.VIEW not in capabilities and capabilities.intersection(
            {Capability.CONFIGURE, Capability.EXECUTE}
        ):
            raise AppError(
                "technology_view_required",
                "View capability is required for configure or execute.",
                422,
            )
        return capabilities
