"""Conservative source-defined business-day support for schema 1/2 citations.

This is a closed grammar, not natural-language entailment. A stated definition,
one cited PDF target header, and its literal attribute/value row must agree.
Geometry corroborates the text; it cannot supply a unit, anchor, or attribute.
Unsupported grammar and incomplete or ambiguous relations supply no values.
"""

import re
from decimal import Decimal
from math import isfinite

from ai_workshop.labs.rag.generation.domain import GroundingEvidence

_VALUE_ROW = re.compile(
    r"(?P<anchor>[가-힣]+) (?P<base>[A-Za-z])\+(?P<days>[1-9][0-9]*) "
    r"(?P<attribute>[가-힣]+(?: [가-힣]+)*)"
)
_DEFINITION = re.compile(
    r"(?:영업일은 [가-힣A-Za-z0-9 ]+ 달력상 업무일이다\. )?"
    r"(?P<base>[A-Za-z])(?:는|은) (?P<anchor>[가-힣]+)(?:이며|이고), "
    r"(?P=base)\+N은 (?P=anchor) 다음 영업일부터 N일을 센다\."
)
_HEADER = re.compile(r"[가-힣A-Za-z0-9]+(?:[ _-][가-힣A-Za-z0-9]+)*")
_AMBIGUOUS = re.compile(r"않|아니|아닌|없|제외|예외|경우|단,|또는|혹은")


def defined_business_day_values(
    claim: str, cited: tuple[GroundingEvidence, ...],
) -> set[tuple[str, Decimal]]:
    """Supply only the period explicitly proved by this claim's cited sources.

    The original strings and citation identities are never modified. No uncited
    grounding or question is accepted here; an omitted target is not inferred from
    the question. The existing validator remains responsible for other exact values.
    """
    if not _valid_source(cited):
        return set()
    candidates = [(item, _VALUE_ROW.fullmatch(_text(item.text))) for item in cited]
    values = [(item, match) for item, match in candidates if match is not None]
    if len(values) != 1:
        return set()
    value, match = values[0]
    value_box = _box(value)
    labels = [item for item in cited if (
        _box(item)[1:4:2] == value_box[1:4:2]
        and _box(item)[2] < value_box[0]
        and item.ordinal + 1 == value.ordinal
        and item.char_end == value.char_start
    )]
    if len(labels) != 1:
        return set()
    label = labels[0]
    attribute = match["attribute"]
    if _text(label.text) not in {attribute, "적용 " + attribute}:
        return set()
    headers = [item for item in cited if (
        _box(item)[0] == value_box[0] and _box(item)[3] < _box(label)[1]
        and item.ordinal < label.ordinal and _HEADER.fullmatch(_text(item.text))
        and not _AMBIGUOUS.search(item.text)
    )]
    if len(headers) != 1:
        return set()
    header = headers[0]
    table_ids = {item.evidence_id for item in (header, label, value)}
    definition = tuple(item for item in cited if item.evidence_id not in table_ids)
    if not _definition_matches(definition, header, label, match["base"], match["anchor"]):
        return set()
    base, anchor, days = (re.escape(match[key]) for key in ("base", "anchor", "days"))
    product, attribute = re.escape(_text(header.text)), re.escape(attribute)
    # The paraphrase explicitly retains the same base, counting start, offset,
    # and attribute. Arbitrary extra clauses cannot inherit this proof.
    claim_pattern = (
        rf"(?:두 경우 모두 |{product}(?:의|은|는) )?"
        rf"{anchor}(?: {base}의)? 다음 영업일부터 {days}\s*영업일을 센 "
        rf"{base}\+{days}의 {attribute}(?:을|를) 적용합니다\.?"
    )
    if re.fullmatch(claim_pattern, _text(claim)) is None:
        return set()
    return {("영업일", Decimal(match["days"]))}


def _text(text: str) -> str:
    return " ".join(text.split())


def _box(item: GroundingEvidence) -> tuple[float, float, float, float]:
    # All callers are guarded by _valid_source; missing boxes never reach here.
    assert item.bbox is not None
    return item.bbox


def _scope(item: GroundingEvidence) -> tuple[object, ...]:
    return (
        item.document_id, item.asset_version_id, item.projection_id, item.chunk_id,
        item.page, item.source_kind, item.source_part, item.section_path,
    )


def _valid_source(cited: tuple[GroundingEvidence, ...]) -> bool:
    if not cited or len({item.evidence_id for item in cited}) != len(cited):
        return False
    if len({_scope(item) for item in cited}) != 1:
        return False
    for index, item in enumerate(cited):
        box = item.bbox
        if (
            item.source_kind != "pdf_page" or item.page is None or item.page < 1
            or item.projection_id is None or item.chunk_id is None
            or item.table_cell is not None or item.ordinal < 0 or item.char_start < 0
            or item.char_end - item.char_start != len(item.text) or not item.text
            or box is None or not all(isfinite(number) for number in box)
            or box[0] >= box[2] or box[1] >= box[3]
        ):
            return False
        if index and (
            cited[index - 1].ordinal >= item.ordinal
            or cited[index - 1].char_end > item.char_start
        ):
            return False
    return True


def _definition_matches(
    definition: tuple[GroundingEvidence, ...], header: GroundingEvidence,
    label: GroundingEvidence, base: str, anchor: str,
) -> bool:
    if not definition:
        return False
    for index, item in enumerate(definition):
        if (
            item.ordinal >= header.ordinal or _box(item)[3] >= _box(header)[1]
            or _box(item)[0] >= _box(label)[0]
        ):
            return False
        if index:
            previous = definition[index - 1]
            if (
                previous.ordinal + 1 != item.ordinal or previous.char_end != item.char_start
                or _box(previous)[0] != _box(item)[0] or _box(previous)[3] >= _box(item)[1]
            ):
                return False
    joined = _text(" ".join(item.text for item in definition))
    match = _DEFINITION.fullmatch(joined)
    return bool(
        match and match["base"] == base and match["anchor"] == anchor
        and not _AMBIGUOUS.search(joined)
    )
