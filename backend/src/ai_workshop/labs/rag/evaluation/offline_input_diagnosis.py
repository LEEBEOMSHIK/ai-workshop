"""Pure preparation of controlled input variants. No execution or result prediction.

Accepts complete v5-shaped captures only. A is byte-exact; B changes whitespace
outside JSON strings; C replaces an explicitly reviewed system guidance interval.
The caller declares that interval: this module cannot infer its semantic purpose.
"""

import hashlib
import json
from difflib import unified_diff
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

type JsonObject = dict[str, JsonValue]


class Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Capture(Value):
    run_id: UUID
    attempt_id: UUID
    execution_id: UUID
    kind: Literal["actual_capture", "synthetic_fixture"]
    request_json: str
    sha256: str
    body_bytes: int
    body_characters: int
    status: str
    content_status: str
    model: str
    provider: str
    dialect: str
    model_version: int
    profile_version: int
    prompt_ref: str


class InstructionChange(Value):
    # Prefix/suffix explicitly preserve format guidance and final wire contracts.
    prefix: str = Field(min_length=1)
    original: str = Field(min_length=1)
    replacement: str = Field(min_length=1)
    suffix: str = Field(min_length=1)


class Candidate(Value):
    condition: Literal["A", "B", "C"]
    execution_status: Literal["not_run"] = "not_run"
    request_json: str
    sha256: str
    body_bytes: int
    changed_field: Literal["none", "messages[1].content", "messages[0].content"]
    diff: str
    invariants: tuple[str, ...]


class Comparison(Value):
    version: Literal["offline-input-comparison-v1"] = "offline-input-comparison-v1"
    source: Capture
    candidates: tuple[Candidate, Candidate, Candidate]
    instruction_change: InstructionChange


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def object_value(value: JsonValue) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
    return value


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON number.")


def parse_object(raw: str) -> JsonObject:
    parsed = cast(JsonValue, json.loads(
        raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant,
    ))
    return object_value(parsed)


def message(body: JsonObject, index: int) -> JsonObject:
    values = body.get("messages")
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError("Exactly one system and one user message are required.")
    item = object_value(values[index])
    if set(item) != {"role", "content"} or item["role"] != ("system", "user")[index]:
        raise ValueError("Unexpected message contract.")
    if not isinstance(item["content"], str):
        raise ValueError("Message content must be text.")
    return item


def content(body: JsonObject, index: int) -> str:
    return cast(str, message(body, index)["content"])


def fragments(payload: JsonObject) -> tuple[JsonObject, ...]:
    sources, blocks = payload.get("evidence_sources"), payload.get("evidence_blocks")
    if not isinstance(sources, list) or not isinstance(blocks, list):
        raise ValueError("Unsupported evidence format; expected compact source blocks.")
    result: list[JsonObject] = []
    seen: set[str] = set()
    for value in blocks:
        block = object_value(value)
        ref, units = block.get("source_ref"), block.get("fragments")
        if type(ref) is not int or not 0 <= ref < len(sources) or not isinstance(units, list):
            raise ValueError("Invalid source reference or fragments.")
        object_value(sources[ref])
        for unit in units:
            item = object_value(unit)
            identity, text = item.get("evidence_id"), item.get("text")
            if not isinstance(identity, str) or not isinstance(text, str) or not text:
                raise ValueError("Evidence identity and text are required.")
            if str(UUID(identity)) != identity or identity in seen:
                raise ValueError("Invalid or duplicate evidence identity.")
            seen.add(identity)
            result.append(item)
    return tuple(result)


