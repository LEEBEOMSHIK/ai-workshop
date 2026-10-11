"""Pure private recipe relationships, never source, purpose or activation authority.

The supplied reference is ordinary data. A future source-bound adapter must
authenticate the actual historical triple and preserve full omission checks.
Successful validation is not installed-state CAS, a receipt, or a safe verdict.
"""

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import cast

_MAX_BYTES = 16 * 1024 * 1024
_MAX_INT = 2**63 - 1
_BASE_KEYS = {"schema_version", "scanner_version", "sources", "calls"}
_REVISION_KEYS = _BASE_KEYS | {"revision", "predecessor_sha256", "purposes"}


@dataclass(frozen=True, slots=True)
class HistoricalShellSelector:
    source: int
    call_id: str = field(repr=False)
    shell_index: int


@dataclass(frozen=True, slots=True)
class HistoryPurposeReference:
    """An unauthenticated comparison reference, deliberately not a capability."""

    baseline_recipe_json: bytes = field(repr=False)
    unqualified_tests: tuple[
        HistoricalShellSelector, HistoricalShellSelector, HistoricalShellSelector
    ] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ValidatedHistoryPurposeRevision:
    """Immutable parsed data; equal copies confer no authority."""

    revision: int
    predecessor_sha256: str = field(repr=False)
    canonical_recipe_json: bytes = field(repr=False)
    adjudicated: tuple[HistoricalShellSelector, ...] = field(repr=False)
    recorded_unadjudicated: tuple[HistoricalShellSelector, ...] = field(repr=False)


def _denied() -> ValueError:
    return ValueError("history_purpose_revision_invalid")


def _need(condition: bool) -> None:
    if not condition:
        raise _denied()


def _object(value: object, keys: set[str] | None = None) -> dict[str, object]:
    _need(type(value) is dict)
    result = cast(dict[str, object], value)
    _need(all(type(key) is str for key in result))
    if keys is not None:
        _need(set(result) == keys)
    return result


def _array(value: object, minimum: int, maximum: int) -> list[object]:
    _need(type(value) is list)
    result = cast(list[object], value)
    _need(minimum <= len(result) <= maximum)
    return result


def _integer(value: object, minimum: int = 0, maximum: int = _MAX_INT) -> int:
    _need(type(value) is int)
    result = cast(int, value)
    _need(minimum <= result <= maximum)
    return result


def _text(value: object, maximum: int = 512) -> str:
    _need(type(value) is str)
    result = cast(str, value)
    _need(0 < len(result) <= maximum and all(ord(c) >= 32 for c in result))
    result.encode("utf-8", errors="strict")
    return result


def _digest(value: object) -> str:
    result = _text(value, 64)
    _need(re.fullmatch(r"[0-9a-f]{64}", result) is not None)
    return result


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        _need(type(key) is str and key not in result)
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise _denied()


def _read(raw: bytes) -> dict[str, object]:
    _need(type(raw) is bytes and 0 < len(raw) <= _MAX_BYTES)
    value: object = json.loads(
        raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs, parse_constant=_constant
    )
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        _need(count <= 100000 and depth <= 32)
        if type(item) is dict:
            obj = _object(item)
            pending.extend((v, depth + 1) for v in obj.values())
        elif type(item) is list:
            pending.extend((v, depth + 1) for v in cast(list[object], item))
        else:
            _need(item is None or type(item) in {str, int, bool})
    return _object(value)


def _canonical(value: dict[str, object]) -> bytes:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    _need(len(raw) <= _MAX_BYTES)
    return raw


def _inventory(value: dict[str, object]) -> tuple[bytes, tuple[HistoricalShellSelector, ...]]:
    sources = _array(value["sources"], 1, 64)
    locators: set[str] = set()
    total_bytes = 0
    for index, item in enumerate(sources):
        source = _object(item)
        base = {"locator", "prefix_bytes", "prefix_sha256"}
        _need(set(source) in (base, base | {"parent_spawn", "purpose"}))
        locator = _text(source["locator"], 32767)
        _need(locator not in locators)
        locators.add(locator)
        total_bytes += _integer(source["prefix_bytes"], 1, 512 * 1024 * 1024)
        _digest(source["prefix_sha256"])
        if "parent_spawn" in source:
            _need(_text(source["purpose"]) == "historical_source_writes")
            parent = _object(source["parent_spawn"], {"source", "call_id", "first_line_sha256"})
            _integer(parent["source"], 0, index - 1)
            _text(parent["call_id"])
            _digest(parent["first_line_sha256"])
    _need(total_bytes <= 1024 * 1024 * 1024)
    calls = _array(value["calls"], 43, 43)
    seen: set[tuple[int, str]] = set()
    selectors: list[HistoricalShellSelector] = []
    for item in calls:
        call = _object(item, {"source", "call_id", "shell_indices", "supports"})
        source_index = _integer(call["source"], 0, len(sources) - 1)
        call_id = _text(call["call_id"])
        _need((source_index, call_id) not in seen)
        seen.add((source_index, call_id))
        indices = tuple(_integer(v) for v in _array(call["shell_indices"], 1, 64))
        _need(len(set(indices)) == len(indices))
        selectors.extend(HistoricalShellSelector(source_index, call_id, i) for i in indices)
        for entry in _array(call["supports"], 0, 10000):
            support = _object(entry, {"source", "line", "payload_sha256", "kind"})
            _integer(support["source"], 0, len(sources) - 1)
            _integer(support["line"], 1)
            _digest(support["payload_sha256"])
            _need(_text(support["kind"]) in {"target_observation", "contemporaneous_stage"})
    _need(len(selectors) == 64 and len(set(selectors)) == 64)
    return _canonical({"sources": sources, "calls": calls}), tuple(selectors)


