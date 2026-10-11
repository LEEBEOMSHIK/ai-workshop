"""Complete recorded inventory orchestration with private synthetic captures."""

import importlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_inventory_binding import InventoryReadBinding
from ai_workshop.labs.rag.indexing.access_epoch_inventory_commands import InventoryCommands
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    ReservedCutoverAction,
)

namespace_case: Any = importlib.import_module(
    "tests.unit.labs.rag.indexing.test_access_epoch_namespace_source"
).case


class Issuer:
    def __init__(self, epoch: Any, binding: Any) -> None:
        self.epoch, self.binding = epoch, binding

    def assert_issued(self, value: Any) -> Any:
        if value is not self.binding:
            raise ValueError("synthetic_private")


class Reader:
    def __init__(self, c: Any) -> None:
        self.binding, self.factory = c.binding, c.issuer
        self.commands = InventoryCommands(self.binding, self.factory)
        self.case = c
        self.issued: set[Any] = set()
        self.calls: list[Any] = []

    async def read(self, parent: Any, command: Any, round: Any) -> Any:
        m = importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_inventory_process")
        self.commands.assert_issued(command)
        self.calls.append((round, command.purpose, command.index_name))
        value = self.case.responses[command.purpose]
        value = json.loads(json.dumps(value))
        if self.case.change:
            self.case.change(round, command.purpose, value)
        observed = m.CapturedInventoryRead(
            parent,
            "original",
            round,
            command.purpose,
            command.index_name,
            json.dumps(value).encode(),
        )
        self.issued.add(observed)
        return observed

    def assert_issued(self, capture: Any) -> Any:
        if capture not in self.issued:
            raise ValueError("synthetic_private")

    async def revalidate(self, parent: Any) -> Any:
        self.factory.assert_issued(self.binding)


@pytest.fixture
def case(monkeypatch: Any) -> Any:
    m = importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_inventory_collection")
    profile, build = uuid4(), uuid4()
    name = f"rag-{profile}-{build}"
    permissions = AccessEpochPermissions("rag", ((profile, None),))
    epoch = SimpleNamespace(
        original=SimpleNamespace(
            cluster_uuid="syntheticCluster",
            stable_node_id="syntheticNode",
            ephemeral_id="syntheticEphemeral",
            jvm_start_at=datetime(2026, 10, 2, tzinfo=UTC),
        )
    )
    binding = InventoryReadBinding(
        "original", uuid4(), uuid4(), uuid4(), uuid4(), "a" * 64, permissions, None
    )
    parent = ReservedCutoverAction(
        binding.parent_action_id,
        binding.execution_id,
        3,
        CutoverActionKind.STOP_OLD,
        ControlExpectedIdentity("{}", 2),
        str(uuid4()),
    )
    settings = {
        "index.uuid": "syntheticIndexUuid",
        "index.creation_date": "1700000000000",
        "index.number_of_shards": "1",
        "index.number_of_replicas": "0",
        "index.version.created": "9050299",
    }
    mappings = {
        "properties": {
            key: {"type": "integer" if key == "rag_mapping_version" else "keyword"}
            for key in (
                "projection_id",
                "index_build_id",
                "indexing_profile_id",
                "rag_mapping_version",
            )
        },
        "_meta": {
            "rag": {
                "mapping_version": 1,
                "index_build_id": str(build),
                "projection_id": str(uuid4()),
                "indexing_profile_id": str(profile),
                "vector_dimension": 768,
            }
        },
    }
    metadata = {"settings": settings, "defaults": {}, "mappings": mappings, "aliases": {}}
    state = {
        "cluster_name": "original",
        "cluster_uuid": "syntheticCluster",
        "metadata": {
            "indices": {
                name: {
                    "state": "open",
                    "settings": settings,
                    "mappings": {"_doc": mappings},
                    "aliases": [],
                }
            }
        },
        "routing_table": {
            "indices": {
                name: {
                    "shards": {
                        "0": [
                            {
                                "primary": True,
                                "state": "STARTED",
                                "node": "syntheticNode",
                                "relocating_node": None,
                                "shard": 0,
                                "index": name,
                            }
                        ]
                    }
                }
            }
        },
    }
    responses = {
        "listing": {
            "cluster_uuid": "syntheticCluster",
            "metadata": {
                "indices": {
                    name: {"state": "open", "settings": {"index.uuid": "syntheticIndexUuid"}}
                }
            },
        },
        "cluster_info": {
            "cluster_uuid": "syntheticCluster",
            "cluster_name": "original",
            "version": {"number": "9.5.2"},
        },
        "cluster_state": state,
        "identity_state": {
            "cluster_uuid": "syntheticCluster",
            "master_node": "syntheticNode",
            "nodes": {"syntheticNode": {"ephemeral_id": "syntheticEphemeral"}},
        },
        "nodes_info": {
            "cluster_name": "original",
            "_nodes": {"total": 1, "successful": 1, "failed": 0},
            "nodes": {"syntheticNode": {"jvm": {"start_time_in_millis": 1790899200000}}},
        },
        "nodes_docs": {
            "cluster_name": "original",
            "_nodes": {"total": 1, "successful": 1, "failed": 0},
            "nodes": {
                "syntheticNode": {
                    "indices": {"indices": {name: {"docs": {"count": 3, "deleted": 0}}}}
                }
            },
        },
        "metadata": {name: metadata},
        "count": {"count": 3, "_shards": {"total": 1, "successful": 1, "failed": 0, "skipped": 0}},
        "provenance_count": {
            "count": 3,
            "_shards": {"total": 1, "successful": 1, "failed": 0, "skipped": 0},
        },
    }
    c = SimpleNamespace(
        m=m, epoch=epoch, binding=binding, parent=parent, responses=responses, change=None
    )
    c.issuer = Issuer(epoch, binding)
    c.reader = Reader(c)
    monkeypatch.setattr(m, "RecordedInventoryReads", Reader)
    c.collector = m.RecordedInventoryCollector(c.reader)
    return c