def capture_body(source: Capture) -> JsonObject:
    if source.kind == "actual_capture" and (
        source.provider != "local_openai_compatible" or source.dialect != "ollama"
        or source.prompt_ref != "rag-answer-v5"
    ):
        raise ValueError("Unsupported actual capture provider, dialect, or prompt format.")
    if source.status != "response_received" or source.content_status != "complete":
        raise ValueError("A complete response-received capture is required.")
    if (source.sha256 != digest(source.request_json)
            or source.body_bytes != len(source.request_json.encode("utf-8"))
            or source.body_characters != len(source.request_json)):
        raise ValueError("Capture hash or size mismatch.")
    body = parse_object(source.request_json)
    if not {"messages", "max_tokens", "temperature", "response_format"} <= body.keys():
        raise ValueError("Missing request contract.")
    if body.keys() - {"messages", "max_tokens", "temperature", "response_format",
                      "reasoning_effort"}:
        raise ValueError("Only allowlisted request fields are accepted.")
    content(body, 0)
    payload = parse_object(content(body, 1))
    allowed = {"schema_version", "question", "resolved_query", "history",
               "evidence_format_notice", "evidence_sources", "evidence_blocks"}
    if payload.keys() != allowed:
        raise ValueError("Unexpected user payload; review/answer annotations are not inputs.")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 2:
        raise ValueError("This comparison supports response schema 2 only.")
    for key in ("question", "resolved_query", "evidence_format_notice"):
        if not isinstance(payload[key], str) or not payload[key]:
            raise ValueError("Required user text field is missing or invalid.")
    history = payload["history"]
    if not isinstance(history, list):
        raise ValueError("History must be a message list.")
    for raw_turn in history:
        turn = object_value(raw_turn)
        if (turn.keys() != {"role", "content"} or turn["role"] not in ("user", "assistant")
                or not isinstance(turn["content"], str)):
            raise ValueError("Invalid history message.")
    fragments(payload)
    return body


def _reflow_json(raw: str) -> str:
    """Preserve every non-whitespace token, including string escape spellings."""
    parse_object(raw)
    pieces: list[str] = []
    depth, quoted, escaped = 0, False, False
    for char in raw:
        if quoted:
            pieces.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
            pieces.append(char)
        elif char in "{[":
            depth += 1
            pieces.append(char + "\n" + "  " * depth)
        elif char in "}]":
            depth -= 1
            pieces.append("\n" + "  " * depth + char)
        elif char == ",":
            pieces.append(",\n" + "  " * depth)
        elif char == ":":
            pieces.append(": ")
        elif char not in " \r\n\t":
            pieces.append(char)
    return "".join(pieces)


def _variant(source: Capture, patch: InstructionChange, condition: str) -> tuple[str, str]:
    body = capture_body(source)
    if content(body, 0) != patch.prefix + patch.original + patch.suffix:
        raise ValueError("Declared system interval does not match the capture.")
    if patch.original == patch.replacement:
        raise ValueError("Instruction comparison must change the reviewed interval.")
    if "\ufffd" in patch.replacement or not any(c.isalpha() for c in patch.replacement):
        raise ValueError("Instruction replacement is empty or has lost its text encoding.")
    if condition == "A":
        return source.request_json, ""
    index = 1 if condition == "B" else 0
    old = content(body, index)
    if condition == "B":
        new = _reflow_json(old)
    elif condition == "C":
        new = patch.prefix + patch.replacement + patch.suffix
    else:
        raise ValueError("Unknown comparison condition.")
    if old == new:
        raise ValueError("Candidate has no change; choose a distinct experiment.")
    message(body, index)["content"] = new
    diff = "\n".join(unified_diff(old.splitlines(), new.splitlines(),
                                 fromfile="A", tofile=condition, lineterm=""))
    return encode(body), diff


def verify_candidate(
    source: Capture, candidate: Candidate, patch: InstructionChange,
) -> tuple[str, ...]:
    expected, _ = _variant(source, patch, candidate.condition)
    if (candidate.execution_status != "not_run" or candidate.request_json != expected
            or candidate.sha256 != digest(expected)
            or candidate.body_bytes != len(expected.encode("utf-8"))):
        raise ValueError("Candidate differs from the declared single-variable transformation.")
    return ("source_hash_and_size", "request_options_unchanged", "source_content_preserved",
            "only_declared_field_changed", "no_generation_executed")


def prepare_comparison(source: Capture, patch: InstructionChange) -> Comparison:
    """Only source and a reviewed guidance patch enter candidate construction."""
    candidates: list[Candidate] = []
    for condition in ("A", "B", "C"):
        raw, diff = _variant(source, patch, condition)
        item = Candidate(
            condition=condition, request_json=raw,
            sha256=digest(raw), body_bytes=len(raw.encode("utf-8")), diff=diff,
            changed_field=("none" if condition == "A" else
                           "messages[1].content" if condition == "B" else "messages[0].content"),
            invariants=(),
        )
        checks = verify_candidate(source, item, patch)
        candidates.append(item.model_copy(update={"invariants": checks}))
    return Comparison(source=source, instruction_change=patch,
                      candidates=(candidates[0], candidates[1], candidates[2]))
