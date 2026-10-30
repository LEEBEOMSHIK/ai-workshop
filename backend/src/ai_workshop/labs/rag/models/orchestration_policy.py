"""Versioned opt-in execution limits, independent of model provider configuration."""

from collections.abc import Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_workshop.labs.rag.deployments.domain import (
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)


class OllamaRuntimeOptions(BaseModel):
    """Bounded request options, not evidence of the server's effective runner values."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    version: int = Field(ge=1, le=1)
    num_batch: int | None = Field(default=None, ge=1, le=2048)
    num_thread: int | None = Field(default=None, ge=1, le=64)

    @model_validator(mode="after")
    def at_least_one_option(self) -> Self:
        if self.num_batch is None and self.num_thread is None:
            raise ValueError("At least one Ollama runtime option is required.")
        return self


class OrchestrationPolicy(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    engine: Literal["openai_agents"]
    version: int = Field(ge=1, le=2)
    local_http_api: Literal["openai_chat_completions", "ollama_chat"] = "openai_chat_completions"
    dispatch_mode: Literal[
        "manager_delegation", "direct_answer", "autonomous_handoffs",
    ] = "manager_delegation"
    ollama_runtime: OllamaRuntimeOptions | None = None
    max_model_calls: int = Field(ge=1, le=8)
    max_tool_calls: int = Field(ge=1, le=7)
    max_total_output_tokens: int = Field(ge=1, le=2**31 - 1)

    @field_validator("ollama_runtime", mode="before")
    @classmethod
    def normalize_runtime_mapping(cls, value: object) -> object:
        # Registered profiles deeply freeze their JSON; never modify that snapshot.
        return dict(value) if isinstance(value, Mapping) else value

    @model_validator(mode="after")
    def require_native_runtime_options(self) -> Self:
        if self.ollama_runtime is not None and self.local_http_api != "ollama_chat":
            raise ValueError("Ollama runtime options require the native Ollama chat API.")
        return self

    @model_validator(mode="after")
    def versioned_execution_contract(self) -> Self:
        if self.version == 1:
            if (self.dispatch_mode == "autonomous_handoffs"
                    or self.max_model_calls > 3 or self.max_tool_calls != 1):
                raise ValueError("Version 1 supports the original bounded dispatch modes only.")
        elif self.dispatch_mode != "autonomous_handoffs" or self.max_model_calls < 2:
            raise ValueError("Version 2 requires autonomous handoffs and at least two model calls.")
        return self


def resolve_orchestration_policy(config: Mapping[str, object]) -> OrchestrationPolicy | None:
    if "orchestration" not in config:
        return None
    value = config["orchestration"]
    # Persisted Profile config is deeply frozen with mappingproxy values.
    return OrchestrationPolicy.model_validate(dict(value) if isinstance(value, Mapping) else value)


def supports_orchestration_binding(
    deployment: ModelDeploymentVersion | None, response_schema_version: object,
) -> bool:
    return bool(
        type(response_schema_version) is int and response_schema_version == 2
        and deployment is not None
        and deployment.provider is ProviderKind.LOCAL_OPENAI_COMPATIBLE
        and deployment.location is ExecutionLocation.LOCAL
        and not deployment.external_transfer and deployment.max_retries == 0
    )
