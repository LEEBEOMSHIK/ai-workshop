"""Pure synthetic foreign metadata/routing/Lucene-cardinality contracts."""

import hashlib
import importlib
import json
from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

NODE = "syntheticStableNode"
CLUSTER = "syntheticClusterUuid"
PRIVATE = "synthetic-private-alias-content"
FOREIGN = "private-foreign-name"


@pytest.fixture
def api() -> Any:
    return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_foreign_inventory")


def raw(body: object) -> bytes:
    return json.dumps(body).encode()


def test_current_system_field_is_retained_for_every_physical_row(api: Any) -> None:
    state, stats = fixtures()
    for row in state["metadata"]["indices"].values():
        row["system"] = False
    value = decode(api, state, stats)
    assert json.loads(value.entries[0].private_metadata)["system"] is False
    state["metadata"]["indices"]["other"]["system"] = True
    assert decode(api, state, stats).entries[0].observation.count == 7
    with pytest.raises(ValueError):
        decode(api, state, stats, names=("other",))


@pytest.mark.parametrize("system", [None, 0, 1, "false", "true", [], {}])
def test_current_system_field_never_coerces_and_global_invalid_is_denied(
    api: Any, system: Any
) -> None:
    state, stats = fixtures()
    state["metadata"]["indices"]["other"]["system"] = system
    with pytest.raises(ValueError):
        decode(api, state, stats)


def fixtures() -> tuple[dict[str, Any], dict[str, Any]]:
    indices: dict[str, Any] = {}
    routing: dict[str, Any] = {}
    stats: dict[str, Any] = {}
    for name, identifier, count in ((FOREIGN, "foreignUuid", 7), ("other", "otherUuid", 2)):
        indices[name] = {
            "state": "open",
            "settings": {
                "index.uuid": identifier,
                "index.creation_date": "1700000000000",
                "index.number_of_shards": "2",
                "index.number_of_replicas": "1",
                "index.version.created": "9050299",
                "index.analysis.filter.custom.synonyms": [PRIVATE],
            },
            "mappings": {
                "_doc": {"_meta": {"note": PRIVATE}, "properties": {"text": {"type": "text"}}}
            },
            "aliases": {"private-alias": {"filter": {"term": {"private": PRIVATE}}}},
        }
        routing[name] = {
            "shards": {
                str(shard): [
                    {
                        "primary": True,
                        "state": "STARTED",
                        "node": NODE,
                        "relocating_node": None,
                        "shard": shard,
                        "index": name,
                    },
                    {
                        "primary": False,
                        "state": "UNASSIGNED",
                        "node": None,
                        "relocating_node": None,
                        "shard": shard,
                        "index": name,
                    },
                ]
                for shard in range(2)
            }
        }
        stats[name] = {"docs": {"count": count, "deleted": 3}}
    return (
        {
            "cluster_name": "original",
            "cluster_uuid": CLUSTER,
            "metadata": {"indices": indices},
            "routing_table": {"indices": routing},
        },
        {
            "cluster_name": "original",
            "_nodes": {"total": 1, "successful": 1, "failed": 0},
            "nodes": {NODE: {"indices": {"indices": stats}}},
        },
    )


def decode(
    api: Any, state: dict[str, Any], stats: dict[str, Any], names: tuple[str, ...] = (FOREIGN,)
) -> Any:
    return api.decode_foreign_inventory(
        raw(state),
        raw(stats),
        cluster_uuid=CLUSTER,
        cluster_name="original",
        stable_node_id=NODE,
        foreign_names=names,
    )


def singleton_autoexpand_fixtures() -> tuple[dict[str, Any], dict[str, Any]]:
    state, stats = fixtures()
    for name, row in state["metadata"]["indices"].items():
        row["settings"]["index.auto_expand_replicas"] = "0-1"
        row["settings"]["index.number_of_replicas"] = "0"
        for copies in state["routing_table"]["indices"][name]["shards"].values():
            del copies[1:]
    return state, stats


