"""Cross-process PostgreSQL capacity, with conservative durable unknown retention.

Settings are immutable for the application lifetime. Mixed fingerprints/capacity
are denied while any slot remains; no timeout, restart or age reclaims a slot.
Caller cancellation may leave a committed slot and requires owned finalization.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from .codex_approval_codec import valid_sha256
from .codex_runner_registry import is_safe_codex_runner_reference
from .codex_slot_models import CodexExecutionSlotRecord
from .codex_slots import CodexExecutionLease, CodexSlotError


def _safe_errors[**P, T](
    operation: Callable[P, Awaitable[T]],
) -> Callable[P, Coroutine[Any, Any, T]]:
    @wraps(operation)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        code: str | None = None
        result: T | None = None
        try:
            result = await operation(*args, **kwargs)
        except CodexSlotError as error:
            code = error.code
        except Exception:
            code = "codex_slot_source_unavailable"
        # Raise outside except and outside contextlib: no raw driver error context.
        if code is not None:
            raise CodexSlotError(code)
        return cast(T, result)

    return wrapped


class SqlAlchemyCodexExecutionSlots:
    def __init__(self, engine: AsyncEngine, *, lock_timeout_ms: int = 5000) -> None:
        if (
            not isinstance(engine, AsyncEngine)
            or type(lock_timeout_ms) is not int
            or not 1 <= lock_timeout_ms <= 60000
        ):
            raise CodexSlotError("codex_slot_invalid_input")
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._lock_timeout_ms = lock_timeout_ms

    @asynccontextmanager
    async def _locked(self, runner_ref: str) -> AsyncIterator[AsyncSession]:
        # Namespaced signed bigint; a collision only over-serializes different runners.
        key = int.from_bytes(
            sha256(("rag-codex-slots:" + runner_ref).encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        async with self._sessions() as session, session.begin():
            await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
            await session.execute(
                text("SELECT set_config('lock_timeout', :timeout, true)"),
                {"timeout": f"{self._lock_timeout_ms}ms"},
            )
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
            yield session

    @_safe_errors
    async def acquire(
        self,
        *,
        runner_ref: str,
        configuration_sha256: str,
        max_concurrent: int,
        request_id: UUID,
    ) -> CodexExecutionLease | None:
        if (
            type(runner_ref) is not str
            or not is_safe_codex_runner_reference(runner_ref)
            or not valid_sha256(configuration_sha256)
            or type(max_concurrent) is not int
            or not 1 <= max_concurrent <= 64
            or type(request_id) is not UUID
        ):
            raise CodexSlotError("codex_slot_invalid_input")
        async with self._locked(runner_ref) as session:
            settings = (
                await session.execute(
                    select(
                        CodexExecutionSlotRecord.configuration_sha256,
                        CodexExecutionSlotRecord.max_concurrent,
                    )
                    .where(CodexExecutionSlotRecord.runner_ref == runner_ref)
                    .distinct()
                    .limit(2)
                )
            ).all()
            if any(row != (configuration_sha256, max_concurrent) for row in settings):
                raise CodexSlotError("codex_slot_settings_mismatch")
            count = await session.scalar(
                select(func.count())
                .select_from(CodexExecutionSlotRecord)
                .where(CodexExecutionSlotRecord.runner_ref == runner_ref)
            )
            if count is None:
                raise CodexSlotError("codex_slot_source_unavailable")
            if count >= max_concurrent:
                return None
            lease = CodexExecutionLease(uuid4(), request_id, runner_ref, configuration_sha256)
            session.add(
                CodexExecutionSlotRecord(
                    id=lease.id,
                    request_id=request_id,
                    runner_ref=runner_ref,
                    configuration_sha256=configuration_sha256,
                    max_concurrent=max_concurrent,
                    created_at=datetime.now(UTC),
                )
            )
        # Transaction commit is finished before exposing ownership.
        return lease

    @_safe_errors
    async def complete(
        self,
        lease: CodexExecutionLease,
        *,
        process_termination_verified: bool,
    ) -> None:
        if (
            type(lease) is not CodexExecutionLease
            or type(lease.id) is not UUID
            or type(lease.request_id) is not UUID
            or type(lease.runner_ref) is not str
            or not is_safe_codex_runner_reference(lease.runner_ref)
            or not valid_sha256(lease.configuration_sha256)
            or type(process_termination_verified) is not bool
        ):
            raise CodexSlotError("codex_slot_invalid_input")
        async with self._locked(lease.runner_ref) as session:
            record = await session.get(CodexExecutionSlotRecord, lease.id, with_for_update=True)
            if (
                record is None
                or CodexExecutionLease(
                    record.id,
                    record.request_id,
                    record.runner_ref,
                    record.configuration_sha256,
                )
                != lease
            ):
                raise CodexSlotError("codex_slot_lease_mismatch")
            if process_termination_verified is True:
                await session.delete(record)
