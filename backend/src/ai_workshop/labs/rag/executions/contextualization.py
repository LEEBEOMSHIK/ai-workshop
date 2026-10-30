"""Bounded private HTTP context observation, separate from the later SDK agent tree."""

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal, Self

from pydantic import model_validator

from ai_workshop.labs.rag.executions.agent_trace import (
    AgentContent,
    TraceModel,
    capture_content,
    validate_content_integrity,
)


class ContextualizationObservation(TraceModel):
    content_retention: Literal["metadata_only", "retained"] = "metadata_only"
    input_kind: Literal["http_request"] = "http_request"
    instructions: AgentContent = AgentContent(content_status="disabled")
    input: AgentContent = AgentContent(content_status="disabled")
    output: AgentContent = AgentContent(content_status="disabled")
    observation_complete: bool = True
    truncated: bool = False

    @model_validator(mode="after")
    def valid_content(self) -> Self:
        if self.content_retention == "retained":
            validate_content_integrity((self.instructions, self.input, self.output))
        return self


_capture: ContextVar[ContextualizationObservation | None] = ContextVar(
    "rag_contextualization_content", default=None,
)


@contextmanager
def capture_contextualization() -> Iterator[None]:
    token = _capture.set(None)
    try:
        yield
    finally:
        _capture.reset(token)


def current_contextualization() -> ContextualizationObservation | None:
    return _capture.get()


def _publish(value: ContextualizationObservation) -> None:
    from ai_workshop.labs.rag.executions.observer import current_observer

    _capture.set(value)
    observer = current_observer.get()
    if observer is not None:
        observer.contextualization = value
        if not value.observation_complete:
            observer.complete = False


def record_contextualization_input(body: Mapping[str, object]) -> None:
    from ai_workshop.labs.rag.executions.observer import current_observer

    try:
        fields = ("messages", "temperature", "max_tokens", "response_format", "reasoning_effort")
        serialized = json.dumps({key: body[key] for key in fields if key in body},
                                ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        messages = body.get("messages")
        instructions = (
            messages[0].get("content") if isinstance(messages, list) and messages else None
        )
        instruction = capture_content(instructions if isinstance(instructions, str) else None)
        value = capture_content(serialized)
        truncated = any(c.content_status == "omitted_size_limit" for c in (instruction, value))
        _publish(ContextualizationObservation(
            content_retention="retained", instructions=instruction, input=value,
            observation_complete=not truncated, truncated=truncated,
        ))
    except Exception:
        observer = current_observer.get()
        if observer is not None:
            observer.complete = False


def record_contextualization_output(content: str) -> None:
    from ai_workshop.labs.rag.executions.observer import current_observer

    try:
        previous = _capture.get()
        if previous is not None:
            output = capture_content(content)
            truncated = previous.truncated or output.content_status == "omitted_size_limit"
            _publish(previous.model_copy(update={
                "output": output, "truncated": truncated, "observation_complete": not truncated,
            }))
    except Exception:
        observer = current_observer.get()
        if observer is not None:
            observer.complete = False


def record_contextualization_failure() -> None:
    """No usable output exists; never receive or hash the rejected response."""
    from ai_workshop.labs.rag.executions.observer import current_observer

    try:
        previous = _capture.get()
        if previous is not None:
            _publish(previous.model_copy(update={
                "output": AgentContent(content_status="not_applicable"),
                "observation_complete": False,
            }))
    except Exception:
        observer = current_observer.get()
        if observer is not None:
            observer.complete = False


def storage_contextualization(value: ContextualizationObservation) -> ContextualizationObservation:
    checked = ContextualizationObservation.model_validate(value.model_dump())
    if checked.content_retention == "retained":
        return checked
    return checked.model_copy(update={field: AgentContent(
        content_status=(
            "not_retained" if content.content_status == "complete" else content.content_status
        ),
        characters=content.characters, sha256=content.sha256,
    ) for field in ("instructions", "input", "output") if (content := getattr(checked, field))})