@pytest.mark.asyncio
async def test_complete_two_passes_and_three_listings_retain_only_issued_collection(
    case: Any,
) -> None:
    result = await case.collector.collect(case.parent)
    case.collector.assert_issued(result)
    assert len(result.rag_entries) == 1
    assert result.rag_entries[0].observation.count == 3
    assert len(result.foreign.entries) == 0
    assert [r for r, p, n in case.reader.calls if p == "listing"] == [1, 2, 3]
    first_node = next(
        i for i, (r, p, n) in enumerate(case.reader.calls) if r == 1 and p == "nodes_info"
    )
    last_node = next(
        i for i, (r, p, n) in enumerate(case.reader.calls) if r == 2 and p == "nodes_info"
    )
    metadata_positions = [i for i, (r, p, n) in enumerate(case.reader.calls) if p == "metadata"]
    assert first_node < min(metadata_positions) <= max(metadata_positions) < last_node
    with pytest.raises(ValueError, match="inventory_collection_denied"):
        case.collector.assert_issued(replace(result))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    (
        "missing_index",
        "changed_uuid",
        "changed_private_mapping",
        "count_mismatch",
        "topology_drift",
        "boolean_node_success",
        "state_private_mapping",
    ),
)
async def test_partial_or_drifting_capture_never_issues_complete_inventory(
    case: Any, change: Any
) -> None:
    def mutate(round: Any, purpose: Any, value: Any) -> Any:
        if change == "missing_index" and purpose == "cluster_state":
            value["metadata"]["indices"].clear()
        elif change == "changed_uuid" and round == 3 and purpose == "listing":
            next(iter(value["metadata"]["indices"].values()))["settings"]["index.uuid"] = (
                "different"
            )
        elif change == "changed_private_mapping" and round == 2 and purpose == "metadata":
            next(iter(value.values()))["mappings"]["_meta"]["private"] = "synthetic-private-content"
        elif change == "count_mismatch" and purpose == "provenance_count":
            value["count"] = 2
        elif change == "topology_drift" and round == 2 and purpose == "identity_state":
            value["nodes"]["syntheticNode"]["ephemeral_id"] = "different"
        elif change == "boolean_node_success" and purpose == "nodes_info":
            value["_nodes"]["successful"] = True
        elif change == "state_private_mapping" and round == 2 and purpose == "cluster_state":
            next(iter(value["metadata"]["indices"].values()))["mappings"]["_doc"]["_meta"][
                "private"
            ] = "synthetic-private"

    case.change = mutate
    with pytest.raises(ValueError, match="^inventory_collection_denied$"):
        await case.collector.collect(case.parent)


