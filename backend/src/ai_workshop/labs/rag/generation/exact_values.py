"""Lexical value equivalence only; never infer or convert financial units."""

import re
from datetime import date
from decimal import Decimal

_VALUE = re.compile(
    r"(?<![\d.])(?:"
    r"(?P<date>\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일|"
    r"\d{4}-\d{1,2}-\d{1,2})(?!\d)|"
    r"(?P<number>(?:[+\-−]\s*)?(?:\d[\d,]*(?:\.\d+)?|\.\d+))\s*"
    r"(?P<unit>[%％]\s*[pP]|[%％]\s*포인트|퍼센트\s*포인트|퍼센트|[%％]|"
    r"억\s*원|만\s*원|원|년|개월|회|명)"
    r")"
)
_GROUPED_NUMBER = re.compile(r"[+\-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_UNIT_ALIASES = {
    "퍼센트": "%",
    "퍼센트포인트": "%p",
    "%포인트": "%p",
    "%P": "%p",
}
# Keep _VALUE unchanged: schema3 uses its established numeric catalogue and
# calculation proof contract. These extra lexical checks belong to exact support.
_SHORT_VALUE = re.compile(
    r"(?<![A-Za-z0-9_.,/+\-−])[0-9]+-[0-9]+"
    r"(?![A-Za-z0-9_/+\-−]|[.,][0-9])"
)
_RELATIVE_OFFSET = re.compile(
    r"(?<![A-Za-z0-9_.,/+\-−])(?P<base>[A-Za-z])\s*"
    r"(?P<sign>[+\-])\s*(?P<offset>[0-9]+)"
    r"(?![A-Za-z0-9_/+\-−]|[.,][0-9])"
    r"(?:\s*(?P<business_days>영업일)(?![A-Za-z0-9_]))?"
)
_BUSINESS_DAYS = re.compile(
    r"(?<![A-Za-z0-9_.,/+\-−])(?P<number>(?:[+\-−]\s*)?[0-9]+)"
    r"\s*영업일(?![A-Za-z0-9_])"
)
_ExactValue = tuple[str, date | Decimal | str]


def exact_values(text: str) -> set[_ExactValue]:
    values: set[_ExactValue] = set()
    for match in _VALUE.finditer(text):
        calendar = match.group("date")
        if calendar is not None:
            year, month, day = (int(part) for part in re.findall(r"\d+", calendar))
            try:
                values.add(("date", date(year, month, day)))
            except ValueError:
                # Preserve invalid dates literally rather than silently repairing them.
                values.add(("literal-date", calendar))
            continue
        number = re.sub(r"\s+", "", match.group("number")).replace("−", "-")
        unit = re.sub(r"\s+", "", match.group("unit")).replace("％", "%")
        unit = _UNIT_ALIASES.get(unit, unit)
        if "," in number and _GROUPED_NUMBER.fullmatch(number) is None:
            values.add(("literal-number:" + unit, number))
            continue
        values.add((unit, Decimal(number.replace(",", ""))))
    # A two-part number may be a date or a range. Preserve its spelling without
    # assigning calendar meaning or treating it as part of a longer identifier.
    values.update(("literal-short-value", match.group()) for match in _SHORT_VALUE.finditer(text))
    for match in _RELATIVE_OFFSET.finditer(text):
        sign = match.group("sign")
        values.add(
            ("relative-offset:" + match.group("base") + sign, Decimal(match.group("offset")))
        )
        if match.group("business_days") is not None:
            values.add(("영업일", Decimal(sign + match.group("offset"))))
    for match in _BUSINESS_DAYS.finditer(text):
        # Do not salvage the final integer from malformed spaced signs, such
        # as '-- 5 영업일'. A complete signed occurrence was already consumed.
        if text[: match.start()].rstrip(" \t").endswith(("+", "-", "−")):
            continue
        number = re.sub(r"\s+", "", match.group("number")).replace("−", "-")
        values.add(("영업일", Decimal(number)))
    return values
