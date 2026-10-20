"""Observe a grid inside one PDF chunk, without assigning semantic table roles.

Neither bbox alignment nor OCR cell coordinates prove table identity/completeness.
An exact lexical cell anchor permits a whole-chunk context candidate, not an answer.
No units, columns, prose, notes or unresolved references are removed or rewritten.
"""

import re
import unicodedata
from dataclasses import dataclass
from math import isfinite

from ai_workshop.labs.rag.documents.domain import EvidenceUnit
from ai_workshop.labs.rag.highlighting.domain import EvidenceSource
from ai_workshop.labs.rag.highlighting.service import _provenance_warnings


@dataclass(frozen=True, slots=True)
class GridCandidate:
    eligible: bool
    reason: str


def inspect_grid_candidate(
    query: str, source: EvidenceSource, units: tuple[EvidenceUnit, ...],
) -> GridCandidate:
    """Inspect preserved coordinates only; the caller owns ranking, ACL and budget.

All context is scoped to the supplied chunk. External notes/reference targets may
be missing. A lexical match may name a value rather than a subject/header; neither
rule existence nor support for the requested property is inferred here.
"""
    if source.media_type != "application/pdf":
        return GridCandidate(False, "unsupported_source")
    original = source.chunk.evidence_units
    if (not units or len(units) != len(original)
            or len({u.id for u in units}) != len(units)
            or {u.id: u for u in units} != {u.id: u for u in original}
            or any(_provenance_warnings(source, u) or not u.text.strip() for u in units)):
        return GridCandidate(False, "incomplete_source")
    if len({(u.location.page, u.location.source_kind, u.location.source_part,
             u.location.image_sha256) for u in units}) != 1:
        return GridCandidate(False, "ambiguous_structure")
    rows: dict[tuple[float, float], list[EvidenceUnit]] = {}
    for unit in units:
        box = unit.location.bbox
        if (box is None or not all(isfinite(v) for v in box)
                or box[0] >= box[2] or box[1] >= box[3]):
            return GridCandidate(False, "ambiguous_structure")
        rows.setdefault((box[1], box[3]), []).append(unit)
    bands = sorted(rows)
    if any(left[1] > right[0] for left, right in zip(bands, bands[1:], strict=False)):
        return GridCandidate(False, "ambiguous_structure")
    ordered = [sorted(rows[band], key=_left) for band in bands]
    grid_indices = [i for i, row in enumerate(ordered) if len(row) > 1]
    if not grid_indices:
        return GridCandidate(False, "missing_structure")
    if (len(grid_indices) < 2
            or grid_indices != list(range(grid_indices[0], grid_indices[-1] + 1))):
        return GridCandidate(False, "ambiguous_structure")
    grid = [ordered[i] for i in grid_indices]
    columns = [_left(cell) for cell in grid[0]]
    for row in grid:
        if [_left(cell) for cell in row] != columns:
            return GridCandidate(False, "ambiguous_structure")
        for left, right in zip(row, row[1:], strict=False):
            box = left.location.bbox
            assert box is not None
            if box[2] >= _left(right):
                return GridCandidate(False, "ambiguous_structure")
    has_coordinates = any(u.location.table_cell is not None for u in units)
    if has_coordinates and not _consistent_cell_coordinates(grid, units):
        # Never ignore partial/contradictory annotations and silently use bbox mode.
        return GridCandidate(False, "ambiguous_structure")
    if not any(_whole_cell_match(query, cell.text) for row in grid for cell in row):
        return GridCandidate(False, "no_cell_match")
    basis = "cell_coordinates" if has_coordinates else "bbox_grid"
    return GridCandidate(True, f"{basis}_match")


def _left(unit: EvidenceUnit) -> float:
    box = unit.location.bbox
    assert box is not None
    return box[0]


def _consistent_cell_coordinates(
    grid: list[list[EvidenceUnit]], units: tuple[EvidenceUnit, ...],
) -> bool:
    grid_ids = {cell.id for row in grid for cell in row}
    if any(u.location.table_cell is not None and u.id not in grid_ids for u in units):
        return False
    positions: list[list[tuple[int, int]]] = []
    for row in grid:
        coordinates = []
        for unit in row:
            cell = unit.location.table_cell
            if (cell is None or type(cell.row) is not int or type(cell.column) is not int
                    or cell.row_span != 1 or cell.column_span != 1):
                return False
            coordinates.append((cell.row, cell.column))
        positions.append(coordinates)
    start_row, start_column = positions[0][0]
    return all(position == (start_row + r, start_column + c)
               for r, row in enumerate(positions) for c, position in enumerate(row))


def _whole_cell_match(query: str, text: str) -> bool:
    def normalized(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())

    cell = normalized(text)
    if not any(character.isalpha() for character in cell):
        return False
    # No synonym/morphology/header vocabulary. Values like T+2 can also match;
    # this supplies context, never a semantic assertion about the requested fact.
    return re.search(r"(?<![\w-])" + re.escape(cell) + r"(?![\w-])",
                     normalized(query)) is not None