@pytest.mark.asyncio
async def test_foreign_count_is_separate_without_foreign_index_reads(case: Any) -> None:
    state = case.responses["cluster_state"]
    foreign = "synthetic-private-foreign-name"
    row = deepcopy(next(iter(state["metadata"]["indices"].values())))
    row["settings"]["index.uuid"] = "syntheticForeignUuid"
    row["mappings"] = {"_doc": {"_meta": {"private": "synthetic-private-content"}}}
    state["metadata"]["indices"][foreign] = row
    route = deepcopy(next(iter(state["routing_table"]["indices"].values())))
    route["shards"]["0"][0]["index"] = foreign
    state["routing_table"]["indices"][foreign] = route
    case.responses["nodes_docs"]["nodes"]["syntheticNode"]["indices"]["indices"][foreign] = {
        "docs": {"count": 8, "deleted": 0}
    }
    case.responses["listing"]["metadata"]["indices"][foreign] = {
        "state": "open",
        "settings": {"index.uuid": "syntheticForeignUuid"},
    }
    result = await case.collector.collect(case.parent)
    assert len(result.rag_entries) == 1
    assert result.foreign.entries[0].observation.count_kind == "lucene_live_docs"
    assert result.foreign.entries[0].observation.count == 8
    assert all(name != foreign for _, _, name in case.reader.calls)
    assert "synthetic-private-content" not in repr(result)


@pytest.mark.asyncio
async def test_late_owner_loss_prevents_issued_collection(case: Any) -> None:
    async def lost(parent: Any) -> Any:
        raise ValueError("synthetic-private-generation")

    case.reader.revalidate = lost
    with pytest.raises(ValueError, match="^inventory_collection_denied$"):
        await case.collector.collect(case.parent)


@pytest.mark.asyncio
async def test_mutated_nested_public_count_cannot_keep_collection_authority(case: Any) -> None:
    result = await case.collector.collect(case.parent)
    object.__setattr__(result.rag_entries[0].observation, "count", True)
    with pytest.raises(ValueError, match="^inventory_collection_denied$"):
        case.collector.assert_issued(result)


