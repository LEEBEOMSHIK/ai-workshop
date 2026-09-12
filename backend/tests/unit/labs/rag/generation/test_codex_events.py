from __future__ import annotations

import json
import traceback
from collections.abc import Iterable

import pytest

from ai_workshop.labs.rag.generation.codex_events import (
    CodexEventError,
    CodexEventLimits,
    CodexEventReceiver,
)


def _lines(*events: dict[str, object], crlf: bool = False) -> bytes:
    separator = b"\r\n" if crlf else b"\n"
    return (
        separator.join(
            json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode()
            for event in events
        )
        + separator
    )


def _valid_events(
    *, text: str = "근거가 있는 답변", usage: dict[str, object] | None = None
) -> tuple[dict[str, object], ...]:
    return (
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"id": "item-1", "type": "agent_message", "text": text},
        },
        {
            "type": "turn.completed",
            "usage": usage
            or {
                "input_tokens": 8,
                "cached_input_tokens": 2,
                "output_tokens": 5,
                "reasoning_output_tokens": 1,
            },
        },
    )


def _receive(chunks: Iterable[bytes], limits: CodexEventLimits | None = None):
    receiver = CodexEventReceiver(limits or CodexEventLimits())
    for chunk in chunks:
        receiver.feed(chunk)
    return receiver.finish()


def _assert_code(
    chunks: Iterable[bytes], code: str, limits: CodexEventLimits | None = None
) -> None:
    receiver = CodexEventReceiver(limits or CodexEventLimits())
    with pytest.raises(CodexEventError) as captured:
        for chunk in chunks:
            receiver.feed(chunk)
        receiver.finish()
    assert captured.value.code == code
    assert str(captured.value) == code
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_receives_official_sequence_across_arbitrary_chunks_and_crlf() -> None:
    payload = _lines(*_valid_events(), crlf=True)

    result = _receive((payload[:1], payload[1:17], payload[17:61], payload[61:]))

    assert result.final_text == "근거가 있는 답변"
    assert result.thread_id == "thread-1"
    assert result.usage.input_tokens == 8
    assert result.usage.cached_input_tokens == 2
    assert result.usage.output_tokens == 5
    assert result.usage.reasoning_output_tokens == 1
    assert result.observed_model is None


@pytest.mark.parametrize("cache_write_tokens", [0, 2, 9000])
def test_measured_usage_field_set_accepts_synthetic_cache_write_counts(
    cache_write_tokens: int,
) -> None:
    # Field set was observed on CLI 0.153.4; these cache-write counts are synthetic.
    usage = {"input_tokens": 7700, "cached_input_tokens": 0,
             "cache_write_input_tokens": cache_write_tokens,
             "output_tokens": 58, "reasoning_output_tokens": 36}
    result = _receive((_lines(*_valid_events(usage=usage)),))
    assert result.usage.cache_write_input_tokens == cache_write_tokens
    assert result.usage.input_tokens == 7700
    assert result.usage.output_tokens == 58
    assert result.usage.reasoning_output_tokens == 36
    assert result.observed_model is None


def test_missing_cache_write_usage_remains_unknown_and_dto_compatible() -> None:
    from ai_workshop.labs.rag.generation.codex_events import CodexTokenUsage

    result = _receive((_lines(*_valid_events()),))
    assert result.usage.cache_write_input_tokens is None
    assert CodexTokenUsage(8, 2, 5, 1).cache_write_input_tokens is None


@pytest.mark.parametrize("value", [None, True, False, -1, 1.0, "1", {}, []])
def test_cache_write_usage_requires_exact_nonnegative_integer(value: object) -> None:
    usage = {"input_tokens": 8, "cached_input_tokens": 0,
             "cache_write_input_tokens": value, "output_tokens": 5}
    _assert_code((_lines(*_valid_events(usage=usage)),), "invalid_usage")


@pytest.mark.parametrize("extra", ["cache_write_tokens", "cache_creation_input_tokens", "future"])
def test_usage_extension_does_not_allow_other_extra_fields(extra: str) -> None:
    usage = {"input_tokens": 8, "cached_input_tokens": 0,
             "cache_write_input_tokens": 0, "output_tokens": 5, extra: 1}
    _assert_code((_lines(*_valid_events(usage=usage)),), "invalid_usage")


@pytest.mark.parametrize("limits,code", [
    (CodexEventLimits(max_input_tokens=7), "input_tokens_exceeded"),
    (CodexEventLimits(max_output_tokens=4), "output_tokens_exceeded"),
])
def test_cache_write_usage_keeps_existing_token_budgets(
    limits: CodexEventLimits, code: str,
) -> None:
    usage = {"input_tokens": 8, "cached_input_tokens": 0,
             "cache_write_input_tokens": 0, "output_tokens": 5}
    _assert_code((_lines(*_valid_events(usage=usage)),), code, limits)


