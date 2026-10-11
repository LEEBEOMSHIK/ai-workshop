from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from ai_workshop.labs.rag.generation.codex_wire import CODEX_GROUNDED_WIRE_SCHEMA_V1
from ai_workshop.labs.rag.generation.codex_wire_v2 import CODEX_GROUNDED_WIRE_SCHEMA_V2
from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    GenerationRequest,
)
from ai_workshop.labs.rag.generation.evidence_payload import evidence_payload
from ai_workshop.labs.rag.generation.prompts import (
    PromptNotFoundError,
    load_prompt,
    prompt_reference_version,
)
from ai_workshop.labs.rag.generation.structured_output import CONTEXTUALIZATION_SCHEMA_V1
from ai_workshop.labs.rag.generation.structured_output_v2 import GROUNDED_GENERATION_SCHEMA_V2

_CONTROL_REF = "rag-codex-control-v1"
_ANSWER_REF = "rag-codex-answer-v2"
_WIRE_ANSWER_REF = "rag-codex-answer-v3"
_CONTEXTUALIZE_REF = "rag-codex-contextualize-v1"


class CodexPromptConfigurationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CodexPromptEnvelope:
    developer_instructions: str = field(repr=False)
    stdin_json: str = field(repr=False)
    output_schema_json: str = field(repr=False)
    control_ref: str
    control_version: int
    control_sha256: str
    task_ref: str
    task_version: int
    task_sha256: str
    schema_ref: str
    schema_version: int
    schema_sha256: str


def build_codex_prompt(
    request: ContextualizationRequest | GenerationRequest,
) -> CodexPromptEnvelope:
    task_ref, schema_ref, schema_version, schema = _trusted_selection(request)
    trusted_assets = _load_trusted_assets(task_ref)
    if trusted_assets is None:
        raise CodexPromptConfigurationError("The configured Codex prompt profile is not available.")
    control, task, control_version, task_version = trusted_assets

    schema_json = _canonical_json(schema)
    payload = _payload(request)
    developer_instructions = "\n\n".join((control, task, f"Output schema:\n{schema_json}"))
    return CodexPromptEnvelope(
        developer_instructions=developer_instructions,
        stdin_json=_canonical_json(payload),
        output_schema_json=schema_json,
        control_ref=_CONTROL_REF,
        control_version=control_version,
        control_sha256=_sha256(control),
        task_ref=task_ref,
        task_version=task_version,
        task_sha256=_sha256(task),
        schema_ref=schema_ref,
        schema_version=schema_version,
        schema_sha256=_sha256(schema_json),
    )


def _trusted_selection(
    request: ContextualizationRequest | GenerationRequest,
) -> tuple[str, str, int, dict[str, Any]]:
    profile = request.profile
    if profile.response_schema_version == 3:
        if (
            profile.prompt_ref != "rag-codex-answer-v6"
            or profile.numeric_proof_policy is None
            or profile.context_prompt_ref != _CONTEXTUALIZE_REF
            or profile.evidence_budget is None
        ):
            _raise_invalid_profile()
        assert profile.numeric_proof_policy is not None
        if isinstance(request, GenerationRequest):
            catalogue = request.numeric_catalogue
            if (
                catalogue is None
                or catalogue.generation_profile_id != profile.profile_id
                or catalogue.policy_digest != profile.numeric_proof_policy.digest
            ):
                _raise_invalid_profile()
            return profile.prompt_ref, "codex-grounded-wire-v2", 2, CODEX_GROUNDED_WIRE_SCHEMA_V2
        return _CONTEXTUALIZE_REF, "contextualization-v1", 1, CONTEXTUALIZATION_SCHEMA_V1
    if (
        profile.prompt_ref
        not in (
            _ANSWER_REF,
            _WIRE_ANSWER_REF,
            "rag-codex-answer-v4",
            "rag-codex-answer-v5",
        )
        or profile.context_prompt_ref != _CONTEXTUALIZE_REF
        or profile.response_schema_version != 2
        or (
            profile.prompt_ref in {"rag-codex-answer-v4", "rag-codex-answer-v5"}
            and profile.evidence_budget is None
        )
    ):
        _raise_invalid_profile()
    if isinstance(request, GenerationRequest):
        if profile.prompt_ref in (_WIRE_ANSWER_REF, "rag-codex-answer-v4", "rag-codex-answer-v5"):
            return profile.prompt_ref, "codex-grounded-wire-v1", 1, CODEX_GROUNDED_WIRE_SCHEMA_V1
        return _ANSWER_REF, "grounded-generation-v2", 2, GROUNDED_GENERATION_SCHEMA_V2
    return _CONTEXTUALIZE_REF, "contextualization-v1", 1, CONTEXTUALIZATION_SCHEMA_V1


def _load_trusted_assets(task_ref: str) -> tuple[str, str, int, int] | None:
    try:
        return (
            load_prompt(_CONTROL_REF),
            load_prompt(task_ref),
            prompt_reference_version(_CONTROL_REF),
            prompt_reference_version(task_ref),
        )
    except (OSError, PromptNotFoundError, UnicodeError):
        return None


def _payload(request: ContextualizationRequest | GenerationRequest) -> dict[str, object]:
    payload: dict[str, object] = {
        "question": request.question,
        "history": [{"role": turn.role.value, "content": turn.content} for turn in request.history],
        "evidence": [],
    }
    if isinstance(request, GenerationRequest):
        payload["resolved_query"] = request.resolved_query
        payload["evidence"] = evidence_payload(
            request.evidence,
            contextual=request.profile.evidence_budget is not None,
        )
        if request.profile.response_schema_version == 3 and request.numeric_catalogue is not None:
            catalogue = request.numeric_catalogue
            payload["numeric_catalogue"] = {
                "request_id": str(catalogue.request_id),
                "policy_ref": catalogue.policy_ref,
                "catalogue_digest": catalogue.digest,
                "tokens": [
                    {
                        "token_id": t.token_id,
                        "evidence_id": str(t.evidence_id),
                        "start": t.start,
                        "end": t.end,
                        "unit": t.unit,
                        "value": str(t.value),
                    }
                    for t in catalogue.tokens
                ],
            }
    return payload


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _raise_invalid_profile() -> None:
    raise CodexPromptConfigurationError("The configured Codex prompt profile is not available.")


__all__ = [
    "CodexPromptConfigurationError",
    "CodexPromptEnvelope",
    "build_codex_prompt",
]
