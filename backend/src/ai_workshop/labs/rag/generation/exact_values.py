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
    return values
