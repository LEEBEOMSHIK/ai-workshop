"""Synthetic pure recipe data; no original recipe, source reader or authority."""

import copy
import json
from dataclasses import replace
from hashlib import sha256
from typing import Any, cast

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_history_purposes import (
    HistoricalShellSelector,
    HistoryPurposeReference,
    ValidatedHistoryPurposeRevision,
    validate_history_purpose_revision,
)

type Document = dict[str, Any]


def encoded(value: Document) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def fixture() -> tuple[Document, Document, HistoryPurposeReference]:
    baseline: Document = {
        "schema_version": 1,
        "scanner_version": 1,
        "sources": [
            {
                "locator": "C:/synthetic/source.jsonl",
                "prefix_bytes": 100,
                "prefix_sha256": "a" * 64,
            },
            {
                "locator": "C:/synthetic/child.jsonl",
                "prefix_bytes": 100,
                "prefix_sha256": "b" * 64,
                "purpose": "historical_source_writes",
                "parent_spawn": {
                    "source": 0,
                    "call_id": "synthetic-spawn",
                    "first_line_sha256": "c" * 64,
                },
            },
        ],
        "calls": [
            {
                "source": 0,
                "call_id": f"synthetic-{i}",
                "shell_indices": [0, 1] if i < 21 else [0],
                "supports": [
                    {
                        "source": 0,
                        "line": 1,
                        "payload_sha256": "d" * 64,
                        "kind": "target_observation",
                    }
                ]
                if i == 0
                else [],
            }
            for i in range(43)
        ],
    }
    selectors = [
        HistoricalShellSelector(c["source"], c["call_id"], i)
        for c in baseline["calls"]
        for i in c["shell_indices"]
    ]
    triple = cast(
        tuple[HistoricalShellSelector, HistoricalShellSelector, HistoricalShellSelector],
        tuple(selectors[:3]),
    )
    reference = HistoryPurposeReference(encoded(baseline), triple)
    candidate = copy.deepcopy(baseline)
    candidate.update(
        schema_version=2,
        scanner_version=2,
        revision=1,
        predecessor_sha256=sha256(encoded(baseline)).hexdigest(),
        purposes=[
            {
                "source": s.source,
                "call_id": s.call_id,
                "shell_index": s.shell_index,
                "purpose": "recorded_unadjudicated" if s in triple else "adjudicate",
                "reason": "historical_test_source_unqualified" if s in triple else None,
            }
            for s in selectors
        ],
    )
    return baseline, candidate, reference


def validate(
    baseline: Document, candidate: Document, reference: HistoryPurposeReference
) -> ValidatedHistoryPurposeRevision:
    return validate_history_purpose_revision(
        encoded(baseline), encoded(candidate), reference=reference
    )


def test_initial_revision_preserves_all43_calls64_shells_and_no_authority() -> None:
    baseline, candidate, reference = fixture()
    result = validate(baseline, candidate, reference)
    assert result.revision == 1 and len(result.adjudicated) == 61
    assert result.recorded_unadjudicated == reference.unqualified_tests
    assert result.canonical_recipe_json == encoded(candidate)
    assert len(json.loads(result.canonical_recipe_json)["calls"]) == 43
    assert json.loads(result.canonical_recipe_json)["calls"] == baseline["calls"]
    assert not hasattr(result, "assert_issued") and not hasattr(result, "coverage")
    assert "synthetic-" not in repr(result) and "source.jsonl" not in repr(reference)


