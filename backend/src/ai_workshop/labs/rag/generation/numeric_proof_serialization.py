"""One canonical private payload for generation, storage and evaluation."""

import hashlib
import json
from dataclasses import asdict

from .numeric_proof_types import (
    NumericValidationBinding,
    ValidatedGenerationPayload,
    ValidatedNumericClaim,
)


def canonical_numeric_payload(payload: ValidatedGenerationPayload) -> bytes:
    return json.dumps(
        asdict(payload),
        default=str,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def numeric_payload_digest(payload: ValidatedGenerationPayload) -> str:
    return hashlib.sha256(canonical_numeric_payload(payload)).hexdigest()


def rebuild_validated_numeric_payload(
    *,
    status: str,
    answer: str | None,
    claims: tuple[ValidatedNumericClaim, ...],
    binding: NumericValidationBinding,
) -> ValidatedGenerationPayload:
    if (
        binding.schema_version != 3
        or status not in ("answered", "insufficient_evidence")
        or (status == "insufficient_evidence" and (answer is not None or claims))
        or (status == "answered" and (not claims or answer != " ".join(c.text for c in claims)))
        or tuple(c.claim_index for c in claims) != tuple(range(len(claims)))
    ):
        raise ValueError("numeric_validation_binding_invalid")
    return ValidatedGenerationPayload(
        3,
        status,
        answer,
        claims,
        binding.request_id,
        binding.configuration_version_id,
        binding.generation_profile_id,
        binding.policy_ref,
        binding.policy_digest,
        binding.catalogue_digest,
    )
