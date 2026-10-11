"""Immutable arithmetic contract; no model or deployment choices."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NumericProofPolicy:
    ref: str = "source-numeric-proof-v1"
    max_claims: int = 32
    max_calculations_per_claim: int = 32
    max_calculations: int = 128
    max_tokens: int = 512
    max_digits: int = 30
    precision: int = 64

    def definition(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "max_claims": self.max_claims,
            "max_calculations_per_claim": self.max_calculations_per_claim,
            "max_calculations": self.max_calculations,
            "max_tokens": self.max_tokens,
            "max_digits": self.max_digits,
            "precision": self.precision,
            "operations": {
                "percentage_point_difference": {
                    "arity": 2,
                    "input": "%",
                    "output": "%p",
                    "order": "left-minus-right",
                },
                "convert_krw_unit": {
                    "arity": 1,
                    "scales": {"원": 1, "만원": 10000, "억원": 100000000},
                },
            },
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.definition(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()


SOURCE_NUMERIC_PROOF_V1 = NumericProofPolicy()


def resolve_numeric_proof_policy(config: Mapping[str, object]) -> NumericProofPolicy | None:
    settings = config.get("generation")
    if settings is None:
        if config.get("prompt_ref") == "rag-codex-answer-v6":
            raise ValueError("numeric_proof_profile_invalid")
        return None
    if not isinstance(settings, Mapping):
        raise ValueError("numeric_proof_profile_invalid")
    schema = settings.get("response_schema_version")
    ref = settings.get("numeric_proof_policy_ref")
    if schema == 3 or config.get("prompt_ref") == "rag-codex-answer-v6":
        if (
            type(schema) is not int
            or schema != 3
            or ref != SOURCE_NUMERIC_PROOF_V1.ref
            or config.get("prompt_ref") != "rag-codex-answer-v6"
        ):
            raise ValueError("numeric_proof_profile_invalid")
        return SOURCE_NUMERIC_PROOF_V1
    if "numeric_proof_policy_ref" in settings:
        raise ValueError("numeric_proof_profile_invalid")
    return None