def test_started_and_updated_message_must_complete_with_the_same_id() -> None:
    events = (
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {"type": "item.started", "item": {"id": "item-1", "type": "agent_message"}},
        {
            "type": "item.updated",
            "item": {"id": "item-1", "type": "agent_message", "text": "draft"},
        },
        {
            "type": "item.completed",
            "item": {"id": "item-1", "type": "agent_message", "text": "final"},
        },
        _valid_events()[-1],
    )

    result = _receive((_lines(*events),))

    assert result.final_text == "final"


@pytest.mark.parametrize(
    "events",
    [
        _valid_events()[1:],
        (_valid_events()[0], _valid_events()[2], _valid_events()[1], _valid_events()[3]),
        (*_valid_events(), {"type": "turn.started"}),
        (*_valid_events()[:3], _valid_events()[2], _valid_events()[3]),
        (
            _valid_events()[0],
            _valid_events()[1],
            {"type": "item.started", "item": {"id": "a", "type": "agent_message"}},
            {"type": "item.completed", "item": {"id": "b", "type": "agent_message", "text": "x"}},
            _valid_events()[3],
        ),
    ],
    ids=[
        "missing-thread",
        "message-before-turn",
        "after-completion",
        "duplicate-final",
        "wrong-id",
    ],
)
def test_invalid_event_order_is_rejected(events: tuple[dict[str, object], ...]) -> None:
    _assert_code((_lines(*events),), "invalid_event_sequence")


@pytest.mark.parametrize(
    "event",
    [
        {"type": "mystery"},
        {"type": []},
        {"type": "turn.started", "extra": True},
        {"type": "item.completed", "item": {"id": "x", "text": "missing type"}},
        {"type": "item.completed", "item": {"id": "x", "type": "reasoning", "text": "secret"}},
        {
            "type": "item.completed",
            "item": {"id": "x", "type": "command_execution", "text": "secret"},
        },
    ],
    ids=[
        "unknown-event",
        "non-string-type",
        "unknown-field",
        "missing-item-type",
        "reasoning",
        "tool",
    ],
)
def test_unknown_fields_events_tools_and_reasoning_are_rejected(
    event: dict[str, object],
) -> None:
    _assert_code((_lines(_valid_events()[0], _valid_events()[1], event),), "invalid_event")


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\n",
        b'{"type":"thread.started","thread_id":"x"}',
        b'{"type":"thread.started","type":"turn.started","thread_id":"x"}\n',
        b'{"type":NaN}\n',
        b"\xff\n",
        b"[]\n",
    ],
    ids=["empty", "blank-line", "truncated", "duplicate-key", "nan", "utf8", "non-object"],
)
def test_malformed_stream_is_rejected(payload: bytes) -> None:
    _assert_code((payload,), "invalid_jsonl")


@pytest.mark.parametrize("event_type", ["turn.failed", "error"])
def test_cli_failure_is_sticky_discards_draft_and_hides_body(event_type: str) -> None:
    canary = "PRIVATE-REASONING-CANARY"
    before = _lines(
        _valid_events()[0],
        _valid_events()[1],
        {"type": "item.started", "item": {"id": "item-1", "type": "agent_message"}},
        {
            "type": "item.updated",
            "item": {"id": "item-1", "type": "agent_message", "text": canary},
        },
        {"type": event_type, "message": canary},
    )
    receiver = CodexEventReceiver(CodexEventLimits())
    with pytest.raises(CodexEventError) as first:
        receiver.feed(before)
    with pytest.raises(CodexEventError) as second:
        receiver.feed(_lines(*_valid_events()))
    with pytest.raises(CodexEventError) as third:
        receiver.finish()

    assert first.value.code == second.value.code == third.value.code == "cli_failed"
    rendered = "".join(traceback.format_exception(third.value)) + repr(receiver)
    assert canary not in rendered


@pytest.mark.parametrize(
    ("limits", "chunks", "code"),
    [
        (CodexEventLimits(max_total_bytes=10), (b"123456", b"12345"), "total_bytes_exceeded"),
        (CodexEventLimits(max_line_bytes=3), (b"1234",), "line_bytes_exceeded"),
        (CodexEventLimits(max_events=3), (_lines(*_valid_events()),), "event_count_exceeded"),
    ],
)
def test_stream_limits_reject_only_above_the_boundary(
    limits: CodexEventLimits, chunks: tuple[bytes, ...], code: str
) -> None:
    _assert_code(chunks, code, limits)


