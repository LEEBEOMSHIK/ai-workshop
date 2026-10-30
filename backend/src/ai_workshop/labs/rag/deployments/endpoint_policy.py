"""Native Anthropic endpoints are exclusive; preserve existing local dialect semantics."""

from collections.abc import Mapping
from typing import Literal

from ai_workshop.labs.rag.deployments.domain import ProviderKind

type EndpointDialect = Literal["openai", "ollama", "anthropic"]


def validate_endpoint_dialect(
    provider: ProviderKind,
    reference: str,
    dialects: Mapping[str, EndpointDialect],
) -> EndpointDialect:
    dialect = dialects.get(reference, "openai")
    if (provider is ProviderKind.ANTHROPIC_MESSAGES) != (dialect == "anthropic"):
        raise ValueError("The endpoint dialect does not match this Provider.")
    # Historically openai/ollama select only the local adapter's wire format.
    # Their existing meaning for other Providers is unchanged by the native addition.
    return dialect
