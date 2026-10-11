"""Synthetic main-security rows; pure decoding does not grant creation authority."""

import importlib
import json
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_native import ORIGINAL_IMAGE, OriginalImageReference
from ai_workshop.labs.rag.indexing.access_epoch_security_descriptor_source import (
    ObservedSecurityDescriptor,
)
from tests.unit.labs.rag.indexing import test_access_epoch_foreign_inventory as foreign
from tests.unit.labs.rag.indexing import test_access_epoch_unmanaged_inventory as physical

MODULE = "ai_workshop.labs.rag.indexing.access_epoch_security_inventory"
NAME = ".security-7"


def sample() -> tuple[dict[str, Any], dict[str, Any], ObservedSecurityDescriptor]:
    state, stats, _ = physical.sample()
    row = {
        "state": "open",
        "system": True,
        "aliases": [".security"],
        "settings": {
            "index.uuid": "syntheticSecurityUuid",
            "index.hidden": "true",
            "index.format": "6",
            "index.number_of_shards": "1",
            "index.number_of_replicas": "0",
            "index.auto_expand_replicas": "0-1",
        },
        "mappings": {
            "_meta": {"security-version": "8.14.0", "managed_index_mappings_version": 5},
            "dynamic": "strict",
            "properties": {"username": {"type": "keyword"}},
        },
    }
    state["metadata"]["indices"][NAME] = row
    state["routing_table"]["indices"][NAME] = {
        "shards": {
            "0": [
                {
                    "primary": True,
                    "state": "STARTED",
                    "node": foreign.NODE,
                    "relocating_node": None,
                    "shard": 0,
                    "index": NAME,
                }
            ]
        }
    }
    stats["nodes"][foreign.NODE]["indices"]["indices"][NAME] = {"docs": {"count": 8, "deleted": 0}}
    descriptor = ObservedSecurityDescriptor(
        uuid4(), "a" * 64, "b" * 64, OriginalImageReference(ORIGINAL_IMAGE, "c" * 64, "amd64")
    )
    return state, stats, descriptor


def decode(
    state: dict[str, Any], stats: dict[str, Any], descriptor: ObservedSecurityDescriptor
) -> Any:
    return importlib.import_module(MODULE).decode_main_security_inventory(
        json.dumps(state).encode(),
        json.dumps(stats).encode(),
        cluster_uuid=foreign.CLUSTER,
        cluster_name="original",
        stable_node_id=foreign.NODE,
        descriptor=descriptor,
    )


def test_exact_descriptor_main_joins_complete_physical_sample() -> None:
    state, stats, descriptor = sample()
    result = decode(state, stats, descriptor)
    assert result.name == NAME and result.uuid == "syntheticSecurityUuid" and result.count == 8
    assert len(json.loads(result.private_physical_inventory)) == 4
    assert "username" not in repr(result)


@pytest.mark.parametrize(
    "fault",
    [
        "hidden",
        "system",
        "system_type",
        "format",
        "mapping_version",
        "mapping_bool",
        "security_version",
        "alias",
        "extra_system",
        "node",
        "uuid",
        "source_contract",
        "primary",
        "source_mapping",
        "marker_missing",
    ],
)
def test_unknown_security_row_or_descriptor_is_not_a_prefix_exemption(fault: str) -> None:
    state, stats, descriptor = sample()
    row = state["metadata"]["indices"][NAME]
    if fault == "hidden":
        row["settings"]["index.hidden"] = "false"
    elif fault == "system":
        row["system"] = False
    elif fault == "system_type":
        row["system"] = 1
    elif fault == "format":
        row["settings"]["index.format"] = "7"
    elif fault == "mapping_version":
        row["mappings"]["_meta"]["managed_index_mappings_version"] = 6
    elif fault == "mapping_bool":
        row["mappings"]["_meta"]["managed_index_mappings_version"] = True
    elif fault == "security_version":
        row["mappings"]["_meta"]["security-version"] = "9.5.2"
    elif fault == "alias":
        row["aliases"] = [".security", ".security-tokens"]
    elif fault == "extra_system":
        state["metadata"]["indices"]["other"]["system"] = True
    elif fault == "node":
        stats["_nodes"]["failed"] = 1
    elif fault == "uuid":
        row["settings"]["index.uuid"] = state["metadata"]["indices"]["other"]["settings"][
            "index.uuid"
        ]
    elif fault == "source_contract":
        descriptor = replace(descriptor, source_contract="unknown")
    elif fault == "primary":
        descriptor = replace(descriptor, primary_name=".security-tokens")
    elif fault == "source_mapping":
        descriptor = replace(descriptor, mapping_version=6)
    else:
        del row["mappings"]["_meta"]["managed_index_mappings_version"]
    with pytest.raises(ValueError, match="^security_inventory_decode_denied$"):
        decode(state, stats, descriptor)


@pytest.mark.parametrize("aliases", [[".security"], {".security": {}}])
def test_security_alias_cannot_have_another_target_in_the_complete_map(aliases: Any) -> None:
    state, stats, descriptor = sample()
    state["metadata"]["indices"]["other"]["aliases"] = aliases
    with pytest.raises(ValueError, match="^security_inventory_decode_denied$"):
        decode(state, stats, descriptor)