@pytest.fixture
async def physical_case(namespace_case: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    ns = namespace_case
    nst = importlib.import_module("tests.unit.labs.rag.indexing.test_access_epoch_namespace_source")
    nst.add_legacy(ns, uuid4(), prefix="outside")
    nst.add_legacy(ns, uuid4())
    ns.profiles.append((ns.source.LEGACY_DOCUMENT_PROCESSING_PROFILE_ID, "document_processing"))
    namespace = await ns.issuer.observe(ns.snapshot)
    companion = ns.issuer.unmanaged(namespace)
    appmod = importlib.import_module(
        "tests.unit.labs.rag.indexing.test_access_epoch_app_retirement"
    )
    df = appmod.df
    setup = df.setup

    def aligned() -> Any:
        values = list(setup())
        old = values[1]
        claim = replace(old.binding.claim, snapshot=ns.snapshot)
        values[1] = replace(
            old, original=ns.observed.identity, binding=replace(old.binding, claim=claim)
        )
        return tuple(values)

    monkeypatch.setattr(df, "setup", aligned)
    app_generator = appmod.app_case.__wrapped__()
    app = next(app_generator)
    bindings = importlib.import_module(
        "tests.unit.labs.rag.indexing.test_access_epoch_inventory_binding"
    )
    b = await bindings.original_case(app)
    b.factory = bindings.module().InventoryReadBindingFactory.for_original(
        app.epoch, app.repo, app.journal, namespace.permissions, b.history, app.runner
    )
    binding = await bindings.create(b, "original")
    modules = importlib.import_module(
        "ai_workshop.labs.rag.indexing.access_epoch_inventory_process"
    )
    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_process._binary_sha", lambda: "c" * 64
    )
    process = importlib.import_module("ai_workshop.infrastructure.local.control_process_windows")
    kernel_type = importlib.import_module(
        "tests.unit.labs.rag.indexing.test_access_epoch_final_auth_process"
    ).Kernel
    state = deepcopy(ns.metadata)
    state["cluster_name"] = ns.observed.cluster_name
    rows = state["metadata"]["indices"]
    rows["synthetic-foreign"] = {
        "state": "open",
        "system": False,
        "settings": {
            "index.uuid": "foreignUuid",
            "index.creation_date": "1700000000000",
            "index.number_of_shards": "1",
            "index.number_of_replicas": "0",
            "index.version.created": "9050299",
        },
        "mappings": {"properties": {"text": {"type": "text"}}},
        "aliases": [],
    }
    state["routing_table"] = {
        "indices": {
            name: {
                "shards": {
                    "0": [
                        {
                            "primary": True,
                            "state": "STARTED",
                            "node": ns.observed.identity.stable_node_id,
                            "relocating_node": None,
                            "shard": 0,
                            "index": name,
                        }
                    ]
                }
            }
            for name in rows
        }
    }
    listing = {
        "cluster_uuid": ns.snapshot.cluster_uuid,
        "metadata": {
            "indices": {
                name: {
                    "state": row["state"],
                    "settings": {"index.uuid": row["settings"]["index.uuid"]},
                }
                for name, row in rows.items()
            }
        },
    }
    node = ns.observed.identity.stable_node_id
    managed = rows[ns.wire.NAME]
    responses = {
        "listing": listing,
        "cluster_info": {
            "cluster_uuid": ns.snapshot.cluster_uuid,
            "cluster_name": ns.observed.cluster_name,
            "version": {"number": "9.5.2"},
        },
        "cluster_state": state,
        "identity_state": {
            "cluster_uuid": ns.snapshot.cluster_uuid,
            "master_node": node,
            "nodes": {node: {"ephemeral_id": ns.observed.identity.ephemeral_id}},
        },
        "nodes_info": {
            "cluster_name": ns.observed.cluster_name,
            "_nodes": {"total": 1, "successful": 1, "failed": 0},
            "nodes": {
                node: {
                    "jvm": {
                        "start_time_in_millis": int(
                            ns.observed.identity.jvm_start_at.timestamp() * 1000
                        )
                    }
                }
            },
        },
        "nodes_docs": {
            "cluster_name": ns.observed.cluster_name,
            "_nodes": {"total": 1, "successful": 1, "failed": 0},
            "nodes": {
                node: {
                    "indices": {
                        "indices": {name: {"docs": {"count": 3, "deleted": 0}} for name in rows}
                    }
                }
            },
        },
        "metadata": {
            ns.wire.NAME: {
                "settings": managed["settings"],
                "defaults": {},
                "mappings": managed["mappings"]["_doc"],
                "aliases": {alias: {} for alias in managed["aliases"]},
            }
        },
        "count": {"count": 3, "_shards": {"total": 1, "successful": 1, "failed": 0, "skipped": 0}},
        "provenance_count": {
            "count": 3,
            "_shards": {"total": 1, "successful": 1, "failed": 0, "skipped": 0},
        },
    }
    order = [
        "listing",
        "cluster_info",
        "cluster_state",
        "identity_state",
        "nodes_info",
        "nodes_docs",
        "metadata",
        "count",
        "provenance_count",
        "listing",
        "metadata",
        "count",
        "provenance_count",
        "cluster_info",
        "cluster_state",
        "identity_state",
        "nodes_info",
        "nodes_docs",
        "listing",
    ]
    value = SimpleNamespace(
        ns=ns,
        namespace=namespace,
        companion=companion,
        binding=binding,
        factory=b.factory,
        app=app,
        parent=b.parent,
        responses=responses,
        order=order,
    )

    def make() -> Any:
        kernel = kernel_type([json.dumps(responses[p]).encode() + b"\n200" for p in order])
        reader = modules.RecordedInventoryReads(
            b.factory, binding, app.repo, app.journal, process.WindowsControlProcess(kernel)
        )
        m = importlib.import_module(
            "ai_workshop.labs.rag.indexing.access_epoch_inventory_collection"
        )
        value.kernel, value.reader = kernel, reader
        value.collector = m.RecordedInventoryCollector(
            reader, namespace_source=ns.issuer, namespace=namespace
        )
        return value.collector

    value.make = make
    try:
        yield value
    finally:
        app_generator.close()


