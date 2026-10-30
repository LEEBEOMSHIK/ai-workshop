"""Unexecuted E variant: repeat exact source text next to D's grid UUIDs.

No selection, semantic roles, rewritten facts, model execution, or live defaults.
Repetition/length/emphasis change together; this does not isolate model attention.
"""

from difflib import unified_diff
from typing import Literal, cast

from pydantic import JsonValue

from ai_workshop.labs.rag.evaluation.offline_input_diagnosis import (
    Capture,
    Value,
    content,
    digest,
    encode,
    fragments,
    message,
    object_value,
    parse_object,
)
from ai_workshop.labs.rag.evaluation.offline_layout_candidate import prepare_layout_candidate


class ReadableLayoutCandidate(Value):
    condition: Literal["E"] = "E"
    execution_status: Literal["not_run"] = "not_run"
    preparation_status: Literal["prepared", "no_supported_grid"]
    source_sha256: str
    baseline_sha256: str
    request_json: str
    sha256: str
    body_bytes: int
    grid_count: int
    repeated_fragment_count: int
    repeated_text_bytes: int
    diff: str


def prepare_readable_layout_candidate(source: Capture) -> ReadableLayoutCandidate:
    # Derive, never accept a caller-supplied grid or join source text by its value.
    baseline = prepare_layout_candidate(source)
    raw, diff = baseline.request_json, ""
    repeated_count = repeated_bytes = 0
    if baseline.grid_count:
        body = parse_object(raw)
        original_content = content(body, 1)
        payload = parse_object(original_content)
        by_id = {str(f["evidence_id"]): f for f in fragments(payload)}
        hints = object_value(payload["layout_hints"])
        for raw_grid in cast(list[JsonValue], hints["grids"]):
            grid = object_value(raw_grid)
            readable_rows: list[JsonValue] = []
            for row in cast(list[list[str]], grid["rows"]):
                readable_cells: list[JsonValue] = []
                for identity in row:
                    text = cast(str, by_id[identity]["text"])
                    readable_cells.append({"evidence_id": identity, "text": text})
                    repeated_count += 1
                    repeated_bytes += len(text.encode("utf-8"))
                readable_rows.append(readable_cells)
            grid["readable_rows"] = readable_rows
        revised_content = encode(payload)
        message(body, 1)["content"] = revised_content
        raw = encode(body)
        diff = "\n".join(unified_diff(original_content.splitlines(),
                                     revised_content.splitlines(), fromfile="D", tofile="E",
                                     lineterm=""))
    return ReadableLayoutCandidate(
        preparation_status=baseline.preparation_status,
        source_sha256=source.sha256, baseline_sha256=baseline.sha256,
        request_json=raw, sha256=digest(raw), body_bytes=len(raw.encode("utf-8")),
        grid_count=baseline.grid_count, repeated_fragment_count=repeated_count,
        repeated_text_bytes=repeated_bytes, diff=diff,
    )


def verify_readable_layout_candidate(source: Capture, candidate: ReadableLayoutCandidate) -> None:
    """Recompute both D and its exact-text copies; reject rehashed substitutions."""
    if candidate != prepare_readable_layout_candidate(source):
        raise ValueError("Readable layout differs from preserved source and derived D rows.")
