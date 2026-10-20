"""Conservative runtime projection of an unambiguous PDF payment timing table.

This is a selection view, not reconstructed parser metadata. Original units and
all prose surrounding the table survive; only unrelated product columns leave.
Unsupported questions or layouts keep the ordinary whole-chunk selection path.
"""

import re
import unicodedata
from math import isfinite

from ai_workshop.labs.rag.documents.domain import EvidenceUnit
from ai_workshop.labs.rag.highlighting.domain import EvidenceSource

_HEADER_LABELS = frozenset({"항목", "구분", "item", "attribute"})
_PAYMENT_LABELS = frozenset({"대금 지급일", "환매 대금 지급일", "환매대금 지급일",
                             "payment date", "payment timing", "payout date"})
# Deliberately bounded lexical intent: this does not infer an answer or change
# keyword/semantic scores. Other intents continue through existing selection.
_ACTION = re.compile(r"환매|현금화|인출|\bredeem\w*\b|\bredemption\b|\bcash out\b|\bwithdraw\w*\b")
_TIME = re.compile(r"언제|며칠|몇\s*일|지급일|\bwhen\b|\bhow (?:many days|long)\b")
_RECEIVE = re.compile(
    r"(?:돈|대금|현금).*받|대금.*지급|\breceive\b.*\b(?:money|payment|proceeds)\b"
)
_UNSUPPORTED = re.compile(
    r"않|아니|아닌|없|못|말고|안\s*(?:받|하|되|주|지급|환매)|비교|다른\s*상품|수익|수수료|가격|이자|"
    r"\b(?:not|never|without|compare|versus|other|rate|price|fee|interest)\b|n['’]t\b"
)
_REFERENCE = re.compile(r"동일|상동|같[음은다]|참조|좌측|우측|왼쪽|오른쪽|〃|″|"
                        r"\b(?:same|ditto|above|below|refer|see)\b")


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _detached_page_footer(
    row: list[EvidenceUnit], table: list[list[EvidenceUnit]], prose: list[EvidenceUnit],
) -> bool:
    """Recognize a detached final page counter, never discard its companion text.

    A page-like value alone is not enough: require smaller text, a separated
    baseline, the prose margin left of the grid, and a counter right of it.
    Without page dimensions/semantic table metadata, other layouts stay unknown.
    """
    if len(row) != 2 or not table or not prose:
        return False
    counter = re.fullmatch(r"([0-9]{1,6})\s*/\s*([0-9]{1,6})", _normalized(row[1].text))
    if (counter is None or int(counter[1]) != row[1].location.page
            or not 0 < int(counter[1]) <= int(counter[2])):
        return False
    left, right = (unit.location.bbox for unit in row)
    assert left is not None and right is not None
    grid_boxes = [u.location.bbox for cells in table for u in cells]
    body_boxes = [u.location.bbox for u in prose]
    # All boxes have already passed the source-wide geometry checks.
    grid = [box for box in grid_boxes if box is not None]
    body = [box for box in body_boxes if box is not None]
    height = left[3] - left[1]
    return (
        all(box[0] == left[0] for box in body)
        and left[0] < min(box[0] for box in grid)
        and left[2] < right[0]
        and right[0] > max(box[2] for box in grid)
        and height < min(box[3] - box[1] for box in grid + body)
        and left[1] - body[-1][3] > 2 * max(box[3] - box[1] for box in body)
    )


def payment_table_units(
    query: str, source: EvidenceSource, units: tuple[EvidenceUnit, ...],
) -> tuple[EvidenceUnit, ...] | None:
    """Return an indivisible target-column bundle only for a strict regular grid."""
    query = _normalized(query)
    if (source.media_type != "application/pdf" or _UNSUPPORTED.search(query)
            or not all(pattern.search(query) for pattern in (_ACTION, _TIME, _RECEIVE))):
        return None
    # Missing/invalid source units must not become an excuse to lose a condition.
    if {u.id for u in units} != {u.id for u in source.chunk.evidence_units}:
        return None
    if not units or len({u.location.page for u in units}) != 1:
        return None
    rows: list[list[EvidenceUnit]] = []
    for unit in units:
        box = unit.location.bbox
        if (box is None or not all(isfinite(v) for v in box)
                or box[0] >= box[2] or box[1] >= box[3]
                or unit.location.table_cell is not None):
            # Annotated/merged tables need their own metadata-aware contract.
            return None
        if rows:
            previous = rows[-1][0].location.bbox
            assert previous is not None
            if box[1:4:2] == previous[1:4:2]:
                rows[-1].append(unit)
                continue
            if box[1] < previous[3]:
                return None
        rows.append([unit])
    headers = [i for i, row in enumerate(rows)
               if len(row) >= 3 and _normalized(row[0].text) in _HEADER_LABELS]
    if len(headers) != 1 or headers[0] == 0:
        return None
    start = headers[0]
    header = rows[start]
    labels = [_normalized(u.text) for u in header]
    if len(set(labels)) != len(labels):
        return None
    targets = [column for column, label in enumerate(labels[1:], 1)
               if re.search(r"(?<![\w-])" + re.escape(label)
                            + r"(?=(?:을|를|은|는|이|가|의|에|와|과)?(?:\W|$))", query)]
    if len(targets) != 1:
        return None
    column = targets[0]
    table: list[list[EvidenceUnit]] = []
    prose: list[EvidenceUnit] = []
    for row_index, row in enumerate(rows[start:], start):
        if len(row) == 1:
            prose.append(row[0])
            continue
        if prose:
            if row_index == len(rows) - 1 and _detached_page_footer(row, table, prose):
                break
            return None
        if len(row) != len(header):
            return None
        for index, cell in enumerate(row):
            box = cell.location.bbox
            reference = header[index].location.bbox
            assert box is not None and reference is not None
            if box[0] != reference[0]:
                return None
            if index:
                prior = row[index - 1].location.bbox
                assert prior is not None
                if prior[2] >= box[0]:
                    return None
        table.append(row)
    if (any(len(row) != 1 for row in rows[:start]) or len(table) < 2
            or sum(_normalized(row[0].text) in _PAYMENT_LABELS for row in table[1:]) != 1):
        return None
    excluded = {cell.id for row in table for index, cell in enumerate(row)
                if index not in (0, column)}
    retained = tuple(unit for unit in units if unit.id not in excluded)
    if any(_REFERENCE.search(_normalized(unit.text)) for unit in retained):
        return None
    omitted_labels = [label for index, label in enumerate(labels) if index not in (0, column)]
    if any(label in _normalized(row[column].text)
           for row in table[1:] for label in omitted_labels):
        return None
    return retained
