from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class DispatchClaim:
    job_id: UUID
    claim_token: UUID
    attempt_count: int


@dataclass(frozen=True, slots=True)
class DispatchRunResult:
    claimed: int
    sent: int
    failed: int


class RagDispatchRepositoryPort(Protocol):
    async def claim_ready(
        self,
        *,
        now: datetime,
        stale_before: datetime,
        limit: int,
    ) -> Sequence[DispatchClaim]: ...

    async def mark_sent(self, claim: DispatchClaim, *, now: datetime) -> None: ...

    async def mark_failed(
        self,
        claim: DispatchClaim,
        *,
        now: datetime,
        retry_at: datetime,
        error: str,
    ) -> None: ...


class RagJobSenderPort(Protocol):
    def send(self, job_id: UUID) -> None: ...


class RagDispatchReconciler:
    def __init__(
        self,
        repository: RagDispatchRepositoryPort,
        sender: RagJobSenderPort,
        *,
        stale_after: timedelta = timedelta(minutes=2),
        base_backoff: timedelta = timedelta(seconds=5),
        max_backoff: timedelta = timedelta(minutes=5),
        batch_size: int = 100,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.repository = repository
        self.sender = sender
        self.stale_after = stale_after
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self.batch_size = batch_size
        self.clock = clock

    async def run_once(self, *, now: datetime | None = None) -> DispatchRunResult:
        dispatch_time = now or self.clock()
        claims = await self.repository.claim_ready(
            now=dispatch_time,
            stale_before=dispatch_time - self.stale_after,
            limit=self.batch_size,
        )
        sent = 0
        failed = 0
        for claim in claims:
            try:
                self.sender.send(claim.job_id)
            except Exception as exc:
                completed_at = now or self.clock()
                failed += 1
                await self.repository.mark_failed(
                    claim,
                    now=completed_at,
                    retry_at=completed_at + self._backoff(claim.attempt_count),
                    error=_safe_broker_failure(exc),
                )
            else:
                await self.repository.mark_sent(claim, now=now or self.clock())
                sent += 1
        return DispatchRunResult(claimed=len(claims), sent=sent, failed=failed)

    def _backoff(self, attempt_count: int) -> timedelta:
        if self.base_backoff <= timedelta(0) or self.max_backoff <= timedelta(0):
            raise ValueError("Dispatch backoff durations must be positive.")
        if self.base_backoff >= self.max_backoff:
            return self.max_backoff
        exponent = max(attempt_count - 1, 0)
        base_microseconds = self.base_backoff // timedelta(microseconds=1)
        max_microseconds = self.max_backoff // timedelta(microseconds=1)
        maximum_multiplier = max_microseconds // base_microseconds
        if exponent >= maximum_multiplier.bit_length():
            return self.max_backoff
        candidate = self.base_backoff * (1 << exponent)
        return candidate if candidate <= self.max_backoff else self.max_backoff


def _safe_broker_failure(exc: Exception) -> str:
    cause_class = "".join(
        character
        if character.isascii() and (character.isalnum() or character in "._")
        else "_"
        for character in type(exc).__name__
    )[:100]
    return f"broker_delivery_failed:{cause_class or 'Exception'}"