def replica_wire_fixtures() -> tuple[dict[str, Any], dict[str, Any]]:
    state, stats = fixtures()
    replica = state["routing_table"]["indices"]["other"]["shards"]["0"][1]
    replica["recovery_source"] = {"type": "PEER"}
    replica["unassigned_info"] = {
        "reason": "CLUSTER_RECOVERED",
        "at": "2026-10-02T00:46:09.123Z",
        "delayed": False,
        "allocation_status": "no_attempt",
    }
    return state, stats


def test_pinned_unassigned_replica_diagnostics_do_not_hide_shard_coverage(api: Any) -> None:
    state, stats = replica_wire_fixtures()
    assert decode(api, state, stats).entries[0].observation.count == 7


@pytest.mark.parametrize(
    "change", ("unknown_key", "delayed_type", "recovery_type", "timestamp", "wrong_node")
)
def test_replica_diagnostic_extension_is_closed_and_preserves_role_checks(
    api: Any, change: str
) -> None:
    state, stats = replica_wire_fixtures()
    replica = state["routing_table"]["indices"]["other"]["shards"]["0"][1]
    if change == "unknown_key":
        replica["unassigned_info"]["extra"] = "synthetic"
    elif change == "delayed_type":
        replica["unassigned_info"]["delayed"] = 0
    elif change == "recovery_type":
        replica["recovery_source"]["type"] = "LOCAL_SHARDS"
    elif change == "timestamp":
        replica["unassigned_info"]["at"] = "untrusted"
    else:
        replica["node"] = NODE
    with pytest.raises(ValueError, match="^foreign_inventory_decode_denied$"):
        decode(api, state, stats)


def test_pinned_zero_to_one_autoexpand_has_zero_replicas_on_one_node(api: Any) -> None:
    state, stats = singleton_autoexpand_fixtures()
    assert decode(api, state, stats).entries[0].observation.count == 7


@pytest.mark.parametrize(
    "change", ("replica_setting", "extra_replica", "extra_node", "different_range")
)
def test_singleton_autoexpand_requires_observed_effective_replica_coverage(
    api: Any, change: str
) -> None:
    state, stats = singleton_autoexpand_fixtures()
    if change == "replica_setting":
        state["metadata"]["indices"][FOREIGN]["settings"]["index.number_of_replicas"] = "1"
    elif change == "extra_replica":
        copies = state["routing_table"]["indices"][FOREIGN]["shards"]["0"]
        copies.append({**copies[0], "primary": False, "state": "UNASSIGNED", "node": None})
    elif change == "extra_node":
        stats["_nodes"]["total"] = 2
        stats["_nodes"]["successful"] = 2
        stats["nodes"]["different-node"] = deepcopy(stats["nodes"][NODE])
    else:
        state["metadata"]["indices"][FOREIGN]["settings"]["index.auto_expand_replicas"] = "0-all"
    with pytest.raises(ValueError, match="^foreign_inventory_decode_denied$"):
        decode(api, state, stats)


def test_single_node_primary_coverage_returns_explicit_lucene_kind_without_private_repr(
    api: Any,
) -> None:
    state, stats = fixtures()
    result = decode(api, state, stats)
    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.name == FOREIGN
    assert entry.observation.uuid == "foreignUuid"
    assert entry.observation.count == 7
    assert entry.observation.count_kind == "lucene_live_docs"
    assert entry.observation.schema == "opaque_non_rag_v1"
    assert entry.deleted_docs == 3
    assert json.loads(entry.private_metadata) == state["metadata"]["indices"][FOREIGN]
    for value in (result, entry, entry.observation):
        assert PRIVATE not in repr(value)
        assert FOREIGN not in repr(value)


