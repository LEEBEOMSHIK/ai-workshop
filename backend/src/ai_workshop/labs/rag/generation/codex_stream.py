"""Validate one bounded Codex JSONL stream before releasing its final event.

This is an internal process adapter, not an authorized generation runtime. CLI
configuration, authorization and actual model identity remain caller concerns.
Event rejection cannot undo tool effects that happened before detection.
"""

import threading
from dataclasses import dataclass, field

from .codex_events import CodexEventError, CodexEventLimits, CodexEventReceiver, CodexEventResult
from .windows_process import ProcessFailure, ProcessRequest, WindowsProcessRunner


@dataclass(frozen=True)
class CodexStreamResult:
    events: CodexEventResult | None = field(default=None, repr=False)
    process_failure: ProcessFailure | None = None
    event_failure: str | None = None
    cleanup_verified: bool = True
    active_processes_after_cleanup: int | None = None


class CodexStreamRunner:
    def __init__(self, process_runner: WindowsProcessRunner | None = None) -> None:
        self._process_runner = (
            process_runner if process_runner is not None else WindowsProcessRunner()
        )

    def run(
        self, request: ProcessRequest, event_limits: CodexEventLimits,
        cancellation: threading.Event | None = None,
    ) -> CodexStreamResult:
        receiver = CodexEventReceiver(event_limits)
        event_failure: str | None = None

        def observe(chunk: bytes) -> bool:
            nonlocal event_failure
            try:
                receiver.feed(chunk)
            except CodexEventError as error:
                # Only the receiver's stable codes cross this boundary, never exception text.
                event_failure = error.code
                return False
            return True

        try:
            process = self._process_runner.run(
                request, cancellation, stdout_observer=observe, capture_output=False,
            )
        except Exception:
            # An unexpected runner failure provides no trustworthy cleanup evidence.
            return CodexStreamResult(
                process_failure=ProcessFailure.IO_FAILED, event_failure=event_failure,
                cleanup_verified=False,
            )

        failure = process.failure
        cleanup_verified = process.cleanup_verified
        if not cleanup_verified or process.active_processes_after_cleanup not in (None, 0):
            failure = ProcessFailure.CLEANUP_FAILED
            cleanup_verified = False
        elif failure is None:
            if process.exit_code is None:
                failure = ProcessFailure.IO_FAILED
            elif process.exit_code != 0:
                failure = ProcessFailure.NONZERO_EXIT
            elif process.active_processes_after_cleanup != 0:
                failure = ProcessFailure.CLEANUP_FAILED
                cleanup_verified = False

        events: CodexEventResult | None = None
        if failure is None and event_failure is None:
            try:
                events = receiver.finish()
            except CodexEventError as error:
                event_failure = error.code
        return CodexStreamResult(
            events=events, process_failure=failure, event_failure=event_failure,
            cleanup_verified=cleanup_verified,
            active_processes_after_cleanup=process.active_processes_after_cleanup,
        )