def test_next_revision_and_pretty_schema1_use_explicit_canonical_predecessor() -> None:
    baseline, candidate, reference = fixture()
    pretty = json.dumps(baseline, indent=2).encode()
    first = validate_history_purpose_revision(pretty, encoded(candidate), reference=reference)
    next_doc = copy.deepcopy(candidate)
    next_doc.update(revision=2, predecessor_sha256=sha256(first.canonical_recipe_json).hexdigest())
    second = validate_history_purpose_revision(
        first.canonical_recipe_json, encoded(next_doc), reference=reference
    )
    assert second.revision == 2
    assert copy.deepcopy(second) == second
    # Revalidating the same pair is structural, never proof of installed CAS state.
    assert (
        validate_history_purpose_revision(
            first.canonical_recipe_json, encoded(next_doc), reference=reference
        )
        == second
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing_purpose",
        "extra_purpose",
        "duplicate_purpose",
        "reordered_purposes",
        "fourth",
        "only_two",
        "swapped_third",
        "caller_reason",
        "adjudicate_reason",
        "unknown_purpose",
        "wrong_source",
        "bool_source",
        "bool_shell",
        "float_shell",
        "changed_call",
        "removed_call",
        "reordered_calls",
        "changed_shell",
        "changed_support",
        "changed_source",
        "changed_child",
        "reordered_sources",
        "unknown_key",
        "wrong_schema",
        "wrong_scanner",
        "revision_zero",
        "revision_gap",
        "revision_bool",
        "revision_float",
        "revision_overflow",
        "predecessor",
        "missing_predecessor",
        "uppercase_predecessor",
        "duplicate_call",
        "missing_reason",
    ],
)
def test_candidate_contract_mutations_refused(fault: str) -> None:
    baseline, candidate, reference = fixture()
    purposes = candidate["purposes"]
    if fault == "missing_purpose":
        purposes.pop()
    elif fault == "extra_purpose":
        purposes.append(copy.deepcopy(purposes[-1]))
    elif fault == "duplicate_purpose":
        purposes[3] = copy.deepcopy(purposes[2])
    elif fault == "reordered_purposes":
        purposes[3], purposes[4] = purposes[4], purposes[3]
    elif fault == "fourth":
        purposes[3].update(
            purpose="recorded_unadjudicated", reason="historical_test_source_unqualified"
        )
    elif fault == "only_two":
        purposes[2].update(purpose="adjudicate", reason=None)
    elif fault == "swapped_third":
        purposes[2].update(purpose="adjudicate", reason=None)
        purposes[3].update(
            purpose="recorded_unadjudicated", reason="historical_test_source_unqualified"
        )
    elif fault == "caller_reason":
        purposes[0]["reason"] = "caller_says_safe"
    elif fault == "adjudicate_reason":
        purposes[3]["reason"] = "historical_test_source_unqualified"
    elif fault == "unknown_purpose":
        purposes[0]["purpose"] = "non_control"
    elif fault == "wrong_source":
        purposes[0]["source"] = 1
    elif fault == "bool_source":
        purposes[0]["source"] = False
    elif fault == "bool_shell":
        purposes[0]["shell_index"] = False
    elif fault == "float_shell":
        purposes[0]["shell_index"] = 0.0
    elif fault == "changed_call":
        candidate["calls"][0]["call_id"] = "other"
    elif fault == "removed_call":
        candidate["calls"].pop()
    elif fault == "reordered_calls":
        candidate["calls"].reverse()
    elif fault == "changed_shell":
        candidate["calls"][0]["shell_indices"] = [1, 0]
    elif fault == "changed_support":
        candidate["calls"][0]["supports"][0]["line"] = 2
    elif fault == "changed_source":
        candidate["sources"][0]["prefix_bytes"] = 101
    elif fault == "changed_child":
        candidate["sources"][1]["parent_spawn"]["call_id"] = "other"
    elif fault == "reordered_sources":
        candidate["sources"].reverse()
    elif fault == "unknown_key":
        candidate["authority"] = True
    elif fault == "wrong_schema":
        candidate["schema_version"] = 1
    elif fault == "wrong_scanner":
        candidate["scanner_version"] = 1
    elif fault.startswith("revision_"):
        candidate["revision"] = {
            "revision_zero": 0,
            "revision_gap": 2,
            "revision_bool": True,
            "revision_float": 1.0,
            "revision_overflow": 2**63,
        }[fault]
    elif fault == "predecessor":
        candidate["predecessor_sha256"] = "e" * 64
    elif fault == "missing_predecessor":
        del candidate["predecessor_sha256"]
    elif fault == "uppercase_predecessor":
        candidate["predecessor_sha256"] = candidate["predecessor_sha256"].upper()
    elif fault == "duplicate_call":
        candidate["calls"][1] = copy.deepcopy(candidate["calls"][0])
    elif fault == "missing_reason":
        del purposes[0]["reason"]
    with pytest.raises(ValueError, match="^history_purpose_revision_invalid$"):
        validate(baseline, candidate, reference)