@pytest.mark.parametrize(
    "change",
    [
        "missing_stats",
        "extra_stats",
        "missing_routing",
        "duplicate_uuid",
        "cluster_name",
        "cluster_uuid",
        "wrong_node",
        "extra_node",
        "boolean_success",
        "float_total",
        "failed_node",
        "closed",
        "missing_uuid",
        "bool_count",
        "float_deleted",
        "negative_count",
        "missing_docs",
        "extra_stats_field",
    ],
)
def test_inventory_requires_exact_cluster_node_and_complete_physical_join(
    api: Any, change: str
) -> None:
    state, stats = fixtures()
    counts = stats["nodes"][NODE]["indices"]["indices"]
    indices = state["metadata"]["indices"]
    if change == "missing_stats":
        del counts["other"]
    elif change == "extra_stats":
        counts["extra"] = deepcopy(counts["other"])
    elif change == "missing_routing":
        del state["routing_table"]["indices"]["other"]
    elif change == "duplicate_uuid":
        indices["other"]["settings"]["index.uuid"] = "foreignUuid"
    elif change == "cluster_name":
        stats["cluster_name"] = "different"
    elif change == "cluster_uuid":
        state["cluster_uuid"] = "different"
    elif change == "wrong_node":
        stats["nodes"]["different"] = stats["nodes"].pop(NODE)
    elif change == "extra_node":
        stats["nodes"]["different"] = deepcopy(stats["nodes"][NODE])
    elif change == "boolean_success":
        stats["_nodes"]["successful"] = True
    elif change == "float_total":
        stats["_nodes"]["total"] = 1.0
    elif change == "failed_node":
        stats["_nodes"]["failed"] = 1
    elif change == "closed":
        indices["other"]["state"] = "close"
    elif change == "missing_uuid":
        del indices["other"]["settings"]["index.uuid"]
    elif change == "bool_count":
        counts[FOREIGN]["docs"]["count"] = True
    elif change == "float_deleted":
        counts[FOREIGN]["docs"]["deleted"] = 0.0
    elif change == "negative_count":
        counts[FOREIGN]["docs"]["count"] = -1
    elif change == "missing_docs":
        del counts["other"]["docs"]
    else:
        counts["other"]["error"] = PRIVATE
    with pytest.raises(ValueError, match="^foreign_inventory_decode_denied$"):
        decode(api, state, stats)


@pytest.mark.parametrize(
    "change",
    [
        "missing_shard",
        "extra_shard",
        "noncanonical_shard",
        "missing_primary",
        "duplicate_primary",
        "missing_replica",
        "extra_replica",
        "assigned_replica",
        "replica_initializing",
        "primary_initializing",
        "primary_relocating",
        "foreign_node",
        "wrong_index",
        "wrong_shard",
        "bool_shard",
        "int_primary",
        "replica_relocating",
        "auto_expand",
        "extra_route_field",
    ],
)
def test_routing_proves_every_exact_primary_and_unassigned_replica(api: Any, change: str) -> None:
    state, stats = fixtures()
    # Validate all physical indices, even a row not selected as foreign.
    shards = state["routing_table"]["indices"]["other"]["shards"]
    primary, replica = shards["0"]
    if change == "missing_shard":
        del shards["1"]
    elif change == "extra_shard":
        shards["2"] = deepcopy(shards["1"])
    elif change == "noncanonical_shard":
        shards["00"] = shards.pop("0")
    elif change == "missing_primary":
        shards["0"] = [replica]
    elif change == "duplicate_primary":
        shards["0"] = [primary, deepcopy(primary)]
    elif change == "missing_replica":
        shards["0"] = [primary]
    elif change == "extra_replica":
        shards["0"].append(deepcopy(replica))
    elif change == "assigned_replica":
        replica.update(state="STARTED", node=NODE)
    elif change == "replica_initializing":
        replica["state"] = "INITIALIZING"
    elif change == "primary_initializing":
        primary["state"] = "INITIALIZING"
    elif change == "primary_relocating":
        primary["relocating_node"] = "another"
    elif change == "foreign_node":
        primary["node"] = "another"
    elif change == "wrong_index":
        primary["index"] = FOREIGN
    elif change == "wrong_shard":
        primary["shard"] = 1
    elif change == "bool_shard":
        primary["shard"] = False
    elif change == "int_primary":
        primary["primary"] = 1
    elif change == "replica_relocating":
        replica["relocating_node"] = NODE
    elif change == "auto_expand":
        state["metadata"]["indices"]["other"]["settings"]["index.auto_expand_replicas"] = "0-all"
    else:
        primary["private_extra"] = PRIVATE
    with pytest.raises(ValueError, match="^foreign_inventory_decode_denied$"):
        decode(api, state, stats)


