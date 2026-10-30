"""Client HTTP boundaries, never estimates of unobserved model internals."""

from collections.abc import Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

LocalHttpApi = Literal["openai_chat_completions", "ollama_chat"]
ServerTimingStatus = Literal[
    "not_exposed_by_non_streaming_api", "available", "missing", "invalid",
]


class OllamaServerTiming(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    source: Literal["ollama_chat"] = "ollama_chat"
    total_ms: float = Field(ge=0, strict=True)
    load_ms: float = Field(
        ge=0, strict=True, description="Server preparation and loading, including scheduler wait.",
    )
    prompt_eval_ms: float = Field(ge=0, strict=True)
    eval_ms: float = Field(ge=0, strict=True)


def parse_ollama_timing(payload: object) -> tuple[ServerTimingStatus, OllamaServerTiming | None]:
    """Use only the provider's four counters; never infer a partition or inspect text."""
    fields = ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration")
    if not isinstance(payload, Mapping) or any(key not in payload for key in fields):
        return "missing", None
    values = [payload[key] for key in fields]
    if any(type(value) is not int or not 0 <= value <= 2**53 - 1 for value in values):
        return "invalid", None
    return "available", OllamaServerTiming(
        total_ms=values[0] / 1_000_000, load_ms=values[1] / 1_000_000,
        prompt_eval_ms=values[2] / 1_000_000, eval_ms=values[3] / 1_000_000,
    )


class ModelCallTiming(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    response_mode: Literal["non_streaming"] = "non_streaming"
    api: LocalHttpApi = "openai_chat_completions"
    request_duration_ms: float = Field(
        ge=0, strict=True, description="Client HTTP elapsed time including response close.",
    )
    response_headers_ms: float | None = Field(
        default=None, ge=0, strict=True,
        description="Cumulative elapsed from HTTP request start to headers; not first token time.",
    )
    response_body_ms: float | None = Field(
        default=None, ge=0, strict=True,
        description="Cumulative elapsed to body iterator completion, including automatic close.",
    )
    response_validation_ms: float | None = Field(
        default=None, ge=0, strict=True,
        description="Separate JSON, usage and response contract validation duration.",
    )
    server_timing_status: ServerTimingStatus = "not_exposed_by_non_streaming_api"
    server_timing: OllamaServerTiming | None = None

    @model_validator(mode="after")
    def ordered_boundaries(self) -> Self:
        headers, body = self.response_headers_ms, self.response_body_ms
        if headers is not None and headers > self.request_duration_ms:
            raise ValueError("Headers cannot follow request completion")
        if body is not None and (
            headers is None or body < headers or body > self.request_duration_ms
        ):
            raise ValueError("Body requires ordered headers and request completion")
        if self.response_validation_ms is not None and body is None:
            raise ValueError("Validation requires a complete response body")
        if self.api == "openai_chat_completions":
            if (self.server_timing_status != "not_exposed_by_non_streaming_api"
                    or self.server_timing is not None):
                raise ValueError("Compatibility calls do not collect native timing")
        elif (self.server_timing_status == "not_exposed_by_non_streaming_api"
              or (self.server_timing_status == "available") != (self.server_timing is not None)):
            raise ValueError("Native timing status must agree with its availability")
        if self.server_timing is not None and body is None:
            raise ValueError("Native server timing requires a complete response body")
        return self
