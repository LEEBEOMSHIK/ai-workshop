from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.ingestion.dispatch import (
    DispatchClaim,
    RagDispatchReconciler,
)


class MemoryDispatchRepository:
    def __init__(self, job_id: UUID, available_at: datetime) -> None:
        self.job_id = job_id
        self.status = "pending"
        self.available_at = available_at
        self.claim: DispatchClaim | None = None
        self.attempt_count = 0
        self.last_error: str | None = None
        self.failed_at: datetime | None = None
        self.sent_at: datetime | None = None

    async def claim_ready(
        self,
        *,
        now: datetime,
        stale_before: datetime,
        limit: int,
    ) -> tuple[DispatchClaim, ...]:
        del stale_before, limit
        if self.status != "pending" or self.available_at > now:
            return ()
        self.status = "claimed"
        self.attempt_count += 1
        self.claim = DispatchClaim(self.job_id, uuid4(), self.attempt_count)
        return (self.claim,)

    async def mark_sent(self, claim: DispatchClaim, *, now: datetime) -> None:
        assert claim == self.claim
        assert self.status == "claimed"
        self.status = "sent"
        self.sent_at = now
        self.claim = None

    async def mark_failed(
        self,
        claim: DispatchClaim,
        *,
        now: datetime,
        retry_at: datetime,
        error: str,
    ) -> None:
        assert claim == self.claim
        assert self.status == "claimed"
        self.status = "pending"
        self.available_at = retry_at
        self.last_error = error
        self.failed_at = now
        self.claim = None


class FailOnceSender:
    def __init__(self, repository: MemoryDispatchRepository) -> None:
        self.repository = repository
        self.calls: list[UUID] = []

    def send(self, job_id: UUID) -> None:
        assert self.repository.status == "claimed"
        self.calls.append(job_id)
        if len(self.calls) == 1:
            raise OSError("redis://user:secret@host/0 private-token")


class SteppedClock:
    def __init__(self, *times: datetime) -> None:
        self.times = iter(times)

    def __call__(self) -> datetime:
        return next(self.times)


class SuccessfulSender:
    def __init__(self, repository: MemoryDispatchRepository) -> None:
        self.repository = repository

    def send(self, job_id: UUID) -> None:
        assert job_id == self.repository.job_id
        assert self.repository.status == "claimed"


@pytest.mark.asyncio
async def test_broker_failure_is_persisted_then_reconciled_after_backoff() -> None:
    now = datetime(2026, 8, 31, tzinfo=UTC)
    job_id = uuid4()
    repository = MemoryDispatchRepository(job_id, now)
    sender = FailOnceSender(repository)
    reconciler = RagDispatchReconciler(
        repository,
        sender,
        base_backoff=timedelta(seconds=10),
    )

    first = await reconciler.run_once(now=now)

    assert first.claimed == 1
    assert first.sent == 0
    assert first.failed == 1
    assert repository.status == "pending"
    assert repository.attempt_count == 1
    assert repository.available_at == now + timedelta(seconds=10)
    assert repository.last_error == "broker_delivery_failed:OSError"
    assert "secret" not in repository.last_error
    assert "private-token" not in repository.last_error
    assert "redis://" not in repository.last_error

    too_early = await reconciler.run_once(now=now + timedelta(seconds=9))
    recovered = await reconciler.run_once(now=now + timedelta(seconds=10))

    assert too_early.claimed == 0
    assert recovered.claimed == 1
    assert recovered.sent == 1
    assert recovered.failed == 0
    assert repository.status == "sent"
    assert repository.sent_at == now + timedelta(seconds=10)
    assert sender.calls == [job_id, job_id]


@pytest.mark.asyncio
async def test_failed_send_schedules_backoff_from_broker_completion_time() -> None:
    started_at = datetime(2026, 8, 31, tzinfo=UTC)
    completed_at = started_at + timedelta(seconds=30)
    job_id = uuid4()
    repository = MemoryDispatchRepository(job_id, started_at)
    reconciler = RagDispatchReconciler(
        repository,
        FailOnceSender(repository),
        base_backoff=timedelta(seconds=10),
        clock=SteppedClock(started_at, completed_at),
    )

    result = await reconciler.run_once()

    assert result.failed == 1
    assert repository.failed_at == completed_at
    assert repository.available_at == completed_at + timedelta(seconds=10)


@pytest.mark.asyncio
async def test_successful_send_records_broker_completion_time() -> None:
    started_at = datetime(2026, 8, 31, tzinfo=UTC)
    completed_at = started_at + timedelta(seconds=30)
    repository = MemoryDispatchRepository(uuid4(), started_at)
    reconciler = RagDispatchReconciler(
        repository,
        SuccessfulSender(repository),
        clock=SteppedClock(started_at, completed_at),
    )

    result = await reconciler.run_once()

    assert result.sent == 1
    assert repository.sent_at == completed_at


@pytest.mark.asyncio
async def test_retry_backoff_caps_without_overflow_for_large_attempt_count() -> None:
    now = datetime(2026, 8, 31, tzinfo=UTC)
    repository = MemoryDispatchRepository(uuid4(), now)
    repository.attempt_count = 999_999
    reconciler = RagDispatchReconciler(
        repository,
        FailOnceSender(repository),
        base_backoff=timedelta(seconds=5),
        max_backoff=timedelta(minutes=5),
    )

    result = await reconciler.run_once(now=now)

    assert result.failed == 1
    assert repository.attempt_count == 1_000_000
    assert repository.available_at == now + timedelta(minutes=5)