@pytest.mark.parametrize("field", ["settings", "mappings", "aliases"])
def test_private_metadata_change_cannot_hide_behind_identical_public_projection(
    api: Any, field: str
) -> None:
    state, stats = fixtures()
    before = decode(api, state, stats)
    state["metadata"]["indices"][FOREIGN][field]["private_extra"] = PRIVATE + "-changed"
    after = decode(api, state, stats)
    assert before.entries[0].observation == after.entries[0].observation
    with pytest.raises(ValueError, match="^foreign_inventory_preservation_mismatch$"):
        api.require_same_private_foreign_inventory(before, after)


def test_deleted_tombstone_changes_are_diagnostic_not_live_document_loss(api: Any) -> None:
    state, stats = fixtures()
    before = decode(api, state, stats)
    stats["nodes"][NODE]["indices"]["indices"][FOREIGN]["docs"]["deleted"] = 0
    after = decode(api, state, stats)
    api.require_same_private_foreign_inventory(before, after)
    assert after.entries[0].deleted_docs == 0


def test_equal_metadata_does_not_hide_changed_lucene_count(api: Any) -> None:
    state, stats = fixtures()
    before = decode(api, state, stats)
    stats["nodes"][NODE]["indices"]["indices"][FOREIGN]["docs"]["count"] = 8
    with pytest.raises(ValueError, match="^foreign_inventory_preservation_mismatch$"):
        api.require_same_private_foreign_inventory(before, decode(api, state, stats))


@pytest.mark.parametrize("names", [("missing",), (FOREIGN, FOREIGN), (FOREIGN, "other")])
def test_selection_requires_present_sorted_unique_names(api: Any, names: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="^foreign_inventory_decode_denied$"):
        decode(api, *fixtures(), names)


@pytest.mark.parametrize("wrapped", [False, True])
def test_rag_metadata_cannot_be_relabelled_opaque(api: Any, wrapped: bool) -> None:
    state, stats = fixtures()
    mapping = state["metadata"]["indices"][FOREIGN]["mappings"]
    if wrapped:
        mapping = mapping["_doc"]
    mapping["_meta"] = {"rag": None}
    with pytest.raises(ValueError, match="^foreign_inventory_decode_denied$"):
        decode(api, state, stats)


def test_no_dot_prefix_security_exemption_or_missing_stats_zero_default(api: Any) -> None:
    state, stats = fixtures()
    state["metadata"]["indices"][".security-unclassified"] = deepcopy(
        state["metadata"]["indices"]["other"]
    )
    with pytest.raises(ValueError, match="^foreign_inventory_decode_denied$"):
        decode(api, state, stats)


@pytest.mark.parametrize(
    "bad",
    [b'{"a":1,"a":2}', b'{"x":NaN}', b"\xff", b"{}", b" " * 262145],
    ids=["duplicate", "nan", "utf8", "missing", "large"],
)
def test_malformed_bounded_input_fails_with_fixed_private_safe_code(api: Any, bad: bytes) -> None:
    _, stats = fixtures()
    with pytest.raises(ValueError, match="^foreign_inventory_decode_denied$"):
        api.decode_foreign_inventory(
            bad,
            raw(stats),
            cluster_uuid=CLUSTER,
            cluster_name="original",
            stable_node_id=NODE,
            foreign_names=(FOREIGN,),
        )


def test_counter_kind_cannot_be_compared_as_logical_rag_count(api: Any) -> None:
    original = decode(api, *fixtures())
    entry = original.entries[0]
    forged = replace(entry.observation, count_kind="logical_docs")
    changed = replace(original, entries=(replace(entry, observation=forged),))
    with pytest.raises(ValueError, match="^foreign_inventory_preservation_mismatch$"):
        api.require_same_private_foreign_inventory(original, changed)


def test_pinned_empty_alias_list_proves_only_alias_absence(api: Any) -> None:
    state, stats = fixtures()
    for value in state["metadata"]["indices"].values():
        value["aliases"] = []
    result = decode(api, state, stats)
    assert json.loads(result.entries[0].private_metadata)["aliases"] == []


