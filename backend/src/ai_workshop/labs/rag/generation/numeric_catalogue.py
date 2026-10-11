"""Build request-scoped occurrences from already-authorized evidence."""

import hashlib
import json
import re
from dataclasses import asdict
from decimal import Decimal
from uuid import UUID

from .domain import GenerationProfile, GroundingEvidence
from .exact_values import _GROUPED_NUMBER, _UNIT_ALIASES, _VALUE
from .numeric_proof_types import SourceValueCatalogue, SourceValueToken


def whole_numeric_occurrence(text: str, start: int) -> bool:
    # The legacy scanner permits suffixes of identifiers/scientific/fractional
    # literals. A v3 operand/result must start a complete supported literal.
    return start == 0 or text[start - 1] not in (
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_,./^*+−-"
    )


def numeric_occurrences(text: str, *, max_digits: int) -> tuple[tuple[int, int, str, Decimal], ...]:
    result: list[tuple[int, int, str, Decimal]] = []
    for match in _VALUE.finditer(text):
        if match.group("date") is not None:
            continue
        if not whole_numeric_occurrence(text, match.start()):
            continue
        number = re.sub(r"\s+", "", match.group("number")).replace("−", "-")
        if "," in number and _GROUPED_NUMBER.fullmatch(number) is None:
            continue
        if sum(character.isdigit() for character in number) > max_digits:
            raise ValueError("calculation_limit_exceeded")
        unit = re.sub(r"\s+", "", match.group("unit")).replace("％", "%")
        unit = _UNIT_ALIASES.get(unit, unit)
        result.append((match.start(), match.end(), unit, Decimal(number.replace(",", ""))))
    return tuple(result)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")
        ).encode()
    ).hexdigest()


def build_source_value_catalogue(
    evidence: tuple[GroundingEvidence, ...],
    *,
    request_id: UUID,
    configuration_version_id: UUID,
    profile: GenerationProfile,
) -> SourceValueCatalogue:
    policy = profile.numeric_proof_policy
    if profile.response_schema_version != 3 or policy is None:
        raise ValueError("numeric_proof_profile_invalid")
    if len({item.evidence_id for item in evidence}) != len(evidence):
        raise ValueError("calculation_operand_not_supported")
    context = {
        "request_id": str(request_id),
        "configuration_version_id": str(configuration_version_id),
        "profile_id": str(profile.profile_id),
        "policy_digest": policy.digest,
        "evidence_digest": _digest([asdict(item) for item in evidence]),
    }
    tokens: list[SourceValueToken] = []
    for item in evidence:
        for start, end, unit, value in numeric_occurrences(item.text, max_digits=policy.max_digits):
            if unit not in ("%", "원", "만원", "억원"):
                continue
            identity = _digest(
                {**context, "evidence_id": str(item.evidence_id), "start": start, "end": end}
            )
            tokens.append(SourceValueToken(identity, item.evidence_id, start, end, unit, value))
            if len(tokens) > policy.max_tokens:
                raise ValueError("calculation_limit_exceeded")
    digest = _digest({**context, "tokens": [asdict(token) for token in tokens]})
    return SourceValueCatalogue(
        request_id,
        configuration_version_id,
        profile.profile_id,
        policy.ref,
        policy.digest,
        context["evidence_digest"],
        digest,
        tuple(tokens),
        tuple(item.evidence_id for item in evidence),
    )