def test_total_line_and_event_limits_accept_the_exact_boundary() -> None:
    payload = _lines(*_valid_events())
    longest_line = max(len(line) for line in payload.splitlines())
    result = _receive(
        (payload,),
        CodexEventLimits(
            max_total_bytes=len(payload),
            max_line_bytes=longest_line,
            max_events=4,
        ),
    )
    assert result.final_text == "근거가 있는 답변"


def test_crlf_line_limit_is_independent_of_chunk_boundary() -> None:
    payload = _lines(*_valid_events(), crlf=True)
    limit = max(len(line.removesuffix(b"\r")) for line in payload.split(b"\n") if line)
    limits = CodexEventLimits(max_line_bytes=limit)

    whole = _receive((payload,), limits)
    split = _receive((bytes([value]) for value in payload), limits)

    assert whole.final_text == split.final_text


@pytest.mark.parametrize(
    ("usage", "code"),
    [
        ({"input_tokens": True, "cached_input_tokens": 0, "output_tokens": 1}, "invalid_usage"),
        ({"input_tokens": 1.0, "cached_input_tokens": 0, "output_tokens": 1}, "invalid_usage"),
        ({"input_tokens": -1, "cached_input_tokens": 0, "output_tokens": 1}, "invalid_usage"),
        ({"input_tokens": 1, "cached_input_tokens": 2, "output_tokens": 1}, "invalid_usage"),
        (
            {
                "input_tokens": 1,
                "cached_input_tokens": 0,
                "output_tokens": 1,
                "reasoning_output_tokens": 2,
            },
            "invalid_usage",
        ),
        ({"input_tokens": 1, "cached_input_tokens": 0}, "invalid_usage"),
        ({"input_tokens": 1, "output_tokens": 1, "reasoning_output_tokens": 0}, "invalid_usage"),
        (
            {
                "input_tokens": 1,
                "cached_input_tokens": 0,
                "output_tokens": 1,
                "reasoning_output_tokens": None,
            },
            "invalid_usage",
        ),
        (
            {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1, "extra": 0},
            "invalid_usage",
        ),
        (
            {"input_tokens": 10**100, "cached_input_tokens": 0, "output_tokens": 1},
            "input_tokens_exceeded",
        ),
    ],
)
def test_usage_types_relations_required_fields_and_large_integers_are_rejected(
    usage: dict[str, object], code: str
) -> None:
    _assert_code(
        (_lines(*_valid_events(usage=usage)),),
        code,
        CodexEventLimits(max_input_tokens=100, max_output_tokens=100),
    )


def test_token_limits_use_total_input_and_output_including_reasoning() -> None:
    usage = {
        "input_tokens": 9,
        "cached_input_tokens": 8,
        "output_tokens": 7,
        "reasoning_output_tokens": 7,
    }
    result = _receive(
        (_lines(*_valid_events(usage=usage)),),
        CodexEventLimits(max_input_tokens=9, max_output_tokens=7),
    )
    assert result.usage.output_tokens == 7

    _assert_code(
        (_lines(*_valid_events(usage={**usage, "output_tokens": 8})),),
        "output_tokens_exceeded",
        CodexEventLimits(max_input_tokens=9, max_output_tokens=7),
    )


def test_final_text_and_receiver_repr_do_not_expose_body() -> None:
    canary = "SENSITIVE-FINAL-CANARY"
    receiver = CodexEventReceiver(CodexEventLimits())
    receiver.feed(_lines(*_valid_events(text=canary)))
    result = receiver.finish()

    assert result.final_text == canary
    assert canary not in repr(result)
    assert canary not in repr(receiver)


def test_limits_require_positive_plain_integers() -> None:
    for invalid in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="non-zero positive integers"):
            CodexEventLimits(max_events=invalid)  # type: ignore[arg-type]


def test_finish_is_repeatable_but_events_after_completion_are_rejected() -> None:
    receiver = CodexEventReceiver(CodexEventLimits())
    receiver.feed(_lines(*_valid_events()))

    assert receiver.finish().final_text == receiver.finish().final_text
    with pytest.raises(CodexEventError, match="^invalid_event_sequence$"):
        receiver.feed(_lines({"type": "turn.started"}))


def test_sticky_failure_raises_fresh_exceptions_without_growing_old_tracebacks() -> None:
    receiver = CodexEventReceiver(CodexEventLimits())
    with pytest.raises(CodexEventError) as first:
        receiver.feed(b"not-json\n")
    first_traceback = first.value.__traceback__

    with pytest.raises(CodexEventError) as second:
        receiver.finish()

    assert first.value is not second.value
    assert first.value.code == second.value.code == "invalid_jsonl"
    assert first.value.__traceback__ is first_traceback
