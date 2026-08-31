from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.exc import DisconnectionError, IntegrityError, OperationalError

from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand, RagIngestionError


@dataclass(frozen=True, slots=True)
class RagAssetHandoffResult:
    claimed: int
    created: int
    failed: int


class RagAssetHandoffSourcePort(Protocol):
    async def pending(self, *, limit: int) -> tuple[EnsureIndexedCommand, ...]: ...


class RagIngestionJobCreatorPort(Protocol):
    async def ensure_indexed(self, command: EnsureIndexedCommand) -> object: ...


class RagAssetHandoffFailurePort(Protocol):
    async def record(
        self,
        command: EnsureIndexedCommand,
        *,
        error_class: str,
        error_code: str,
        safe_message: str,
    ) -> None: ...

    async def resolve(self, command: EnsureIndexedCommand) -> None: ...


class RagAssetHandoffRunError(RuntimeError):
    def __init__(self, result: RagAssetHandoffResult) -> None:
        super().__init__(
            f"RAG Asset handoff run failed for {result.failed} of {result.claimed} commands."
        )
        self.result = result


@dataclass(frozen=True, slots=True)
class _ClassifiedFailure:
    error_class: str
    error_code: str
    safe_message: str


def _classify_failure(exc: Exception) -> _ClassifiedFailure | None:
    if isinstance(exc, RagIngestionError):
        if exc.code == "index_source_inactive":
            return _ClassifiedFailure(
                "obsolete",
                exc.code,
                "The exact RAG Asset handoff source is no longer active.",
            )
        return _ClassifiedFailure(
            "transient" if exc.retryable else "permanent",
            exc.code,
            (
                "A retryable RAG Asset handoff operation failed."
                if exc.retryable
                else "A deterministic RAG Asset handoff validation failed."
            ),
        )
    if isinstance(exc, (OperationalError, DisconnectionError, TimeoutError)):
        return _ClassifiedFailure(
            "transient",
            "database_transient",
            "A transient database operation interrupted the RAG Asset handoff.",
        )
    if isinstance(exc, IntegrityError):
        return _ClassifiedFailure(
            "transient",
            "handoff_concurrent_commit",
            "A concurrent idempotent RAG Asset handoff commit must be retried.",
        )
    if isinstance(exc, OSError):
        return _ClassifiedFailure(
            "transient",
            "handoff_operational_failure",
            "A transient RAG Asset handoff operation failed.",
        )
    return None


class RagAssetHandoffReconciler:
    def __init__(
        self,
        source: RagAssetHandoffSourcePort,
        creator: RagIngestionJobCreatorPort,
        failures: RagAssetHandoffFailurePort,
        *,
        batch_size: int = 100,
    ) -> None:
        self.source = source
        self.creator = creator
        self.failures = failures
        self.batch_size = batch_size

    async def run_once(self) -> RagAssetHandoffResult:
        commands = await self.source.pending(limit=self.batch_size)
        created = 0
        failed = 0
        unexpected: list[Exception] = []
        for command in commands:
            try:
                await self.creator.ensure_indexed(command)
            except Exception as exc:
                classified = _classify_failure(exc)
                if classified is None:
                    failed += 1
                    unexpected.append(exc)
                    continue
                try:
                    await self.failures.record(
                        command,
                        error_class=classified.error_class,
                        error_code=classified.error_code,
                        safe_message=classified.safe_message,
                    )
                except Exception as record_error:
                    unexpected.append(record_error)
                failed += 1
            else:
                try:
                    await self.failures.resolve(command)
                except Exception as resolve_error:
                    failed += 1
                    unexpected.append(resolve_error)
                else:
                    created += 1
        result = RagAssetHandoffResult(len(commands), created, failed)
        if unexpected:
            raise RagAssetHandoffRunError(result) from unexpected[0]
        return result