async def test_actual_source_physical_capture_precedes_original_completion_without_extra_reads(
    physical_case: Any,
) -> None:
    c = physical_case
    collector = c.make()
    physical = await collector.capture_physical(c.parent)
    assert collector.assert_physical_issued(physical) is None
    assert len(physical.listings) == 3
    assert len(physical.rag_entries) == 1
    assert len(physical.unmanaged_passes[0].entries) == 2
    assert len(physical.unmanaged_passes[0].private_physical_inventory) > 0
    before = c.kernel.created
    result = await collector.complete_original(c.parent, physical)
    assert result.physical is physical and result.unmanaged is physical.unmanaged_passes[1]
    assert len(result.foreign.entries) == 1
    assert c.kernel.created == before == 19
    collector.assert_issued(result)
    assert all(
        capture.index_name not in {e.name for e in c.companion.entries}
        for capture in physical.captures
    )
    assert "private_metadata" not in repr(physical)
    with pytest.raises(ValueError):
        await collector.complete_original(c.parent, physical)


@pytest.mark.parametrize(
    "change",
    ["missing_system", "system_type", "unmanaged_mapping", "unlisted", "route_gap", "stats_gap"],
)
async def test_physical_capture_denies_any_global_or_source_companion_gap(
    physical_case: Any, change: str
) -> None:
    c = physical_case
    rows = c.responses["cluster_state"]["metadata"]["indices"]
    if change == "missing_system":
        rows["synthetic-foreign"].pop("system")
    elif change == "system_type":
        rows["synthetic-foreign"]["system"] = 0
    elif change == "unmanaged_mapping":
        rows[c.companion.entries[0].name]["mappings"]["_doc"]["_meta"]["note"] = "synthetic"
    elif change == "unlisted":
        c.responses["listing"]["metadata"]["indices"].pop(c.companion.entries[0].name)
    elif change == "route_gap":
        c.responses["cluster_state"]["routing_table"]["indices"].pop("synthetic-foreign")
    else:
        c.responses["nodes_docs"]["nodes"][c.ns.observed.identity.stable_node_id]["indices"][
            "indices"
        ].pop("synthetic-foreign")
    collector = c.make()
    with pytest.raises(ValueError, match="^inventory_collection_denied$"):
        await collector.capture_physical(c.parent)
    created = c.kernel.created
    with pytest.raises(ValueError):
        await collector.capture_physical(c.parent)
    assert c.kernel.created == created


