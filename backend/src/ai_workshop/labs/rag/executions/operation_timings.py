"""Body-free, stage-owned inclusive timings with no additional persistence calls."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from math import isfinite
from time import perf_counter
from typing import get_args

from ai_workshop.labs.rag.executions.domain import OperationName, OperationTiming

_OPERATION_NAMES = frozenset(get_args(OperationName))


@dataclass(slots=True)
class _Totals:
    duration_ms: float = 0
    calls: int = 0
    failures: int = 0
    items: int = 0
    reused_items: int = 0


class OperationTimings:
    """One stage invocation; retained scopes cannot write into a later invocation."""

    def __init__(self) -> None:
        self.closed = False
        self._totals: dict[OperationName, _Totals] = {}

    def record(
        self, name: OperationName, *, duration_ms: float, failed: bool,
        items: int, reused_items: int,
    ) -> None:
        if self.closed:
            return
        if (
            name not in _OPERATION_NAMES
            or not isfinite(duration_ms)
            or duration_ms < 0
            or type(items) is not int
            or type(reused_items) is not int
            or not 0 <= reused_items <= items
        ):
            raise ValueError("Invalid operation timing metadata")
        totals = self._totals.setdefault(name, _Totals())
        duration = totals.duration_ms + duration_ms
        if not isfinite(duration):
            raise ValueError("Invalid operation timing total")
        totals.duration_ms = duration
        totals.calls += 1
        totals.failures += int(failed)
        totals.items += items
        totals.reused_items += reused_items

    def close(self) -> list[OperationTiming]:
        self.closed = True
        return [
            OperationTiming(
                name=name, duration_ms=value.duration_ms, calls=value.calls,
                failures=value.failures, items=value.items, reused_items=value.reused_items,
            )
            for name, value in self._totals.items()
        ]


@contextmanager
def measure_operation(
    name: OperationName, *, items: int = 0, reused_items: int = 0,
) -> Iterator[None]:
    """Measure sync or awaited work, preserving its exact exception/cancellation."""
    from ai_workshop.labs.rag.executions.observer import current_observer

    observer = current_observer.get()
    if observer is None:
        yield
        return
    try:
        collector = observer.operation_timings()
        started = perf_counter() if collector is not None else None
    except Exception:
        observer.complete = False
        collector, started = None, None
    failed = True
    try:
        yield
        failed = False
    finally:
        if collector is not None and not collector.closed and started is not None:
            try:
                collector.record(
                    name, duration_ms=(perf_counter() - started) * 1000,
                    failed=failed, items=items, reused_items=reused_items,
                )
            except Exception:
                # Timing failures never expose inputs or replace the work's result.
                observer.complete = False