def test_nonempty_alias_names_cannot_masquerade_as_full_definitions(api: Any) -> None:
    state, stats = fixtures()
    state["metadata"]["indices"][FOREIGN]["aliases"] = ["private-alias"]
    with pytest.raises(ValueError, match="^foreign_inventory_decode_denied$"):
        decode(api, state, stats)


def test_unselected_rag_alias_names_are_retained_for_join_without_claiming_their_definition(
    api: Any,
) -> None:
    state, stats = fixtures()
    state["metadata"]["indices"]["other"]["aliases"] = ["rag-active"]
    state["metadata"]["indices"]["other"]["mappings"]["_doc"]["_meta"] = {"rag": {}}
    result = decode(api, state, stats)
    assert len(result.entries) == 1
    assert json.loads(result.private_physical_inventory) == {
        FOREIGN: "foreignUuid",
        "other": "otherUuid",
    }


@pytest.mark.parametrize("which", ["state", "stats"])
def test_json_numeric_token_cannot_equal_a_string_cluster_identity(api: Any, which: str) -> None:
    state, stats = fixtures()
    state["cluster_name"] = stats["cluster_name"] = "1e1"
    state_raw, stats_raw = raw(state), raw(stats)
    if which == "state":
        state_raw = state_raw.replace(b'"cluster_name": "1e1"', b'"cluster_name": 1e1')
    else:
        stats_raw = stats_raw.replace(b'"cluster_name": "1e1"', b'"cluster_name": 1e1')
    with pytest.raises(ValueError, match="^foreign_inventory_decode_denied$"):
        api.decode_foreign_inventory(
            state_raw,
            stats_raw,
            cluster_uuid=CLUSTER,
            cluster_name="1e1",
            stable_node_id=NODE,
            foreign_names=(FOREIGN,),
        )


def test_closed_public_cardinality_preimage_does_not_include_foreign_name_or_body(api: Any) -> None:
    result = decode(api, *fixtures()).entries[0].observation
    expected = {
        "schema": "opaque_non_rag_v1",
        "count_kind": "lucene_live_docs",
        "uuid": "foreignUuid",
        "count": 7,
    }
    canonical = json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
    assert result.cardinality_sha256 == hashlib.sha256(canonical).hexdigest()


def test_zero_replicas_and_zero_lucene_count_are_valid_when_primary_coverage_is_complete(
    api: Any,
) -> None:
    state, stats = fixtures()
    for name, value in state["metadata"]["indices"].items():
        value["settings"]["index.number_of_replicas"] = "0"
        for shard, copies in state["routing_table"]["indices"][name]["shards"].items():
            state["routing_table"]["indices"][name]["shards"][shard] = copies[:1]
    stats["nodes"][NODE]["indices"]["indices"][FOREIGN]["docs"]["count"] = 0
    assert decode(api, state, stats).entries[0].observation.count == 0


def test_pinned_allocation_diagnostics_do_not_become_restart_equality_fields(api: Any) -> None:
    state, stats = fixtures()
    before = decode(api, state, stats)
    for name, index in state["routing_table"]["indices"].items():
        for shard, copies in index["shards"].items():
            copies[0]["allocation_id"] = {"id": f"allocation-{name}-{shard}"}
            copies[0]["relocation_failure_info"] = {"failed_attempts": 0}
    after = decode(api, state, stats)
    api.require_same_private_foreign_inventory(before, after)


@pytest.mark.parametrize(
    "field,value",
    [
        ("allocation_id", {"id": 1}),
        ("allocation_id", {"id": "valid", "relocation_id": "moving"}),
        ("allocation_id", None),
        ("relocation_failure_info", {"failed_attempts": True}),
        ("relocation_failure_info", {"failed_attempts": -1}),
        ("relocation_failure_info", {"failed_attempts": 0, "unknown": "private"}),
    ],
)
def test_pinned_optional_routing_metadata_has_a_closed_typed_schema(
    api: Any, field: str, value: object
) -> None:
    state, stats = fixtures()
    state["routing_table"]["indices"][FOREIGN]["shards"]["0"][0][field] = value
    with pytest.raises(ValueError, match="^foreign_inventory_decode_denied$"):
        decode(api, state, stats)
