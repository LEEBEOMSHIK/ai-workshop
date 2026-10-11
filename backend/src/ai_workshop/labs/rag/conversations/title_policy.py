"""Conservative local grammar extraction from the first question alone."""

import re
from dataclasses import dataclass
from typing import Literal

POLICY_VERSION = "first-question-local-v1"
FALLBACK_TITLE = "새 대화"
REDACTED_TITLE = "접근할 수 없는 대화"


@dataclass(frozen=True)
class DerivedTitle:
    title: str
    derivation: Literal["extracted", "preserved", "fallback"]
    policy_version: str = POLICY_VERSION
    error_code: str | None = None


def derive_title(question: str, max_length: int) -> DerivedTitle:
    """Never truncate, infer answers, or select one request from a compound question."""
    try:
        candidate = " ".join(question.split())
        if not candidate or re.match(
            r"^(그건|그것|이건|이것|그거|이거)(?:\s|은|는|이|가)", candidate
        ):
            return DerivedTitle(FALLBACK_TITLE, "fallback", error_code="title_subject_uncertain")
        derivation: Literal["extracted", "preserved", "fallback"] = "preserved"
        # Quoted/code fragments, conditions, negatives and multiple sentences are
        # retained. A grammar transform must not silently narrow the user's intent.
        uncertain = re.search(r"[`\"'\n]|하지|않|못|없이|경우|만약|그리고|[.!?].+", candidate)
        if uncertain is None:
            request = re.fullmatch(
                r"(.+?)(을|를)(\s+각각)?\s+(설명|비교)해\s*주(?:세요|십시오)[?.]?", candidate
            )
            timing = re.fullmatch(r"(.+?)(?:이|가)\s+언제(?:야|인가요|예요|입니까)[?]?", candidate)
            if request:
                particle = request[2] if request[3] else ""
                candidate = f"{request[1]}{particle}{request[3] or ''} {request[4]}"
                derivation = "extracted"
            elif timing:
                candidate = re.sub(r"(\S+)의\s+", r"\1 ", timing[1]) + " 확인"
                derivation = "extracted"
        if len(candidate) > max_length:
            return DerivedTitle(FALLBACK_TITLE, "fallback", error_code="title_length_exceeded")
        return DerivedTitle(candidate, derivation)
    except Exception:
        # A title failure never changes the acceptance/generation contract.
        return DerivedTitle(FALLBACK_TITLE, "fallback", error_code="title_derivation_failed")
