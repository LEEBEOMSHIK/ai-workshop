"""Body-free durable capacity port, independent of call authorization."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CodexExecutionLease:
    id: UUID
    request_id: UUID
    runner_ref: str
    configuration_sha256: str


class CodexExecutionSlots(Protocol):
    async def acquire(
        self,
        *,
        runner_ref: str,
        configuration_sha256: str,
        max_concurrent: int,
        request_id: UUID,
    ) -> CodexExecutionLease | None: ...

    async def complete(
        self,
        lease: CodexExecutionLease,
        *,
        process_termination_verified: bool,
    ) -> None: ...


class CodexSlotError(RuntimeError):
    """Only fixed local codes escape the persistence adapter."""

    def __init__(self, code: str) -> None:
        if code not in {
            "codex_slot_invalid_input",
            "codex_slot_settings_mismatch",
            "codex_slot_lease_mismatch",
            "codex_slot_source_unavailable",
        }:
            code = "codex_slot_source_unavailable"
        self.code = code
        super().__init__(code)
