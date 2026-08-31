from dataclasses import dataclass
from typing import Protocol

from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand


@dataclass(frozen=True, slots=True)
class RagAssetHandoffResult:
    claimed: int
    created: int
    failed: int


class RagAssetHandoffSourcePort(Protocol):
    async def pending(self, *, limit: int) -> tuple[EnsureIndexedCommand, ...]: ...


class RagIngestionJobCreatorPort(Protocol):
    async def ensure_indexed(self, command: EnsureIndexedCommand) -> object: ...


class RagAssetHandoffReconciler:
    def __init__(
        self,
        source: RagAssetHandoffSourcePort,
        creator: RagIngestionJobCreatorPort,
        *,
        batch_size: int = 100,
    ) -> None:
        self.source = source
        self.creator = creator
        self.batch_size = batch_size

    async def run_once(self) -> RagAssetHandoffResult:
        commands = await self.source.pending(limit=self.batch_size)
        created = 0
        failed = 0
        for command in commands:
            try:
                await self.creator.ensure_indexed(command)
            except Exception:
                failed += 1
            else:
                created += 1
        return RagAssetHandoffResult(len(commands), created, failed)