@pytest.mark.parametrize(
    "change",
    [
        "copy",
        "parent",
        "topology",
        "rag_count",
        "unmanaged_uuid",
        "packet",
        "capture",
        "source",
        "namespace",
        "companion",
    ],
)
async def test_physical_exact_source_parent_and_nested_signature_are_revalidated(
    physical_case: Any, change: str
) -> None:
    c = physical_case
    collector = c.make()
    cap = await collector.capture_physical(c.parent)
    if change == "copy":
        cap = replace(cap)
    elif change == "parent":
        object.__setattr__(cap, "parent", replace(cap.parent))
    elif change == "topology":
        object.__setattr__(cap.topology, "ephemeral_id", "foreign")
    elif change == "rag_count":
        object.__setattr__(cap.rag_entries[0].observation, "count", True)
    elif change == "unmanaged_uuid":
        object.__setattr__(cap.unmanaged_passes[0].entries[0].index_build_id, "int", uuid4().int)
    elif change == "packet":
        object.__setattr__(cap, "first_packets", ())
    elif change == "capture":
        object.__setattr__(cap.captures[0], "private_body", b"{}")
    elif change == "source":
        collector.namespace_source = c.ns.source.OriginalNamespaceSource(
            c.ns.settings, c.ns.original, c.ns.observed
        )
    elif change == "namespace":
        collector.namespace = replace(c.namespace)
    else:
        object.__setattr__(c.companion.entries[0], "reason", "unknown")
    with pytest.raises(ValueError):
        collector.assert_physical_issued(cap)


async def test_system_creation_is_only_physical_capture_not_original_authority(
    physical_case: Any,
) -> None:
    c = physical_case
    c.responses["cluster_state"]["metadata"]["indices"]["synthetic-foreign"]["system"] = True
    collector = c.make()
    cap = await collector.capture_physical(c.parent)
    before = c.kernel.created
    with pytest.raises(ValueError):
        await collector.complete_original(c.parent, cap)
    assert c.kernel.created == before


@pytest.mark.parametrize("mutation", ["capture_list", "foreign_copy", "topology_copy", "rag_tuple"])
async def test_new_capabilities_reject_equal_nested_object_substitution(
    physical_case: Any, mutation: str
) -> None:
    c = physical_case
    collector = c.make()
    cap = await collector.capture_physical(c.parent)
    if mutation == "capture_list":
        object.__setattr__(cap, "captures", list(cap.captures))
        with pytest.raises(ValueError):
            collector.assert_physical_issued(cap)
        return
    completed = await collector.complete_original(c.parent, cap)
    if mutation == "foreign_copy":
        object.__setattr__(completed, "foreign", replace(completed.foreign))
    elif mutation == "topology_copy":
        object.__setattr__(completed, "topology", replace(completed.topology))
    else:
        object.__setattr__(
            completed, "rag_entries", tuple(replace(e) for e in completed.rag_entries)
        )
    with pytest.raises(ValueError):
        collector.assert_issued(completed)


@pytest.mark.parametrize(
    "source,namespace", [(object(), None), (None, object()), (object(), object())]
)
async def test_constructor_rejects_unissued_source_pair_without_calling_caller(
    case: Any, source: Any, namespace: Any
) -> None:
    with pytest.raises(ValueError, match="^inventory_collection_denied$"):
        case.m.RecordedInventoryCollector(case.reader, namespace_source=source, namespace=namespace)


async def test_legacy_does_not_issue_physical_or_secure_completion(case: Any) -> None:
    with pytest.raises(ValueError):
        await case.collector.capture_physical(case.parent)
    assert not case.reader.calls
    object.__setattr__(case.binding, "phase", "bootstrap")
    with pytest.raises(ValueError):
        await case.collector.collect(case.parent)
    assert not case.reader.calls


@pytest.mark.parametrize("moment", ["capture", "complete"])
async def test_fresh_db_generation_loss_stops_new_capability_issuance(
    physical_case: Any, moment: str
) -> None:
    c = physical_case
    collector = c.make()
    cap = None if moment == "capture" else await collector.capture_physical(c.parent)
    count = c.kernel.created
    c.app.repo.state = replace(c.app.repo.state, executor_generation="foreign")
    with pytest.raises(ValueError):
        if cap is None:
            await collector.capture_physical(c.parent)
        else:
            await collector.complete_original(c.parent, cap)
    assert c.kernel.created == count
    assert not collector._issued


