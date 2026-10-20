"""Read-only joins of exported capture/result values; no I/O or runtime imports."""

from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue

from ai_workshop.labs.rag.evaluation.generative import PrivateGenerativeResult
from ai_workshop.labs.rag.evaluation.offline_input_diagnosis import (
    Capture,
    JsonObject,
    Value,
    capture_body,
    content,
    encode,
    fragments,
    object_value,
    parse_object,
)


class _CapturedAttempt(BaseModel):
    attempt_id: UUID
    execution_id: UUID
    question: str
    inspection: dict[str, JsonValue]


class _CaptureExport(BaseModel):
    run_id: UUID
    attempts: tuple[_CapturedAttempt, ...]


class _Run(BaseModel):
    id: UUID


class _ResultAttempt(BaseModel):
    id: UUID
    execution_id: UUID
    case_id: UUID
    repetition: int = Field(ge=0)
    status: Literal["completed"]
    query: str
    expected_status: Literal["answered", "insufficient_evidence"]
    result_digest: str
    result: PrivateGenerativeResult


class _ResultExport(BaseModel):
    run: _Run
    attempts: tuple[_ResultAttempt, ...]


class Record(Value):
    capture: Capture
    case_id: UUID
    repetition: int
    question: str
    expected_status: Literal["answered", "insufficient_evidence"]
    result: PrivateGenerativeResult
    result_sha256: str
    evidence: tuple[JsonObject, ...]


def _source_check(payload: JsonObject, result: PrivateGenerativeResult) -> tuple[JsonObject, ...]:
    units = fragments(payload)
    ids = tuple(str(unit["evidence_id"]) for unit in units)
    selected = tuple(str(value) for value in result.observation.selected_evidence_ids)
    if len(set(selected)) != len(selected) or set(ids) != set(selected):
        raise ValueError("Selected evidence and captured evidence differ.")
    stored: dict[str, JsonObject] = {}
    for value in result.evidence:
        item = parse_object(encode(value))
        source = object_value(item["source"])
        key = str(source["evidence_unit_id"])
        if key in stored:
            raise ValueError("Duplicate stored evidence identity.")
        stored[key] = item
    if set(ids) != set(stored):
        raise ValueError("Stored evidence identities differ from the capture.")
    sources = cast(list[JsonValue], payload["evidence_sources"])
    blocks = cast(list[JsonValue], payload["evidence_blocks"])
    for raw_block in blocks:
        block = object_value(raw_block)
        source_context = object_value(sources[cast(int, block["source_ref"])])
        for raw_unit in cast(list[JsonValue], block["fragments"]):
            unit = object_value(raw_unit)
            item = stored[str(unit["evidence_id"])]
            source = object_value(item["source"])
            location = object_value(source["location"])
            if (unit["text"] != item["excerpt"] or unit.get("bbox") != location.get("bbox")
                    or unit.get("char_range") != [location["char_start"], location["char_end"]]):
                raise ValueError("Evidence text or location differs from the result.")
            for field in ("page", "source_kind", "source_part", "table_cell"):
                if source_context.get(field) != location.get(field):
                    raise ValueError("Source context differs from the result.")
            if source_context.get("section_path") != source.get("section_path"):
                raise ValueError("Source section differs from the result.")
    return units


def load_records(
    captures: object, results: object, *, kind: Literal["actual_capture", "synthetic_fixture"],
) -> tuple[Record, ...]:
    """Cross-check exported files; not a signature or a live permission recheck."""
    captured = _CaptureExport.model_validate(captures)
    exported = _ResultExport.model_validate(results)
    cap_ids = [item.attempt_id for item in captured.attempts]
    res_ids = [item.id for item in exported.attempts]
    if (captured.run_id != exported.run.id or not cap_ids
            or len(set(cap_ids)) != len(cap_ids) or len(set(res_ids)) != len(res_ids)
            or set(cap_ids) != set(res_ids)):
        raise ValueError("Run/attempt identity mismatch or duplicate/missing attempts.")
    captures_by_id = {item.attempt_id: item for item in captured.attempts}
    records: list[Record] = []
    executions: set[UUID] = set()
    for item in exported.attempts:
        observed = captures_by_id[item.id]
        result = item.result
        if (item.execution_id != observed.execution_id
                or item.execution_id != result.observation.execution_id
                or item.execution_id in executions or observed.question != item.query
                or result.digest() != item.result_digest):
            raise ValueError("Execution/question/result hash mismatch.")
        executions.add(item.execution_id)
        keys = Capture.model_fields.keys() - {"run_id", "attempt_id", "execution_id", "kind"}
        capture = Capture.model_validate({
            **{key: observed.inspection[key] for key in keys}, "kind": kind,
            "run_id": captured.run_id, "attempt_id": item.id, "execution_id": item.execution_id,
        })
        payload = parse_object(content(capture_body(capture), 1))
        if payload["question"] != item.query:
            raise ValueError("Captured question differs from the saved question.")
        units = _source_check(payload, result)
        records.append(Record(
            capture=capture, case_id=item.case_id, repetition=item.repetition + 1,
            question=item.query, expected_status=item.expected_status, result=result,
            result_sha256=item.result_digest, evidence=units,
        ))
    return tuple(records)