@pytest.mark.parametrize(
    "fault", ["two", "four", "duplicate", "reordered", "other", "list", "bool", "changed_baseline"]
)
def test_reference_is_exact_three_structural_data_only(fault: str) -> None:
    baseline, candidate, reference = fixture()
    triple: Any = reference.unqualified_tests
    if fault == "two":
        triple = triple[:2]
    elif fault == "four":
        triple = (*triple, HistoricalShellSelector(0, "synthetic-2", 0))
    elif fault == "duplicate":
        triple = (triple[0], triple[0], triple[2])
    elif fault == "reordered":
        triple = tuple(reversed(triple))
    elif fault == "other":
        triple = (*triple[:2], HistoricalShellSelector(0, "synthetic-2", 0))
    elif fault == "list":
        triple = list(triple)
    elif fault == "bool":
        triple = (HistoricalShellSelector(False, triple[0].call_id, 0), *triple[1:])
    if fault == "changed_baseline":
        changed = copy.deepcopy(baseline)
        changed["sources"][0]["locator"] = "C:/different/source.jsonl"
        reference = replace(reference, baseline_recipe_json=encoded(changed))
    else:
        reference = replace(reference, unqualified_tests=triple)
    with pytest.raises(ValueError, match="^history_purpose_revision_invalid$"):
        validate(baseline, candidate, reference)


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_root",
        "duplicate_nested",
        "noncanonical",
        "nan",
        "oversize",
        "deep",
        "invalid_utf8",
    ],
)
def test_strict_json_and_bounds(fault: str) -> None:
    baseline, candidate, reference = fixture()
    raw = encoded(candidate)
    if fault == "duplicate_root":
        raw = raw.replace(b"{", b'{"revision":1,', 1)
    elif fault == "duplicate_nested":
        raw = raw.replace(
            b'"call_id":"synthetic-0"', b'"call_id":"synthetic-0","call_id":"synthetic-0"', 1
        )
    elif fault == "noncanonical":
        raw = json.dumps(candidate, indent=2).encode()
    elif fault == "nan":
        raw = raw.replace(b'"revision":1', b'"revision":NaN')
    elif fault == "oversize":
        raw = b" " * (16 * 1024 * 1024 + 1)
    elif fault == "deep":
        raw = b'{"x":' + b"[" * 150 + b"0" + b"]" * 150 + b"}"
    elif fault == "invalid_utf8":
        raw = b"\xff"
    with pytest.raises(ValueError, match="^history_purpose_revision_invalid$"):
        validate_history_purpose_revision(encoded(baseline), raw, reference=reference)


def test_next_revision_cannot_reuse_or_skip_or_mutate_predecessor() -> None:
    baseline, previous, reference = fixture()
    for revision in (1, 3):
        candidate = copy.deepcopy(previous)
        candidate.update(
            revision=revision, predecessor_sha256=sha256(encoded(previous)).hexdigest()
        )
        with pytest.raises(ValueError, match="^history_purpose_revision_invalid$"):
            validate_history_purpose_revision(
                encoded(previous), encoded(candidate), reference=reference
            )
    previous["purposes"][0]["reason"] = "other"
    candidate = copy.deepcopy(previous)
    candidate.update(revision=2, predecessor_sha256=sha256(encoded(previous)).hexdigest())
    with pytest.raises(ValueError, match="^history_purpose_revision_invalid$"):
        validate_history_purpose_revision(
            encoded(previous), encoded(candidate), reference=reference
        )