@pytest.mark.parametrize("fault", ["cancel", "nonzero", "resume_ack"])
async def test_helper_failure_poison_is_preserved_and_never_replayed(
    physical_case: Any, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    import asyncio

    c = physical_case
    collector = c.make()
    error: type[BaseException]
    if fault == "cancel":

        def cancel(name: str) -> None:
            if name == "create":
                raise asyncio.CancelledError()

        c.kernel.before = cancel
        error = asyncio.CancelledError
    elif fault == "nonzero":
        monkeypatch.setattr(c.kernel, "exit_code", lambda _: 1)
        error = ValueError
    else:
        monkeypatch.setattr(c.kernel, "resume", lambda _: 0)
        error = ValueError
    with pytest.raises(error):
        await collector.capture_physical(c.parent)
    count = c.kernel.created
    assert not collector._physical and not collector._issued
    with pytest.raises(ValueError):
        await collector.capture_physical(c.parent)
    assert c.kernel.created == count


async def test_new_source_collect_is_exact_original_convenience(physical_case: Any) -> None:
    c = physical_case
    collector = c.make()
    result = await collector.collect(c.parent)
    assert result.physical is not None and result.unmanaged is not None
    collector.assert_issued(result)
    assert c.kernel.created == 19


@pytest.mark.parametrize(
    "part", ["foreign_count", "unmanaged_count", "global_metadata", "second_listing", "topology"]
)
async def test_second_sample_drift_cannot_be_completed(physical_case: Any, part: str) -> None:
    c = physical_case
    collector = c.make()
    outputs = c.kernel.outputs
    index = (
        17
        if part in {"foreign_count", "unmanaged_count"}
        else 14
        if part == "global_metadata"
        else 18
        if part == "second_listing"
        else 15
    )
    value = json.loads(outputs[index].rsplit(b"\n", 1)[0])
    if part in {"foreign_count", "unmanaged_count"}:
        name = "synthetic-foreign" if part == "foreign_count" else c.companion.entries[0].name
        value["nodes"][c.ns.observed.identity.stable_node_id]["indices"]["indices"][name]["docs"][
            "count"
        ] += 1
    elif part == "global_metadata":
        value["metadata"]["indices"]["synthetic-foreign"]["mappings"]["extra"] = {"type": "keyword"}
    elif part == "second_listing":
        value["metadata"]["indices"]["synthetic-foreign"]["settings"]["index.uuid"] = "different"
    else:
        value["nodes"][c.ns.observed.identity.stable_node_id]["ephemeral_id"] = "different"
    outputs[index] = json.dumps(value).encode() + b"\n200"
    with pytest.raises(ValueError):
        cap = await collector.capture_physical(c.parent)
        await collector.complete_original(c.parent, cap)
    assert not collector._issued


@pytest.mark.parametrize("sample", [1, 2])
@pytest.mark.parametrize("part", ["settings", "mappings", "alias_names", "alias_options"])
async def test_managed_global_per_index_join_is_required_in_each_sample(
    physical_case: Any, sample: int, part: str
) -> None:
    c = physical_case
    collector = c.make()
    name = c.ns.wire.NAME
    # Preserve both index UUIDs; private detail mismatch must independently deny.
    if part == "alias_options":
        for index in (2, 6, 10, 14):
            packet = json.loads(c.kernel.outputs[index].rsplit(b"\n", 1)[0])
            row = packet["metadata"]["indices"][name] if index in (2, 14) else packet[name]
            row["aliases"] = {"synthetic-alias": {"filter": {"term": {"kind": "first"}}}}
            c.kernel.outputs[index] = json.dumps(packet).encode() + b"\n200"
    index = 2 if sample == 1 else 14
    packet = json.loads(c.kernel.outputs[index].rsplit(b"\n", 1)[0])
    row = packet["metadata"]["indices"][name]
    if part == "settings":
        row["settings"]["index.synthetic_private"] = "changed"
    elif part == "mappings":
        row["mappings"]["_doc"]["_meta"]["synthetic_private"] = "changed"
    elif part == "alias_names":
        row["aliases"] = ["synthetic-added-alias"]
    else:
        row["aliases"]["synthetic-alias"]["filter"]["term"]["kind"] = "second"
    c.kernel.outputs[index] = json.dumps(packet).encode() + b"\n200"
    with pytest.raises(ValueError, match="^inventory_collection_denied$"):
        await collector.capture_physical(c.parent)
    assert not collector._physical and not collector._issued
    assert c.kernel.created <= (9 if sample == 1 else 18)


@pytest.mark.parametrize("part", ["settings", "mappings", "alias_names", "alias_options"])
async def test_consistent_global_packets_cannot_mask_managed_packet_mismatch(
    physical_case: Any, part: str
) -> None:
    c = physical_case
    name = c.ns.wire.NAME
    global_row = c.responses["cluster_state"]["metadata"]["indices"][name]
    managed = c.responses["metadata"][name]
    # Detach shared fixture settings; samples agree with each other, but not
    # with the per-index source packet in either pass.
    global_row["settings"] = deepcopy(global_row["settings"])
    if part == "settings":
        global_row["settings"]["index.synthetic_private"] = "changed"
    elif part == "mappings":
        global_row["mappings"] = deepcopy(global_row["mappings"])
        global_row["mappings"]["_doc"]["_meta"]["synthetic_private"] = "changed"
    elif part == "alias_names":
        global_row["aliases"] = ["synthetic-added-alias"]
    else:
        managed["aliases"] = {"synthetic-alias": {"filter": {"term": {"kind": "first"}}}}
        global_row["aliases"] = {"synthetic-alias": {"filter": {"term": {"kind": "second"}}}}
    collector = c.make()
    with pytest.raises(ValueError, match="^inventory_collection_denied$"):
        await collector.capture_physical(c.parent)
    assert not collector._physical and not collector._issued


@pytest.mark.parametrize("global_aliases", ["list", "dict"])
@pytest.mark.parametrize("mapping_wrapper", [True, False])
async def test_managed_global_join_accepts_exact_packets_and_only_global_fields(
    physical_case: Any, global_aliases: str, mapping_wrapper: bool
) -> None:
    c = physical_case
    name = c.ns.wire.NAME
    managed = c.responses["metadata"][name]
    managed["defaults"]["index.synthetic_default"] = "default-only"
    options = {"filter": {"term": {"kind": "synthetic"}}}
    managed["aliases"] = {"synthetic-alias": options}
    row = c.responses["cluster_state"]["metadata"]["indices"][name]
    row["aliases"] = (
        ["synthetic-alias"] if global_aliases == "list" else deepcopy(managed["aliases"])
    )
    if not mapping_wrapper:
        row["mappings"] = deepcopy(managed["mappings"])
    collector = c.make()
    result = await collector.capture_physical(c.parent)
    collector.assert_physical_issued(result)


@pytest.mark.parametrize("fake_authority", ["protocol", "dict", "none", "copied_physical"])
async def test_secure_completion_cannot_accept_caller_authority_or_original_phase(
    physical_case: Any, fake_authority: str
) -> None:
    from types import SimpleNamespace

    c = physical_case
    collector = c.make()
    physical = await collector.capture_physical(c.parent)
    created = c.kernel.created
    calls: list[str] = []

    def asserted(*args: object) -> None:
        calls.append("caller assertion")

    issuer: Any = SimpleNamespace(assert_issued=asserted, context=object())
    cap: Any = SimpleNamespace(parent=c.parent, physical=physical)
    if fake_authority == "dict":
        issuer, cap = {}, {}
    elif fake_authority == "none":
        issuer, cap = None, None
    elif fake_authority == "copied_physical":
        physical = replace(physical)
    with pytest.raises(ValueError, match="^inventory_collection_denied$"):
        await collector.complete_secure(c.parent, physical, issuer, cap)
    assert calls == [] and c.kernel.created == created and not collector._issued
    with pytest.raises(ValueError):
        await collector.complete_secure(c.parent, physical, issuer, cap)
    assert calls == [] and c.kernel.created == created
