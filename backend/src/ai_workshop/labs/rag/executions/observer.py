"""Task-local, server-owned observation scope; never populated from HTTP headers."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

from ai_workshop.labs.rag.executions.domain import (
    STAGES,
    ExecutionIdentity,
    ExecutionOutcome,
    ExecutionRecorder,
    SelectionObservation,
    StageName,
    StageObservation,
    StageState,
)

logger = logging.getLogger(__name__)
current_observer: ContextVar[ExecutionObserver | None] = ContextVar("rag_execution", default=None)


class ExecutionObserver:
    def __init__(self, identity: ExecutionIdentity, recorder: ExecutionRecorder) -> None:
        self.identity, self.recorder = identity, recorder
        self.complete = True
        self.persisted_id: UUID | None = None
        self.active: StageName | None = None
        self.started: dict[StageName, tuple[datetime, float]] = {}
        self.done: set[StageName] = set()

    async def _write(self, operation: Callable[[], Awaitable[None]]) -> None:
        try:
            await operation()
        except Exception:
            self.complete = False
            logger.warning(
                "execution_observation_incomplete execution_id=%s stage=%s code=write_failed",
                self.identity.execution_id,
                self.active,
            )

    async def start(self) -> None:
        await self._write(lambda: self.recorder.start(self.identity))
        if self.complete:
            self.persisted_id = self.identity.execution_id

    async def begin(self, stage: StageName) -> None:
        self.active = stage
        self.started[stage] = datetime.now(UTC), perf_counter()
        await self._write(
            lambda: self.recorder.record(
                self.identity.execution_id,
                StageObservation(stage=stage, state="running", started_at=self.started[stage][0]),
            )
        )

    async def end(
        self,
        stage: StageName,
        *,
        state: StageState = "completed",
        reason: str | None = None,
        selection: SelectionObservation | None = None,
    ) -> None:
        started = self.started.get(stage)
        observation = StageObservation(
            stage=stage,
            state=state,
            reason=reason,
            selection=selection,
            started_at=started[0] if started else None,
            ended_at=datetime.now(UTC),
            duration_ms=(perf_counter() - started[1]) * 1000 if started else None,
        )
        await self._write(lambda: self.recorder.record(self.identity.execution_id, observation))
        self.done.add(stage)
        if self.active == stage:
            self.active = None

    async def fail(self, code: str) -> None:
        if self.active:
            await self.end(self.active, state="failed", reason=code)

    async def finish(self, outcome: ExecutionOutcome) -> None:
        for stage in STAGES:
            if stage not in self.done:
                await self.end(stage, state="skipped", reason="not_executed")
        await self._write(
            lambda: self.recorder.finish(
                self.identity.execution_id, outcome.model_copy(update={"complete": self.complete})
            )
        )


async def observed_call[T](operation: Awaitable[T], observer: ExecutionObserver | None) -> T:
    token = current_observer.set(observer)
    try:
        return await operation
    finally:
        current_observer.reset(token)


async def begin(stage: StageName) -> None:
    observer = current_observer.get()
    if observer:
        await observer.begin(stage)


async def end(
    stage: StageName,
    *,
    state: StageState = "completed",
    reason: str | None = None,
    selection: SelectionObservation | None = None,
) -> None:
    observer = current_observer.get()
    if observer:
        await observer.end(stage, state=state, reason=reason, selection=selection)


def execution_id() -> UUID | None:
    observer = current_observer.get()
    return observer.persisted_id if observer else None


async def capture_selection(factory: Callable[[], SelectionObservation]) -> None:
    observer = current_observer.get()
    if observer is None:
        return

    async def capture() -> None:
        await observer.end("selection", selection=factory())

    await observer._write(capture)