@pytest.mark.parametrize(
    "fault",
    [
        "bool_prefix",
        "oversize_prefix",
        "bad_prefix_digest",
        "duplicate_locator",
        "parent_forward",
        "child_purpose",
        "support_bool_line",
        "support_unknown_kind",
        "support_extra",
        "call_bool_source",
        "duplicate_shell",
        "duplicate_call",
        "empty_call_id",
        "extra_source_key",
        "baseline_extra",
        "baseline_bool_schema",
    ],
)
def test_self_consistent_invalid_baseline_cannot_bypass_shape_validation(fault: str) -> None:
    baseline, candidate, reference = fixture()
    if fault == "bool_prefix":
        baseline["sources"][0]["prefix_bytes"] = True
    elif fault == "oversize_prefix":
        baseline["sources"][0]["prefix_bytes"] = 512 * 1024 * 1024 + 1
    elif fault == "bad_prefix_digest":
        baseline["sources"][0]["prefix_sha256"] = "a" * 63
    elif fault == "duplicate_locator":
        baseline["sources"][1]["locator"] = baseline["sources"][0]["locator"]
    elif fault == "parent_forward":
        baseline["sources"][1]["parent_spawn"]["source"] = 1
    elif fault == "child_purpose":
        baseline["sources"][1]["purpose"] = "operational"
    elif fault == "support_bool_line":
        baseline["calls"][0]["supports"][0]["line"] = True
    elif fault == "support_unknown_kind":
        baseline["calls"][0]["supports"][0]["kind"] = "safe"
    elif fault == "support_extra":
        baseline["calls"][0]["supports"][0]["authority"] = True
    elif fault == "call_bool_source":
        baseline["calls"][0]["source"] = False
    elif fault == "duplicate_shell":
        baseline["calls"][0]["shell_indices"] = [0, 0]
    elif fault == "duplicate_call":
        baseline["calls"][1] = copy.deepcopy(baseline["calls"][0])
    elif fault == "empty_call_id":
        baseline["calls"][0]["call_id"] = ""
    elif fault == "extra_source_key":
        baseline["sources"][0]["extra"] = "ignored"
    elif fault == "baseline_extra":
        baseline["extra"] = "ignored"
    elif fault == "baseline_bool_schema":
        baseline["schema_version"] = True
    candidate.update(sources=baseline["sources"], calls=baseline["calls"])
    candidate["predecessor_sha256"] = sha256(encoded(baseline)).hexdigest()
    reference = replace(reference, baseline_recipe_json=encoded(baseline))
    with pytest.raises(ValueError, match="^history_purpose_revision_invalid$"):
        validate(baseline, candidate, reference)


@pytest.mark.parametrize("kind", ["reference", "selector", "bytes", "string"])
def test_exact_input_classes_reject_equal_subclasses(kind: str) -> None:
    baseline, candidate, reference = fixture()
    previous = encoded(baseline)
    if kind == "reference":

        class ForeignReference(HistoryPurposeReference):
            pass

        reference = ForeignReference(reference.baseline_recipe_json, reference.unqualified_tests)
    elif kind == "selector":

        class ForeignSelector(HistoricalShellSelector):
            pass

        first = reference.unqualified_tests[0]
        reference = replace(
            reference,
            unqualified_tests=(
                ForeignSelector(first.source, first.call_id, first.shell_index),
                *reference.unqualified_tests[1:],
            ),
        )
    elif kind == "bytes":

        class ForeignBytes(bytes):
            pass

        previous = ForeignBytes(previous)
    else:

        class ForeignString(str):
            pass

        first = reference.unqualified_tests[0]
        reference = replace(
            reference,
            unqualified_tests=(
                HistoricalShellSelector(
                    first.source, ForeignString(first.call_id), first.shell_index
                ),
                *reference.unqualified_tests[1:],
            ),
        )
    with pytest.raises(ValueError, match="^history_purpose_revision_invalid$"):
        validate_history_purpose_revision(previous, encoded(candidate), reference=reference)
