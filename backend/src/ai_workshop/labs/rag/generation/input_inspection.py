"""Bounded request-local inspection; never logs or persists prompt/source text."""

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ai_workshop.labs.rag.models.context_evidence import EvidenceBudget

# Diagnostic response contract limit, independent of model/token budgets (ADR-0038).
CAPTURE_LIMIT_CHARACTERS = 131072
_BODY_FIELDS = ("messages", "temperature", "max_tokens", "response_format",
                "reasoning_effort")


class GenerationInputInspection(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["prepared", "response_received"]
    provider: str
    dialect: str
    model: str
    model_version: int
    prompt_ref: str
    profile_version: int
    request_json: str | None
    body_characters: int
    body_bytes: int
    sha256: str
    content_status: Literal["complete", "omitted_size_limit"]
    capture_limit_characters: int
    max_output_tokens: int
    evidence_budget: EvidenceBudget | None
    provider_truncation: Literal["unknown"] = "unknown"


@dataclass
class _Capture:
    value: GenerationInputInspection | None = None


_capture: ContextVar[_Capture | None] = ContextVar("generation_input_inspection", default=None)


@contextmanager
def capture_generation_input(enabled: bool) -> Iterator[None]:
    token = _capture.set(_Capture() if enabled else None)
    try:
        yield
    finally:
        _capture.reset(token)


def current_input_inspection() -> GenerationInputInspection | None:
    capture = _capture.get()
    return capture.value if capture else None


def record_generation_input(
    body: Mapping[str, object], *, provider: str, dialect: str,
    prompt_ref: str, profile_version: int, evidence_budget: EvidenceBudget | None,
    model_name: str, model_version: int,
) -> None:
    capture = _capture.get()
    if capture is None:
        return
    # Safe body projection: raw provider model identity is owner-only (RAG design).
    # Never include headers, URL or client configuration. Message strings stay exact.
    serialized = json.dumps({key: body[key] for key in _BODY_FIELDS if key in body},
                            ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    content = serialized.encode("utf-8")
    complete = len(serialized) <= CAPTURE_LIMIT_CHARACTERS
    limit = body.get("max_tokens")
    capture.value = GenerationInputInspection(
        status="prepared", provider=provider, dialect=dialect,
        model=model_name, model_version=model_version,
        prompt_ref=prompt_ref, profile_version=profile_version,
        request_json=serialized if complete else None,
        body_characters=len(serialized), body_bytes=len(content),
        sha256=sha256(content).hexdigest(),
        content_status="complete" if complete else "omitted_size_limit",
        capture_limit_characters=CAPTURE_LIMIT_CHARACTERS,
        max_output_tokens=limit if isinstance(limit, int) else 0, evidence_budget=evidence_budget,
    )


def record_generation_response() -> None:
    capture = _capture.get()
    if capture is not None and capture.value is not None:
        capture.value = capture.value.model_copy(update={"status": "response_received"})
