"""Bounded application observations; no SDK types, credentials or reasoning traces."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal, Protocol, Self, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_workshop.labs.rag.executions.model_timing import (
    LocalHttpApi,
    ModelCallTiming,
    OllamaServerTiming,
    ServerTimingStatus,
)

TRACE_STORAGE_KEY = "_agent_trace_v1"
MAX_SPANS = 64
MAX_CONTENT_CHARACTERS = 32768
MAX_TOTAL_CHARACTERS = 131072
SpanKind = Literal["agent", "delegation", "tool", "model"]
SpanState = Literal["running", "completed", "failed", "cancelled"]


class TraceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class AgentContent(TraceModel):
    content_status: Literal[
        "complete", "not_retained", "disabled", "omitted_size_limit", "omitted_validation_failure",
        "not_applicable",
    ]
    text: str | None = Field(default=None, max_length=MAX_CONTENT_CHARACTERS)
    characters: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def consistent_body(self) -> Self:
        if (self.content_status == "complete") != (self.text is not None):
            raise ValueError("Content state does not match body availability")
        return self


def validate_content_integrity(values: tuple[AgentContent, ...]) -> int:
    characters = 0
    for value in values:
        if value.content_status in {"disabled", "not_applicable"}:
            if value.characters is not None or value.sha256 is not None:
                raise ValueError("Absent content has a digest")
            continue
        if value.characters is None or value.sha256 is None:
            raise ValueError("Retained content lacks integrity metadata")
        if value.text is not None:
            if value.characters != len(value.text) or value.sha256 != hashlib.sha256(
                value.text.encode("utf-8")
            ).hexdigest():
                raise ValueError("Retained content integrity mismatch")
            characters += len(value.text)
    if characters > MAX_TOTAL_CHARACTERS:
        raise ValueError("Execution content exceeds total limit")
    return characters


class AgentEvidenceRef(TraceModel):
    document_id: UUID
    asset_version_id: UUID
    projection_id: UUID


class CitationReferenceMap(TraceModel):
    """Server-owned e1..eN identity order; never part of the model input."""

    format: Literal["rag-answer-v6"] = "rag-answer-v6"
    evidence_ids: tuple[UUID, ...] = Field(max_length=200)

    @model_validator(mode="after")
    def unique_evidence_ids(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("Citation reference identities must be unique")
        return self


class AgentSpan(TraceModel):
    id: UUID
    parent_id: UUID | None
    sequence: int = Field(ge=0)
    kind: SpanKind
    name: str = Field(max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    state: SpanState
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    from_agent: str | None = Field(default=None, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    to_agent: str | None = Field(default=None, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    delegation_mode: Literal["as_tool", "handoff"] | None = None
    model_name: str | None = Field(default=None, max_length=200)
    input_kind: Literal["sdk_input", "http_request", "tool_arguments"] = "sdk_input"
    instructions: AgentContent = AgentContent(content_status="disabled")
    input: AgentContent = AgentContent(content_status="disabled")
    output: AgentContent = AgentContent(content_status="disabled")
    input_tokens: int | None = Field(default=None, ge=0, le=2**31 - 1)
    output_tokens: int | None = Field(default=None, ge=0, le=2**31 - 1)
    model_timing: ModelCallTiming | None = None
    citation_reference_map: CitationReferenceMap | None = None
    error_code: str | None = Field(default=None, max_length=100, pattern=r"^[a-z0-9_]+$")
    evidence_refs: tuple[AgentEvidenceRef, ...] = Field(default=(), max_length=200)

    @model_validator(mode="after")
    def timing_belongs_to_model(self) -> Self:
        if self.model_timing is not None and self.kind != "model":
            raise ValueError("Only model spans may contain model call timing")
        if self.citation_reference_map is not None and self.kind != "model":
            raise ValueError("Only model spans may contain a citation reference map")
        return self


class AgentTrace(TraceModel):
    schema_version: Literal[1] = 1
    runtime: Literal["openai_agents"] = "openai_agents"
    content_retention: Literal["metadata_only", "retained"] = "metadata_only"
    run_id: UUID
    root_span_id: UUID | None
    revision: int = Field(ge=0)
    updated_at: datetime
    observation_complete: bool = True
    truncated: bool = False
    spans: tuple[AgentSpan, ...] = Field(default=(), max_length=MAX_SPANS)

    @model_validator(mode="after")
    def connected_tree(self) -> Self:
        seen: set[UUID] = set()
        for index, span in enumerate(self.spans):
            if span.id in seen or span.sequence != index:
                raise ValueError("Invalid span identity or order")
            if index == 0:
                if span.parent_id is not None or self.root_span_id != span.id:
                    raise ValueError("Invalid root span")
            elif span.parent_id not in seen:
                raise ValueError("Missing parent span")
            seen.add(span.id)
        if not self.spans and self.root_span_id is not None:
            raise ValueError("Missing root span")
        if self.content_retention == "retained":
            characters = 0
            for span in self.spans:
                for value in (span.instructions, span.input, span.output):
                    if value.content_status in {"disabled", "not_applicable"}:
                        if value.characters is not None or value.sha256 is not None:
                            raise ValueError("Absent content has a digest")
                        continue
                    if value.characters is None or value.sha256 is None:
                        raise ValueError("Retained content lacks integrity metadata")
                    if value.text is not None:
                        if value.characters != len(value.text) or value.sha256 != hashlib.sha256(
                            value.text.encode("utf-8")
                        ).hexdigest():
                            raise ValueError("Retained content integrity mismatch")
                        characters += len(value.text)
            if characters > MAX_TOTAL_CHARACTERS:
                raise ValueError("Retained content exceeds the trace limit")
        return self


def persisted_agent_trace(trace: AgentTrace) -> AgentTrace:
    """Metadata-only duplicate projection for conversation responses and legacy traces."""
    spans = []
    for span in trace.spans:
        contents = {}
        for field in ("instructions", "input", "output"):
            value: AgentContent = getattr(span, field)
            contents[field] = AgentContent(
                content_status="not_retained" if value.content_status == "complete"
                else value.content_status,
                characters=value.characters,
                sha256=value.sha256,
            )
        spans.append(span.model_copy(update=contents))
    return trace.model_copy(update={"spans": tuple(spans), "content_retention": "metadata_only"})


def storage_agent_trace(trace: AgentTrace) -> AgentTrace:
    """Revalidate every nested value, including objects made with model_copy/construct."""
    checked = AgentTrace.model_validate(trace.model_dump())
    return checked if checked.content_retention == "retained" else persisted_agent_trace(checked)


def read_agent_trace(stages: dict[str, object]) -> AgentTrace | None:
    raw = stages.get(TRACE_STORAGE_KEY)
    if raw is None:
        return None
    # A missing retention marker never upgrades historical bodies to private retention.
    return storage_agent_trace(AgentTrace.model_validate(raw))


def next_agent_trace(previous: object, incoming: AgentTrace) -> dict[str, object] | None:
    """Accept only append/update snapshots from the same server-owned run."""
    safe = storage_agent_trace(incoming)
    if previous is not None:
        old = AgentTrace.model_validate(previous)
        if old.run_id != safe.run_id:
            raise ValueError("Agent run identity changed")
        if old.content_retention != safe.content_retention:
            raise ValueError("Agent retention policy changed")
        if old.revision >= safe.revision:
            return None
        if len(old.spans) > len(safe.spans):
            raise ValueError("Agent observation regressed")
        for before, after in zip(old.spans, safe.spans, strict=False):
            if (before.id, before.parent_id, before.kind, before.name, before.sequence) != (
                after.id, after.parent_id, after.kind, after.name, after.sequence,
            ):
                raise ValueError("Agent span identity changed")
            if before.citation_reference_map != after.citation_reference_map:
                raise ValueError("Agent citation reference map changed")
            if before.state != "running" and before != after:
                raise ValueError("Terminal agent span changed")
    return safe.model_dump(mode="json")


@runtime_checkable
class AgentTraceRecorder(Protocol):
    async def record_agent_trace(self, execution_id: UUID, trace: AgentTrace) -> None: ...


@dataclass
class _Capture:
    enabled: bool
    value: AgentTrace | None = None
    characters: int = 0


_capture: ContextVar[_Capture | None] = ContextVar("rag_agent_trace", default=None)


@contextmanager
def capture_agent_trace(enabled: bool) -> Iterator[None]:
    from ai_workshop.labs.rag.executions.contextualization import capture_contextualization

    token = _capture.set(_Capture(enabled))
    try:
        with capture_contextualization():
            yield
    finally:
        _capture.reset(token)


def capture_content(value: str | None) -> AgentContent:
    scope = _capture.get()
    if value is None:
        return AgentContent(content_status="not_applicable")
    if scope is None or not scope.enabled:
        return AgentContent(content_status="disabled")
    size = len(value)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    if size > MAX_CONTENT_CHARACTERS or scope.characters + size > MAX_TOTAL_CHARACTERS:
        return AgentContent(content_status="omitted_size_limit", characters=size, sha256=digest)
    scope.characters += size
    return AgentContent(content_status="complete", text=value, characters=size, sha256=digest)


def current_agent_trace() -> AgentTrace | None:
    scope = _capture.get()
    return scope.value if scope is not None else None


def response_agent_trace(*, answer_validated: bool) -> AgentTrace | None:
    trace = current_agent_trace()
    if trace is None or answer_validated:
        return trace
    spans = []
    for span in trace.spans:
        output = span.output
        if output.content_status == "complete":
            output = AgentContent(
                content_status="omitted_validation_failure",
                characters=output.characters, sha256=output.sha256,
            )
        spans.append(span.model_copy(update={"output": output}))
    return trace.model_copy(update={"spans": tuple(spans)})


class AgentTraceCollector:
    def __init__(self) -> None:
        self.run_id = uuid4()
        self.spans: list[AgentSpan] = []
        self.started: dict[UUID, float] = {}
        self.revision = 0
        self.characters = 0
        self.complete = True
        self.truncated = False

    def _content(self, value: str | None) -> AgentContent:
        content = capture_content(value)
        if content.content_status == "omitted_size_limit":
            self.complete = False
            self.truncated = True
        if content.text is not None:
            self.characters += len(content.text)
        return content

    async def start_span(
        self, *, kind: SpanKind, name: str, parent_id: UUID | None = None,
        from_agent: str | None = None, to_agent: str | None = None,
        delegation_mode: Literal["as_tool", "handoff"] | None = None,
        model_name: str | None = None,
        input_kind: Literal["sdk_input", "http_request", "tool_arguments"] = "sdk_input",
        instructions: str | None = None, input: str | None = None,
        evidence_refs: tuple[AgentEvidenceRef, ...] = (),
        citation_reference_map: CitationReferenceMap | None = None,
    ) -> UUID:
        span_id = uuid4()
        if len(self.spans) >= MAX_SPANS:
            self.truncated = True
            self.complete = False
            await self._publish()
            return span_id
        span = AgentSpan(
            id=span_id, parent_id=parent_id, sequence=len(self.spans), kind=kind,
            name=name, state="running", started_at=datetime.now(UTC),
            from_agent=from_agent, to_agent=to_agent, delegation_mode=delegation_mode,
            model_name=model_name, input_kind=input_kind,
            instructions=self._content(instructions), input=self._content(input),
            evidence_refs=evidence_refs,
            citation_reference_map=citation_reference_map,
        )
        if (self.spans and parent_id not in self.started) or (not self.spans and parent_id):
            self.complete = False
            await self._publish()
            return span_id
        self.spans.append(span)
        self.started[span_id] = perf_counter()
        await self._publish()
        return span_id

    def attach_model_timing(
        self, span_id: UUID, *, request_duration_ms: float,
        response_headers_ms: float | None, response_body_ms: float | None,
        response_validation_ms: float | None,
        api: LocalHttpApi = "openai_chat_completions",
        server_timing_status: ServerTimingStatus = "not_exposed_by_non_streaming_api",
        server_timing: OllamaServerTiming | None = None,
    ) -> None:
        """Stage timing for the existing terminal publish, preserving timeout/cancel ownership."""
        try:
            timing = ModelCallTiming(
                request_duration_ms=request_duration_ms,
                response_headers_ms=response_headers_ms, response_body_ms=response_body_ms,
                response_validation_ms=response_validation_ms,
                api=api, server_timing_status=server_timing_status, server_timing=server_timing,
            )
        except ValueError:
            self.complete = False
            return
        for index, span in enumerate(self.spans):
            if span.id == span_id and span.state == "running" and span.kind == "model":
                self.spans[index] = span.model_copy(update={"model_timing": timing})
                return

    async def end_span(
        self, span_id: UUID, *, state: SpanState = "completed", output: str | None = None,
        error_code: str | None = None, input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        for index, span in enumerate(self.spans):
            if span.id == span_id and span.state == "running":
                self.spans[index] = span.model_copy(update={
                    "state": state, "ended_at": datetime.now(UTC),
                    "duration_ms": max(0, (perf_counter() - self.started[span_id]) * 1000),
                    "output": self._content(output), "error_code": error_code,
                    "input_tokens": input_tokens, "output_tokens": output_tokens,
                })
                await self._publish()
                return

    async def finish(self, *, state: SpanState = "failed", error_code: str | None = None) -> None:
        for span in reversed(self.spans):
            if span.state == "running":
                await self.end_span(span.id, state=state, error_code=error_code)

    async def _publish(self) -> None:
        from ai_workshop.labs.rag.executions.observer import current_observer

        self.revision += 1
        trace = AgentTrace(
            run_id=self.run_id, root_span_id=self.spans[0].id if self.spans else None,
            content_retention="retained",
            revision=self.revision, updated_at=datetime.now(UTC),
            observation_complete=self.complete, truncated=self.truncated, spans=tuple(self.spans),
        )
        observer = current_observer.get()
        scope = _capture.get()
        if scope is not None:
            scope.value = trace
        if observer is not None:
            await observer.record_agent_trace(trace)
            if not observer.complete:
                self.complete = False
                trace = trace.model_copy(update={"observation_complete": False})
        if scope is not None and (
            scope.value is None
            or (scope.value.run_id == trace.run_id and scope.value.revision <= trace.revision)
        ):
            scope.value = trace
