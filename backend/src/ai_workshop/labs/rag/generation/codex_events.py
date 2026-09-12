from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, NoReturn, cast


@dataclass(frozen=True, slots=True)
class CodexEventLimits:
    max_total_bytes: int = 1_048_576
    max_line_bytes: int = 262_144
    max_events: int = 64
    max_input_tokens: int = 131_072
    max_output_tokens: int = 16_384

    def __post_init__(self) -> None:
        values = (
            self.max_total_bytes,
            self.max_line_bytes,
            self.max_events,
            self.max_input_tokens,
            self.max_output_tokens,
        )
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("Codex event limits must be non-zero positive integers.")


@dataclass(frozen=True, slots=True)
class CodexTokenUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int | None
    cache_write_input_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class CodexEventResult:
    final_text: str = field(repr=False)
    thread_id: str
    usage: CodexTokenUsage
    observed_model: None = None


class CodexEventError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _InvalidJson(ValueError):
    pass


class CodexEventReceiver:
    """Strict, bounded receiver for one Codex exec JSONL turn."""

    def __init__(self, limits: CodexEventLimits) -> None:
        self._limits = limits
        self._buffer = bytearray()
        self._total_bytes = 0
        self._event_count = 0
        self._phase = "initial"
        self._thread_id: str | None = None
        self._active_item_id: str | None = None
        self._final_text: str | None = None
        self._usage: CodexTokenUsage | None = None
        self._failure_code: str | None = None

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(phase={self._phase!r}, "
            f"event_count={self._event_count}, failed={self._failure_code is not None})"
        )

    def feed(self, chunk: bytes) -> None:
        self._raise_if_failed()
        if self._phase == "completed":
            self._fail("invalid_event_sequence")
        if type(chunk) is not bytes:
            self._fail("invalid_chunk")
        self._total_bytes += len(chunk)
        if self._total_bytes > self._limits.max_total_bytes:
            self._fail("total_bytes_exceeded")
        self._buffer.extend(chunk)
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                pending_cr = self._buffer.endswith(b"\r")
                allowed_pending = self._limits.max_line_bytes + int(pending_cr)
                if len(self._buffer) > allowed_pending:
                    self._fail("line_bytes_exceeded")
                return
            raw_line = bytes(self._buffer[:newline])
            del self._buffer[: newline + 1]
            if raw_line.endswith(b"\r"):
                raw_line = raw_line[:-1]
            if len(raw_line) > self._limits.max_line_bytes:
                self._fail("line_bytes_exceeded")
            self._consume_line(raw_line)

    def finish(self) -> CodexEventResult:
        self._raise_if_failed()
        if self._buffer or self._event_count == 0:
            self._fail("invalid_jsonl")
        if self._phase != "completed" or self._final_text is None or self._usage is None:
            self._fail("invalid_event_sequence")
        return CodexEventResult(
            final_text=self._final_text,
            thread_id=cast(str, self._thread_id),
            usage=self._usage,
        )

    def _consume_line(self, raw_line: bytes) -> None:
        if not raw_line:
            self._fail("invalid_jsonl")
        self._event_count += 1
        if self._event_count > self._limits.max_events:
            self._fail("event_count_exceeded")
        parse_failure: str | None = None
        try:
            event = _parse_event(raw_line)
        except CodexEventError as error:
            parse_failure = error.code
            event = {}
        if parse_failure is not None:
            self._fail(parse_failure)
        event_type = event.get("type")
        if type(event_type) is not str:
            self._fail("invalid_event")
        if event_type in {"turn.failed", "error"}:
            self._fail("cli_failed")
        if event_type == "thread.started":
            self._thread_started(event)
        elif event_type == "turn.started":
            self._turn_started(event)
        elif event_type in {"item.started", "item.updated", "item.completed"}:
            self._item_event(event_type, event)
        elif event_type == "turn.completed":
            self._turn_completed(event)
        else:
            self._fail("invalid_event")

    def _thread_started(self, event: Mapping[str, Any]) -> None:
        if self._phase != "initial" or set(event) != {"type", "thread_id"}:
            self._fail("invalid_event_sequence" if self._phase != "initial" else "invalid_event")
        thread_id = event["thread_id"]
        if type(thread_id) is not str or not thread_id:
            self._fail("invalid_event")
        self._thread_id = thread_id
        self._phase = "thread_started"

    def _turn_started(self, event: Mapping[str, Any]) -> None:
        if set(event) != {"type"}:
            self._fail("invalid_event")
        if self._phase != "thread_started":
            self._fail("invalid_event_sequence")
        self._phase = "turn_started"

    def _item_event(self, event_type: str, event: Mapping[str, Any]) -> None:
        if set(event) != {"type", "item"}:
            self._fail("invalid_event")
        item = event["item"]
        if not isinstance(item, Mapping):
            self._fail("invalid_event")
        allowed = {"id", "type"} if event_type == "item.started" else {"id", "type", "text"}
        actual = set(item)
        if not actual.issubset(allowed) or not {"id", "type"}.issubset(actual):
            self._fail("invalid_event")
        item_id = item["id"]
        item_type = item["type"]
        if type(item_id) is not str or not item_id or item_type != "agent_message":
            self._fail("invalid_event")
        if "text" in item and type(item["text"]) is not str:
            self._fail("invalid_event")
        if self._phase != "turn_started":
            self._fail("invalid_event_sequence")

        if event_type == "item.started":
            if self._active_item_id is not None:
                self._fail("invalid_event_sequence")
            self._active_item_id = item_id
            return
        if event_type == "item.updated":
            if self._active_item_id != item_id:
                self._fail("invalid_event_sequence")
            return
        if self._active_item_id is not None and self._active_item_id != item_id:
            self._fail("invalid_event_sequence")
        if self._final_text is not None or "text" not in item:
            self._fail(
                "invalid_event_sequence" if self._final_text is not None else "invalid_event"
            )
        self._final_text = cast(str, item["text"])
        self._active_item_id = None
        self._phase = "message_completed"

    def _turn_completed(self, event: Mapping[str, Any]) -> None:
        if set(event) != {"type", "usage"}:
            self._fail("invalid_event")
        if self._phase != "message_completed":
            self._fail("invalid_event_sequence")
        usage = event["usage"]
        if not isinstance(usage, Mapping):
            self._fail("invalid_usage")
        required = {"input_tokens", "cached_input_tokens", "output_tokens"}
        allowed = required | {"reasoning_output_tokens", "cache_write_input_tokens"}
        actual = set(usage)
        if not required.issubset(actual) or not actual.issubset(allowed):
            self._fail("invalid_usage")
        values = {name: usage[name] for name in required}
        has_reasoning = "reasoning_output_tokens" in usage
        reasoning = usage.get("reasoning_output_tokens")
        cache_write = usage.get("cache_write_input_tokens")
        if any(type(value) is not int or value < 0 for value in values.values()):
            self._fail("invalid_usage")
        if has_reasoning and (type(reasoning) is not int or reasoning < 0):
            self._fail("invalid_usage")
        if "cache_write_input_tokens" in usage and (
            type(cache_write) is not int or cache_write < 0
        ):
            self._fail("invalid_usage")
        input_tokens = cast(int, values["input_tokens"])
        cached_tokens = cast(int, values["cached_input_tokens"])
        output_tokens = cast(int, values["output_tokens"])
        reasoning_tokens = cast(int | None, reasoning)
        if cached_tokens > input_tokens:
            self._fail("invalid_usage")
        if reasoning_tokens is not None and reasoning_tokens > output_tokens:
            self._fail("invalid_usage")
        if input_tokens > self._limits.max_input_tokens:
            self._fail("input_tokens_exceeded")
        if output_tokens > self._limits.max_output_tokens:
            self._fail("output_tokens_exceeded")
        self._usage = CodexTokenUsage(
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            reasoning_output_tokens=reasoning_tokens,
            cache_write_input_tokens=cast(int | None, cache_write),
        )
        self._phase = "completed"

    def _raise_if_failed(self) -> None:
        if self._failure_code is not None:
            raise CodexEventError(self._failure_code) from None

    def _fail(self, code: str) -> NoReturn:
        self._final_text = None
        self._usage = None
        self._active_item_id = None
        self._phase = "failed"
        self._buffer.clear()
        self._failure_code = code
        raise CodexEventError(code) from None


def _parse_event(raw_line: bytes) -> Mapping[str, Any]:
    failed = False
    try:
        text = raw_line.decode("utf-8", errors="strict")
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError):
        failed = True
        parsed = None
    if failed or not isinstance(parsed, Mapping):
        raise CodexEventError("invalid_jsonl") from None
    return cast(Mapping[str, Any], parsed)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidJson
        result[key] = value
    return result


def _reject_constant(_value: str) -> NoReturn:
    raise _InvalidJson


__all__ = [
    "CodexEventError",
    "CodexEventLimits",
    "CodexEventReceiver",
    "CodexEventResult",
    "CodexTokenUsage",
]
