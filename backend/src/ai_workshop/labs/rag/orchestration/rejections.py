"""Closed diagnostics for rejected delegation; never carry model-provided values."""

from enum import StrEnum

from pydantic import ValidationError

from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.openai_compatible import parse_http_json
from ai_workshop.labs.rag.orchestration.domain import DelegationInput


class DelegationRejectionReason(StrEnum):
    REQUIRED_HANDOFF_MISSING = "delegation_required_handoff_missing"
    MULTIPLE_TOOL_CALLS = "delegation_multiple_tool_calls"
    MALFORMED_TOOL_CALL = "delegation_malformed_tool_call"
    UNAPPROVED_TARGET = "delegation_unapproved_target"
    INVALID_FINISH_REASON = "delegation_invalid_finish_reason"
    INVALID_ARGUMENTS = "delegation_invalid_arguments"
    INVALID_TASK = "delegation_invalid_task"
    INVALID_SDK_TRANSITION = "delegation_invalid_sdk_transition"


class DelegationRejection(GenerationProviderError):
    def __init__(
        self, reason: DelegationRejectionReason, *, provider_error: bool = False,
    ) -> None:
        super().__init__(
            "provider_invalid_response" if provider_error else "orchestration_invalid_delegation",
            retryable=False,
        )
        self.reason = reason


def validate_delegation_arguments(arguments: str) -> DelegationInput:
    try:
        payload = parse_http_json(arguments)
    except GenerationProviderError:
        raise DelegationRejection(
            DelegationRejectionReason.INVALID_ARGUMENTS, provider_error=True,
        ) from None
    try:
        return DelegationInput.model_validate(payload)
    except ValidationError:
        raise DelegationRejection(
            DelegationRejectionReason.INVALID_TASK, provider_error=True,
        ) from None
