"""Trusted request binding, never an authorization grant or client intent DTO."""

from dataclasses import dataclass
from uuid import UUID

from .codex_authorization import CodexCallOperation, EvidenceClassification


@dataclass(frozen=True, slots=True)
class CodexRequestContext:
    actor_id: UUID
    request_id: UUID
    operation: CodexCallOperation
    configuration_version_id: UUID
    workspace_ids: tuple[UUID, ...]
    input_classification: EvidenceClassification
    consented: bool
    disclosure_version: str

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not UUID
                for value in (
                    self.actor_id,
                    self.request_id,
                    self.configuration_version_id,
                )
            )
            or type(self.operation) is not CodexCallOperation
            or type(self.workspace_ids) is not tuple
            or len(self.workspace_ids) > 128
            or any(type(value) is not UUID for value in self.workspace_ids)
            or len(set(self.workspace_ids)) != len(self.workspace_ids)
            or type(self.input_classification) is not EvidenceClassification
            or self.input_classification
            not in (
                EvidenceClassification.PUBLIC,
                EvidenceClassification.SYNTHETIC,
            )
            or self.consented is not True
            or type(self.disclosure_version) is not str
            or not 1 <= len(self.disclosure_version) <= 120
            or not self.disclosure_version.isascii()
            or any(ord(value) < 33 or ord(value) == 127 for value in self.disclosure_version)
        ):
            raise ValueError("codex_request_invalid")
        object.__setattr__(self, "workspace_ids", tuple(sorted(self.workspace_ids)))
