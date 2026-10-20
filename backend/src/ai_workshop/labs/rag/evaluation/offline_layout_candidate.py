"""Prepare an unexecuted geometry-only variant from a complete local v5 capture.

This is an offline experiment, not a runtime profile or a semantic table parser.
Never reorder source fragments or infer headers, subjects, rules, or conditions.
"""

from collections import Counter
from dataclasses import dataclass
from difflib import unified_diff
from math import isfinite
from typing import Literal, cast

from pydantic import JsonValue

from ai_workshop.labs.rag.evaluation.offline_input_diagnosis import (
    Capture,
    JsonObject,
    Value,
    capture_body,
    content,
    digest,
    encode,
    message,
    object_value,
    parse_object,
)

LAYOUT_NOTICE = (
    "Rows list original fragment UUIDs in observed left-to-right, top-to-bottom alignment. "
    "They describe selected fragments only, not a complete table. Columns and rows have "
    "no assigned semantic roles: do not assume a header, subject, rule, or condition. "
    "Read original fragment text and surrounding evidence to establish meaning. "
    "Cite original fragment UUIDs; a grid or source_ref is not a citation."
)


class LayoutCandidate(Value):
    condition: Literal["D"] = "D"
    execution_status: Literal["not_run"] = "not_run"
    preparation_status: Literal["prepared", "no_supported_grid"]
    source_sha256: str
    request_json: str
    sha256: str
    body_bytes: int
    grid_count: int
    diff: str


@dataclass(frozen=True, slots=True)
class _Cell:
    identity: str
    box: tuple[float, float, float, float]


def _rows(units: list[JsonValue]) -> list[list[_Cell]]:
    """Fail closed for inconsistent order/coordinates anywhere in this source run."""
    rows: list[list[_Cell]] = []
    previous_ordinal, previous_end = -1, 0
    for value in units:
        unit = object_value(value)
        box, offsets, ordinal = unit.get("bbox"), unit.get("char_range"), unit.get("ordinal")
        if (not isinstance(box, list) or len(box) != 4
                or any(type(v) not in (int, float) for v in box)
                or not isinstance(offsets, list) or len(offsets) != 2
                or any(type(v) is not int for v in offsets)
                or type(ordinal) is not int or ordinal <= previous_ordinal):
            return []
        numbers = cast(list[float], box)
        start, end = cast(list[int], offsets)
        if (not all(isfinite(v) for v in numbers) or numbers[0] >= numbers[2]
                or numbers[1] >= numbers[3] or start < previous_end or start >= end):
            return []
        cell = _Cell(str(unit["evidence_id"]), (numbers[0], numbers[1], numbers[2], numbers[3]))
        if rows:
            previous = rows[-1][-1]
            if cell.box[1::2] == previous.box[1::2]:
                if previous.box[2] >= cell.box[0]:
                    return []
                rows[-1].append(cell)
            elif cell.box[1] >= previous.box[3]:
                rows.append([cell])
            else:
                return []
        else:
            rows.append([cell])
        previous_ordinal, previous_end = ordinal, end
    return rows


def _grids(rows: list[list[_Cell]], reference: int) -> list[JsonValue]:
    result: list[JsonValue] = []
    pending: list[JsonValue] = []
    columns: tuple[float, ...] = ()
    for row in [*rows, []]:
        signature = tuple(cell.box[0] for cell in row) if len(row) > 1 else ()
        if not signature or signature != columns:
            if len(pending) > 1:
                result.append({"source_ref": reference, "rows": pending})
            pending = []
        if signature:
            pending.append([cell.identity for cell in row])
        columns = signature
    return result


def _layout(payload: JsonObject) -> JsonObject:
    sources = cast(list[JsonValue], payload["evidence_sources"])
    blocks = cast(list[JsonValue], payload["evidence_blocks"])
    runs: list[tuple[int, list[JsonValue]]] = []
    for raw_block in blocks:
        block = object_value(raw_block)
        reference = cast(int, block["source_ref"])
        units = cast(list[JsonValue], block["fragments"])
        if runs and reference == runs[-1][0]:
            runs[-1][1].extend(units)
        else:
            runs.append((reference, list(units)))
    grids: list[JsonValue] = []
    occurrences = Counter(reference for reference, _ in runs)
    for reference, units in runs:
        source = object_value(sources[reference])
        page = source.get("page")
        # OCR/explicit cell layouts need richer table/image identity first.
        if (occurrences[reference] != 1 or source.get("source_kind") != "pdf_page"
                or type(page) is not int or page < 1
                or source.get("table_cell") is not None):
            continue
        grids.extend(_grids(_rows(units), reference))
    return {"version": 1, "basis": "selected_fragment_geometry_only",
            "semantic_roles": "not_assigned", "coverage": "selected_fragments_only",
            "notice": LAYOUT_NOTICE, "grids": grids}


def prepare_layout_candidate(source: Capture) -> LayoutCandidate:
    body = capture_body(source)
    original_content = content(body, 1)
    payload = parse_object(original_content)
    layout = _layout(payload)
    count = len(cast(list[JsonValue], layout["grids"]))
    raw, diff = source.request_json, ""
    if count:
        payload["layout_hints"] = layout
        revised_content = encode(payload)
        message(body, 1)["content"] = revised_content
        raw = encode(body)
        diff = "\n".join(unified_diff(original_content.splitlines(),
                                     revised_content.splitlines(), fromfile="A", tofile="D",
                                     lineterm=""))
    return LayoutCandidate(
        preparation_status="prepared" if count else "no_supported_grid",
        source_sha256=source.sha256, request_json=raw, sha256=digest(raw),
        body_bytes=len(raw.encode("utf-8")), grid_count=count, diff=diff,
    )


def verify_layout_candidate(source: Capture, candidate: LayoutCandidate) -> None:
    """Reject a rehashed edit, inferred answer annotation, or changed model option."""
    if candidate != prepare_layout_candidate(source):
        raise ValueError("Layout candidate differs from the preserved source and derived hints.")
