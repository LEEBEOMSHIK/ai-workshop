"""Synthetic complete physical joins; ordinary DTOs never establish authority."""

import importlib
import json
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_index_inventory import _canonical
from ai_workshop.labs.rag.indexing.access_epoch_namespace_source import (
    OriginalUnmanagedPhysicalEntry,
)
from tests.unit.labs.rag.indexing import test_access_epoch_foreign_inventory as foreign
from tests.unit.labs.rag.indexing import test_access_epoch_index_inventory as wire

MODULE = "ai_workshop.labs.rag.indexing.access_epoch_unmanaged_inventory"


def sample() -> tuple[dict[str, Any], dict[str, Any], tuple[OriginalUnmanagedPhysicalEntry, ...]]:
    state, stats = foreign.singleton_autoexpand_fixtures()
    for row in state["metadata"]["indices"].values():
        row["system"] = False
    row = wire.legacy_metadata()[wire.LEGACY_NAME]
    row.pop("defaults")
    row["aliases"] = ["retained-private-alias"]
    row.update(state="open", system=False)
    state["metadata"]["indices"][wire.LEGACY_NAME] = row
    state["routing_table"]["indices"][wire.LEGACY_NAME] = {
        "shards": {
            "0": [
                {
                    "primary": True,
                    "state": "STARTED",
                    "node": foreign.NODE,
                    "relocating_node": None,
                    "shard": 0,
                    "index": wire.LEGACY_NAME,
                }
            ]
        }
    }
    stats["nodes"][foreign.NODE]["indices"]["indices"][wire.LEGACY_NAME] = {
        "docs": {"count": 17, "deleted": 3}
    }
    entry = OriginalUnmanagedPhysicalEntry(
        wire.LEGACY_NAME,
        row["settings"]["index.uuid"],
        UUID(wire.PROFILE),
        UUID(wire.BUILD),
        "rag",
        "missing_indexing_profile",
        tuple(row["aliases"]),
        _canonical({wire.LEGACY_NAME: row}),
    )
    return state, stats, (entry,)


def decode(
    state: dict[str, Any],
    stats: dict[str, Any],
    entries: tuple[OriginalUnmanagedPhysicalEntry, ...],
) -> Any:
    return importlib.import_module(MODULE).decode_unmanaged_inventory(
        json.dumps(state).encode(),
        json.dumps(stats).encode(),
        cluster_uuid=foreign.CLUSTER,
        cluster_name="original",
        stable_node_id=foreign.NODE,
        unmanaged_entries=entries,
    )


def test_complete_map_retained_with_legacy_live_cardinality() -> None:
    state, stats, entries = sample()
    result = decode(state, stats, entries)
    assert result.entries[0].count == 17
    assert result.entries[0].reason == "missing_indexing_profile"
    assert len(json.loads(result.private_physical_inventory)) == 3
    assert result.entries[0].private_metadata == entries[0].private_metadata
    assert "retained-private-alias" not in repr(result)
    assert "synthetic-private" not in repr(result)


@pytest.mark.parametrize(
    "fault",
    [
        "metadata",
        "profile",
        "reason",
        "tracked",
        "system",
        "hidden",
        "routing_missing",
        "stats_missing",
        "duplicate_uuid",
        "node_count",
        "bool_docs",
        "aliases",
    ],
)
def test_unmanaged_structure_never_skips_unknown_or_changed_rows(fault: str) -> None:
    state, stats, entries = sample()
    row = state["metadata"]["indices"][wire.LEGACY_NAME]
    if fault == "metadata":
        row["settings"]["private_added"] = "changed"
    elif fault == "profile":
        entries = (replace(entries[0], indexing_profile_id=UUID(wire.BUILD)),)
    elif fault == "reason":
        entries = (replace(entries[0], reason="unsupported"),)  # type: ignore[arg-type]
    elif fault == "tracked":
        row["mappings"]["_meta"]["rag_index_resource"] = {}
    elif fault == "system":
        row["system"] = True
    elif fault == "hidden":
        row["settings"]["index.hidden"] = "true"
    elif fault == "routing_missing":
        del state["routing_table"]["indices"]["other"]
    elif fault == "stats_missing":
        del stats["nodes"][foreign.NODE]["indices"]["indices"]["other"]
    elif fault == "duplicate_uuid":
        row["settings"]["index.uuid"] = state["metadata"]["indices"]["other"]["settings"][
            "index.uuid"
        ]
    elif fault == "node_count":
        stats["_nodes"]["failed"] = 1
    elif fault == "bool_docs":
        stats["nodes"][foreign.NODE]["indices"]["indices"]["other"]["docs"]["count"] = True
    else:
        entries = (replace(entries[0], aliases=()),)
    with pytest.raises(ValueError, match="^unmanaged_inventory_decode_denied$"):
        decode(state, stats, entries)


def test_private_entry_change_is_detected_even_when_live_docs_equal() -> None:
    state, stats, entries = sample()
    before = decode(state, stats, entries)
    row = state["metadata"]["indices"][wire.LEGACY_NAME]
    row["settings"]["private_new_setting"] = "changed"
    after = decode(
        state, stats, (replace(entries[0], private_metadata=_canonical({wire.LEGACY_NAME: row})),)
    )
    with pytest.raises(ValueError, match="^unmanaged_inventory_preservation_mismatch$"):
        importlib.import_module(MODULE).require_same_unmanaged_entries(before, after)


def test_deleted_docs_diagnostic_does_not_claim_changed_live_cardinality() -> None:
    state, stats, entries = sample()
    before = decode(state, stats, entries)
    stats["nodes"][foreign.NODE]["indices"]["indices"][wire.LEGACY_NAME]["docs"]["deleted"] = 9
    after = decode(state, stats, entries)
    assert importlib.import_module(MODULE).require_same_unmanaged_entries(before, after) is None


def test_both_source_reasons_preserve_all_outside_and_orphan_rows() -> None:
    from copy import deepcopy

    state, stats, entries = sample()
    added = []
    for prefix, identifier in (("old-rag", "outsideUuidOne"), ("other-rag", "outsideUuidTwo")):
        name = f"{prefix}-{wire.PROFILE}-{wire.BUILD}"
        row = deepcopy(state["metadata"]["indices"][wire.LEGACY_NAME])
        row["settings"]["index.uuid"] = identifier
        state["metadata"]["indices"][name] = row
        route = deepcopy(state["routing_table"]["indices"][wire.LEGACY_NAME])
        route["shards"]["0"][0]["index"] = name
        state["routing_table"]["indices"][name] = route
        stats["nodes"][foreign.NODE]["indices"]["indices"][name] = {
            "docs": {"count": 2, "deleted": 0}
        }
        added.append(
            replace(
                entries[0],
                name=name,
                uuid=identifier,
                prefix=prefix,
                reason="outside_configured_prefix",
                private_metadata=_canonical({name: row}),
            )
        )
    all_entries = tuple(sorted((*entries, *added), key=lambda entry: entry.name))
    result = decode(state, stats, all_entries)
    assert len(result.entries) == 3
    assert len(json.loads(result.private_physical_inventory)) == 5
    assert [entry.reason for entry in result.entries].count("outside_configured_prefix") == 2
    with pytest.raises(ValueError, match="^unmanaged_inventory_decode_denied$"):
        decode(state, stats, tuple(reversed(all_entries)))
    with pytest.raises(ValueError, match="^unmanaged_inventory_decode_denied$"):
        decode(state, stats, (entries[0], entries[0]))
