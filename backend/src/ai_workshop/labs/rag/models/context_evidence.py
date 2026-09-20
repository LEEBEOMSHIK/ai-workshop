from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvidenceBudget:
    max_groups: int
    max_units: int
    max_characters: int

    def __post_init__(self) -> None:
        values = (self.max_groups, self.max_units, self.max_characters)
        if any(type(value) is not int or value < 1 for value in values):
            raise ValueError("Context evidence limits must be positive integers.")
        if self.max_groups > self.max_units:
            raise ValueError("Context group limit cannot exceed unit limit.")


def resolve_evidence_budget(config: Mapping[str, object]) -> EvidenceBudget | None:
    value = config.get("context_evidence")
    contextual_prompt = config.get("prompt_ref") in {"rag-codex-answer-v4", "rag-answer-v2"}
    if value is None:
        if contextual_prompt:
            raise ValueError("Contextual prompts require an explicit evidence budget.")
        return None
    if not contextual_prompt or not isinstance(value, Mapping):
        raise ValueError("Context evidence requires a contextual prompt and structured limits.")
    if type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("Unknown context evidence version.")
    if set(value) != {"version", "max_groups", "max_units", "max_characters"}:
        raise ValueError("Unknown context evidence settings.")
    return EvidenceBudget(
        _context_integer(value.get("max_groups"), "context groups"),
        _context_integer(value.get("max_units"), "context units"),
        _context_integer(value.get("max_characters"), "context characters"),
    )


def _context_integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"Invalid {name}.")
    return value