def _baseline(raw: bytes) -> tuple[dict[str, object], bytes, tuple[HistoricalShellSelector, ...]]:
    value = _read(raw)
    _object(value, _BASE_KEYS)
    _need(_integer(value["schema_version"]) == 1 and _integer(value["scanner_version"]) == 1)
    inventory, selectors = _inventory(value)
    return value, inventory, selectors


def _triple(
    reference: HistoryPurposeReference, selectors: tuple[HistoricalShellSelector, ...]
) -> tuple[HistoricalShellSelector, ...]:
    values = reference.unqualified_tests
    _need(type(values) is tuple and len(values) == 3)
    for value in values:
        _need(type(value) is HistoricalShellSelector)
        _integer(value.source)
        _integer(value.shell_index)
        _text(value.call_id)
    _need(len(set(values)) == 3)
    ordered = tuple(selector for selector in selectors if selector in values)
    _need(ordered == values)
    return ordered


def _revision(
    raw: bytes,
    inventory: bytes,
    selectors: tuple[HistoricalShellSelector, ...],
    unqualified: tuple[HistoricalShellSelector, ...],
) -> dict[str, object]:
    value = _read(raw)
    _object(value, _REVISION_KEYS)
    _need(_integer(value["schema_version"]) == 2 and _integer(value["scanner_version"]) == 2)
    _integer(value["revision"], 1)
    _digest(value["predecessor_sha256"])
    actual_inventory, actual_selectors = _inventory(value)
    _need(actual_inventory == inventory and actual_selectors == selectors)
    purposes = _array(value["purposes"], 64, 64)
    for item, selector in zip(purposes, selectors, strict=True):
        purpose = _object(item, {"source", "call_id", "shell_index", "purpose", "reason"})
        _need(_integer(purpose["source"]) == selector.source)
        _need(_text(purpose["call_id"]) == selector.call_id)
        _need(_integer(purpose["shell_index"]) == selector.shell_index)
        if selector in unqualified:
            _need(_text(purpose["purpose"]) == "recorded_unadjudicated")
            _need(_text(purpose["reason"]) == "historical_test_source_unqualified")
        else:
            _need(_text(purpose["purpose"]) == "adjudicate" and purpose["reason"] is None)
    _need(_canonical(value) == raw)
    return value


def validate_history_purpose_revision(
    previous_recipe_json: bytes,
    candidate_recipe_json: bytes,
    *,
    reference: HistoryPurposeReference,
) -> ValidatedHistoryPurposeRevision:
    """Validate a supplied relationship; do not authenticate history or activate it."""
    try:
        _need(type(reference) is HistoryPurposeReference)
        baseline, inventory, selectors = _baseline(reference.baseline_recipe_json)
        unqualified = _triple(reference, selectors)
        previous = _read(previous_recipe_json)
        version = _integer(previous["schema_version"])
        if version == 1:
            previous, previous_inventory, _ = _baseline(previous_recipe_json)
            _need(previous_inventory == inventory and _canonical(previous) == _canonical(baseline))
            previous_revision = 0
        elif version == 2:
            previous = _revision(previous_recipe_json, inventory, selectors, unqualified)
            previous_revision = _integer(previous["revision"], 1)
        else:
            raise _denied()
        candidate = _revision(candidate_recipe_json, inventory, selectors, unqualified)
        revision = _integer(candidate["revision"], 1)
        predecessor = _digest(candidate["predecessor_sha256"])
        _need(revision == previous_revision + 1)
        _need(predecessor == sha256(_canonical(previous)).hexdigest())
        return ValidatedHistoryPurposeRevision(
            revision,
            predecessor,
            _canonical(candidate),
            tuple(s for s in selectors if s not in unqualified),
            unqualified,
        )
    except Exception:
        raise _denied() from None
