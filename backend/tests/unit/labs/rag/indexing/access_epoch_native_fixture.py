"""Actual-class native assembly over synthetic external I/O boundaries.

No protocol SUT, issued registry, guard or getter is replaced. These helpers
do not establish original-environment history or authorize a live cutover.
"""

from __future__ import annotations

import importlib
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest

from ai_workshop.infrastructure.local.control_process_windows import (
    NativeChild,
)
from ai_workshop.infrastructure.local.credential_store_windows import WindowsCredentialStore
from ai_workshop.infrastructure.local.cutover_control_windows import WindowsControlLock
from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord
from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext
from ai_workshop.labs.rag.indexing.access_epoch_keys import SqlAlchemyEpochKeyRepository
from ai_workshop.labs.rag.indexing.access_epoch_namespace_source import OriginalNamespaceSource
from ai_workshop.labs.rag.indexing.access_epoch_original_security import (
    OriginalSecurityAbsenceReader,
)
from ai_workshop.labs.rag.indexing.access_epoch_repository import SqlAlchemyAccessEpochRepository
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_types import ControlSettlement, CutoverActionKind
from ai_workshop.labs.rag.indexing.alias_recovery import AliasRecoveryService
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexBinding
from ai_workshop.labs.rag.models.models import ProfileRecord
from tests.unit.labs.rag.indexing.test_access_epoch_repository import EpochDatabase
from tests.unit.labs.rag.indexing.test_access_epoch_submission import Kernel, PrivateMemory


class PacketKernel:
    """External owned-process kernel; fixtures enqueue complete raw outputs."""

    def __init__(self) -> None:
        self.outputs: list[bytes] = []
        self.calls: list[tuple[object, ...]] = []
        self.buffers: dict[int, bytearray] = {}
        self.closed: set[int] = set()
        self.created = 0
        self.resumed: set[int] = set()
        self.stdin_writers: dict[int, int] = {}
        self.job_processes: dict[int, int] = {}
        self.before: Any = None

    def thread_id(self) -> int:
        return 9

    def create(
        self, argv: tuple[str, ...], env: dict[str, str], cwd: Path, *, stdin_pipe: bool = False
    ) -> NativeChild:
        if self.before:
            self.before("create")
        if self.created >= len(self.outputs):
            raise AssertionError("synthetic_packet_missing")
        self.calls.append(("create", argv, env, cwd))
        base = 100 + 10 * self.created
        self.buffers[base + 3] = bytearray(self.outputs[self.created])
        self.buffers[base + 4] = bytearray()
        self.job_processes[base + 2] = base
        if stdin_pipe:
            self.stdin_writers[base] = base + 5
        self.created += 1
        return NativeChild(
            base,
            base + 1,
            base + 2,
            base + 3,
            base + 4,
            4000 + self.created,
            str(133700000000000000 + self.created),
            base + 5 if stdin_pipe else None,
        )

    def resume(self, thread: int) -> int:
        self.resumed.add(thread - 1)
        return 1

    def read(self, pipe: int, limit: int) -> bytes:
        part = bytes(self.buffers[pipe][:limit])
        del self.buffers[pipe][:limit]
        return part

    def write(self, pipe: int, data: memoryview) -> int:
        self.calls.append(("private_write", pipe, len(data)))
        return len(data)

    def poll(self, process: int) -> bool:
        writer = self.stdin_writers.get(process)
        return process in self.resumed and (writer is None or writer in self.closed)

    def active_processes(self, job: int) -> int:
        process = self.job_processes.get(job)
        if process is None or process not in self.stdin_writers:
            return 0
        return int(not self.poll(process))

    def exit_code(self, process: int) -> int:
        return 0

    def close(self, handle: int) -> None:
        self.closed.add(handle)


@dataclass
class NativeFixture:
    root: Path
    context: NativeControlContext
    database: Any
    kernel: PacketKernel
    memory: PrivateMemory
    namespace_packets: Any
    stage: str = "prepared"

    def close(self) -> None:
        if self.context._lock is not None and self.context._owner is not None:
            self.context._lock.close(self.context._owner)

    async def prepare_history_and_apps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Real history reader/gate and app retirement, synthetic source bytes.

        Source event recipes are synthetic unit inputs, never original receipts.
        """
        from ai_workshop.infrastructure.local.process_retirement_windows import (
            WindowsProcessRetirement,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_app_retirement import RecordedAppRetirement
        from ai_workshop.labs.rag.indexing.access_epoch_history_gate import OriginalHistoryGate
        from ai_workshop.labs.rag.indexing.access_epoch_original_apps import (
            OriginalApplicationAllowlistIssuer,
        )

        if self.stage != "prepared":
            raise ValueError("synthetic_fixture_stage_mismatch")
        ctx = self.context
        assert ctx.epoch is not None
        assert ctx.journal is not None
        history_packets = importlib.import_module(
            "tests.unit.labs.rag.indexing.test_access_epoch_history"
        )
        reader, recipe, source = history_packets.fixture(
            self.root, monkeypatch, command="python recover-local", exit_code=1
        )
        history_packets.add_support(reader, recipe, source)
        rows = [json.loads(line) for line in source.read_bytes().splitlines()]
        result = rows[5]["payload"]["output"][0]
        wire = json.loads(result["text"])
        wire["output"] = (
            ctx.observation.identity.container_id
            + " true 2026-09-20T00:00:00.000Z 0001-01-01T00:00:00Z\n"
        )
        result["text"] = json.dumps(wire)
        history_packets.rewrite(reader, recipe, source, rows)
        ctx._history = OriginalHistoryGate(
            ctx.epoch, ctx.repository, ctx.journal, reader, ctx.original
        )
        ctx._history_ticket = await ctx._history.verify()
        await ctx._history.assert_verified(ctx._history_ticket)
        original_apps = importlib.import_module(
            "tests.unit.labs.rag.indexing.test_access_epoch_original_apps"
        )
        app_packets = original_apps.source_case.__wrapped__(monkeypatch)
        observed_apps = await app_packets.reader.observe()
        process_packets = importlib.import_module(
            "tests.unit.labs.rag.indexing.test_access_epoch_app_retirement"
        )
        app_kernel = process_packets.ProcessKernel(observed_apps.targets)
        issuer = OriginalApplicationAllowlistIssuer(
            ctx.epoch, ctx.repository, ctx.journal, app_packets.reader
        )
        ctx._apps = RecordedAppRetirement(
            ctx.epoch, ctx.repository, ctx.journal, issuer, WindowsProcessRetirement(app_kernel)
        )
        assert ctx.apps is not None
        ticket = await ctx.apps.prepare()
        parent = await ctx.repository.reserve_action(
            ctx.epoch, CutoverActionKind.STOP_REGISTERED_APPS, ticket.expected
        )
        cap = await ctx.apps.run(parent, ticket)
        ctx._retain_reobserved("app_retirement", cap)
        from datetime import UTC, datetime

        await ctx.repository.settle_action(
            parent,
            ControlSettlement(
                parent.action_id,
                parent.execution_id,
                parent.executor_generation,
                "settled",
                cap.manifest_json,
                datetime.now(UTC),
            ),
        )
        self.namespace_packets.app_kernel = app_kernel
        self.stage = "apps_retired"

    def inventory_packets(self, phase: str) -> dict[str, object]:
        """Complete external ES packet recipe; no captured/issued object recipe."""
        ctx = self.context
        identity = ctx.observation.identity
        state = deepcopy(self.namespace_packets.state)
        state["cluster_name"] = ctx.observation.cluster_name
        node = identity.stable_node_id
        rows = state["metadata"]["indices"]
        ephemeral = identity.ephemeral_id
        jvm = identity.jvm_start_at
        if phase in {"bootstrap", "final"}:
            security_packets = importlib.import_module(
                "tests.unit.labs.rag.indexing.test_access_epoch_security_inventory"
            )
            security_state, _stats, _descriptor = security_packets.sample()
            security_row = deepcopy(security_state["metadata"]["indices"][".security-7"])
            security_row["settings"].update(
                {"index.creation_date": "1700000000000", "index.version.created": "9050299"}
            )
            rows[".security-7"] = security_row
            ephemeral = "synthetic-" + phase + "-ephemeral"
            active = self.context.bootstrap if phase == "bootstrap" else self.context.final
            assert active is not None
            jvm = active.started_at + timedelta(milliseconds=1)
        elif phase != "original":
            raise ValueError("synthetic_secure_packet_recipe_pending")
        state["routing_table"] = {
            "indices": {
                name: {
                    "shards": {
                        "0": [
                            {
                                "primary": True,
                                "state": "STARTED",
                                "node": node,
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
        name = next(name for name in rows if name != ".security-7")
        row = rows[name]
        listing = deepcopy(self.namespace_packets.listing)
        if phase in {"bootstrap", "final"}:
            listing["metadata"]["indices"][".security-7"] = {
                "state": "open",
                "settings": {"index.uuid": "syntheticSecurityUuid", "index.hidden": "true"},
            }
        return {
            "listing": listing,
            "cluster_info": {
                "cluster_uuid": identity.cluster_uuid,
                "cluster_name": ctx.observation.cluster_name,
                "version": {"number": "9.5.2"},
            },
            "cluster_state": state,
            "identity_state": {
                "cluster_uuid": identity.cluster_uuid,
                "master_node": node,
                "nodes": {node: {"ephemeral_id": ephemeral}},
            },
            "nodes_info": {
                "cluster_name": ctx.observation.cluster_name,
                "_nodes": {"total": 1, "successful": 1, "failed": 0},
                "nodes": {node: {"jvm": {"start_time_in_millis": int(jvm.timestamp() * 1000)}}},
            },
            "nodes_docs": {
                "cluster_name": ctx.observation.cluster_name,
                "_nodes": {"total": 1, "successful": 1, "failed": 0},
                "nodes": {
                    node: {
                        "indices": {
                            "indices": {
                                name: {
                                    "docs": {
                                        "count": 8 if name == ".security-7" else 3,
                                        "deleted": 0,
                                    }
                                }
                                for name in rows
                            }
                        }
                    }
                },
            },
            "metadata": {
                name: {
                    "settings": deepcopy(row["settings"]),
                    "defaults": {},
                    "mappings": deepcopy(row["mappings"]["_doc"]),
                    "aliases": {alias: {} for alias in row["aliases"]},
                }
            },
            "count": {
                "count": 3,
                "_shards": {"total": 1, "successful": 1, "failed": 0, "skipped": 0},
            },
            "provenance_count": {
                "count": 3,
                "_shards": {"total": 1, "successful": 1, "failed": 0, "skipped": 0},
            },
        }

    async def capture_original(self) -> Any:
        from ai_workshop.labs.rag.indexing.access_epoch_inventory_binding import (
            InventoryReadBindingFactory,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_inventory_collection import (
            RecordedInventoryCollector,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_inventory_process import (
            RecordedInventoryReads,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_process import (
            RecordedOriginalControlProcess,
        )

        if self.stage != "apps_retired":
            raise ValueError("synthetic_fixture_stage_mismatch")
        ctx = self.context
        assert ctx.epoch is not None
        assert ctx.journal is not None
        assert ctx.native is not None
        assert ctx.history is not None
        assert ctx.apps is not None
        assert ctx.app_retirement is not None
        assert ctx.history_ticket is not None
        process = RecordedOriginalControlProcess(
            ctx.epoch, ctx.repository, ctx.journal, ctx.native, self.root
        )
        ticket = await process.prepare(CutoverActionKind.STOP_OLD)
        parent = await ctx.repository.reserve_action(
            ctx.epoch, CutoverActionKind.STOP_OLD, ticket.expected
        )
        factory = InventoryReadBindingFactory.for_original(
            ctx.epoch, ctx.repository, ctx.journal, ctx.namespace.permissions, ctx.history, ctx.apps
        )
        binding = await factory.create_original(parent, ctx.app_retirement, ctx.history_ticket)
        # Builders/decoders/readers remain actual production classes.
        reads = RecordedInventoryReads(factory, binding, ctx.repository, ctx.journal, ctx.native)
        collector = RecordedInventoryCollector(
            reads, namespace_source=ctx.namespace_source, namespace=ctx.namespace
        )
        ctx._collectors["original"] = collector
        packets = self.inventory_packets("original")
        order = (
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
        )
        self.kernel.outputs.extend(json.dumps(packets[key]).encode() + b"\n200" for key in order)
        cap = await collector.collect(parent)
        ctx._retain("original_inventory", cap)
        self.namespace_packets.stop_process, self.namespace_packets.stop_ticket = process, ticket
        self.namespace_packets.stop_parent = parent
        self.stage = "original_captured"
        return cap

    async def retire_original_and_prepare_tls(self) -> None:
        from ai_workshop.infrastructure.local.tls_bundle import ProjectTlsBundles
        from ai_workshop.labs.rag.indexing.access_epoch_settlement import OriginalDaemonSettlement
        from ai_workshop.labs.rag.indexing.access_epoch_tls import AccessEpochTls
        from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
            DAEMON,
            ORIGINAL_IMAGE_ID,
            FixedCommand,
        )

        if self.stage != "original_captured":
            raise ValueError("synthetic_fixture_stage_mismatch")
        ctx = self.context
        assert ctx.epoch is not None
        assert ctx.journal is not None
        assert ctx.native is not None
        finished = datetime.now(UTC) - timedelta(seconds=5)

        class Docker:
            async def run(self, command: Any) -> str:
                assert ctx.epoch is not None
                if command == FixedCommand.ORIGINAL_DAEMON_ID:
                    return json.dumps({"id": DAEMON, "os": "linux"})
                if command == FixedCommand.ORIGINAL_STOP_METADATA:
                    return json.dumps(
                        {
                            "container_id": ctx.epoch.original.container_id,
                            "image_id": ORIGINAL_IMAGE_ID,
                            "running": False,
                            "restarting": False,
                            "dead": False,
                            "pid": 0,
                            "started_at": "2026-09-20T00:00:00Z",
                            "finished_at": finished.isoformat().replace("+00:00", "Z"),
                        }
                    )
                if command == FixedCommand.ORIGINAL_ALL_IDS:
                    return ""
                raise AssertionError("synthetic_docker_packet_missing")

        settlement = OriginalDaemonSettlement(ctx.epoch, ctx.repository, ctx.journal, Docker())
        runner = self.namespace_packets.stop_process
        action = self.namespace_packets.stop_parent
        self.kernel.outputs.append((ctx.epoch.original.container_id + "\n").encode())
        await runner.run(action, self.namespace_packets.stop_ticket)
        await ctx.repository.settle_action(action, await settlement.observe(action))
        ticket = await runner.prepare(CutoverActionKind.RETIRE_OLD)
        action = await ctx.repository.reserve_action(
            ctx.epoch, CutoverActionKind.RETIRE_OLD, ticket.expected
        )
        self.kernel.outputs.append((ctx.epoch.original.container_id + "\n").encode())
        await runner.run(action, ticket)
        retired = await settlement.observe(action)
        await ctx.repository.settle_action(action, retired)
        self.namespace_packets.retirement_action, self.namespace_packets.retirement_settlement = (
            action,
            retired,
        )
        ctx._tls = AccessEpochTls(
            ctx.epoch,
            ctx.repository,
            ctx.journal,
            ProjectTlsBundles(self.memory),
            ctx.observation.original_ipv4,
        )
        assert ctx.tls is not None
        ticket = await ctx.tls.prepare()
        action = await ctx.repository.reserve_action(
            ctx.epoch, CutoverActionKind.PREPARE_TLS, ticket.expected
        )
        assets = await ctx.tls.execute(action, ticket)
        await ctx.repository.settle_action(
            action,
            ControlSettlement(
                action.action_id,
                action.execution_id,
                action.executor_generation,
                "settled",
                assets.manifest_json,
                datetime.now(UTC),
            ),
        )
        ctx._retain_reobserved("tls_assets", await ctx.tls.read_settled(action))
        # Only six fixture leaf paths are mirrored to unit temp storage.
        assert ctx.tls_assets is not None
        for location in ctx.tls_assets.leaf_locations:
            path = Path(location)
            assert path.is_relative_to(self.root)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.memory.files[str(path)])
        cfg = self.root / "infrastructure/elasticsearch/elasticsearch-secured.yml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_bytes(
            (
                Path(__file__).parents[6] / "infrastructure/elasticsearch/elasticsearch-secured.yml"
            ).read_bytes()
        )
        self.stage = "tls_prepared"

    async def start_bootstrap(self) -> None:
        await self._start_deployment(CutoverActionKind.START_BOOTSTRAP)

    async def start_final(self) -> None:
        await self._start_deployment(CutoverActionKind.START_SECURED)

    async def _start_deployment(self, kind: CutoverActionKind) -> None:
        from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_binding import (
            BootstrapBindingFactory,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_deployment import (
            DeploymentCommands,
            RetiredPredecessor,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_deployment_process import (
            FixedDeploymentInventory,
            RecordedDeploymentControlProcess,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_deployment_settlement import (
            DeploymentDaemonSettlement,
            FixedDeploymentDaemonReads,
        )
        from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
            DAEMON,
            ORIGINAL_IMAGE_ID,
            FixedCommand,
        )

        boot = kind == CutoverActionKind.START_BOOTSTRAP
        if kind not in {CutoverActionKind.START_BOOTSTRAP, CutoverActionKind.START_SECURED}:
            raise ValueError("synthetic_fixture_kind_mismatch")
        if self.stage != ("tls_prepared" if boot else "bootstrap_retired"):
            raise ValueError("synthetic_fixture_stage_mismatch")
        ctx = self.context
        assert ctx.epoch is not None
        assert ctx.journal is not None
        assert ctx.native is not None
        assert ctx.tls_assets is not None
        assert ctx.tls is not None
        assert ctx.original_inventory is not None
        if boot:
            builder = DeploymentCommands(
                ctx.epoch,
                ctx.tls_assets,
                ctx.observation.image.manifest_digest,
                ctx.observation.cluster_name,
                ctx.observation.network_subnet,
                ctx.observation.network_gateway,
                tuple(entry.observation for entry in ctx.original_inventory.rag_entries),
            )
            ctx._deployment = builder
        else:
            assert ctx.deployment is not None
            builder = ctx.deployment
        values: dict[object, str] = {
            FixedCommand.ORIGINAL_DAEMON_ID: json.dumps({"id": DAEMON, "os": "linux"}),
            FixedCommand.ORIGINAL_SLOT_INVENTORY: "",
        }

        class Docker:
            async def run(self, command: Any) -> str:
                if command not in values:
                    raise AssertionError("synthetic_deployment_packet_missing")
                return values[command]

        docker = Docker()
        process = RecordedDeploymentControlProcess(
            ctx.epoch,
            ctx.repository,
            builder,
            ctx.journal,
            ctx.native,
            FixedDeploymentInventory(docker),
        )
        ticket = await process.prepare(kind)
        parent = await ctx.repository.reserve_action(ctx.epoch, kind, ticket.expected)
        retired = RetiredPredecessor(
            self.namespace_packets.retirement_action,
            self.namespace_packets.retirement_settlement,
            None if boot else ctx.bootstrap,
        )
        self.kernel.outputs.append(b"synthetic deployment terminal\n")
        await process.run(parent, ticket, retired)
        recipes = importlib.import_module(
            "tests.unit.labs.rag.indexing.test_access_epoch_deployment"
        )
        container = recipes.container_json(
            builder, parent, container_id="d" * 64 if boot else "f" * 64
        )
        moment = datetime.now(UTC) - timedelta(seconds=1)
        container["Created"] = container["State"]["StartedAt"] = moment.isoformat()
        container["Config"]["Image"] = (
            "docker.elastic.co/elasticsearch/elasticsearch:9.5.2@" + builder.manifest_digest
        )
        container["Config"]["Env"][-1] = (
            "AI_WORKSHOP_ES_ORIGINAL_CLUSTER_NAME=" + builder.cluster_name
        )
        values.update(
            {
                FixedCommand.SELECTED_SLOT_CONTAINER: json.dumps([container]),
                FixedCommand.SELECTED_IMAGE_RAW: json.dumps(
                    [
                        {
                            "Id": ORIGINAL_IMAGE_ID,
                            "RepoDigests": [
                                "docker.elastic.co/elasticsearch/elasticsearch@"
                                + builder.manifest_digest
                            ],
                            "Os": "linux",
                            "Architecture": ctx.observation.image.architecture,
                        }
                    ]
                ),
                FixedCommand.SELECTED_VOLUME_RAW: json.dumps(
                    [
                        {
                            "Name": "ai-workshop_elasticsearch-data",
                            "Driver": "local",
                            "Scope": "local",
                            "CreatedAt": "2026-09-01T00:00:00Z",
                            "Options": None,
                            "Mountpoint": (
                                "/var/lib/docker/volumes/ai-workshop_elasticsearch-data/_data"
                            ),
                        }
                    ]
                ),
                FixedCommand.ORIGINAL_ALL_IDS: container["Id"] + "\n",
                FixedCommand.SELECTED_SECURITY_CONFIG: (
                    self.root / "infrastructure/elasticsearch/elasticsearch-secured.yml"
                ).read_text(),
            }
        )
        if not boot:
            selected_network = container["NetworkSettings"]["Networks"]["ai-workshop_default"]
            selected_network.update(
                IPAddress=ctx.observation.original_ipv4,
                Gateway=ctx.observation.network_gateway,
                IPPrefixLen=builder.network.prefixlen,
            )
            values[FixedCommand.SELECTED_SLOT_CONTAINER] = json.dumps([container])
            values[FixedCommand.SELECTED_NETWORK_RAW] = json.dumps(
                [
                    {
                        "Id": selected_network["NetworkID"],
                        "Name": "ai-workshop_default",
                        "Driver": "bridge",
                        "Scope": "local",
                        "Internal": False,
                        "EnableIPv6": False,
                        "IPAM": {
                            "Driver": "default",
                            "Config": [
                                {
                                    "Subnet": ctx.observation.network_subnet,
                                    "Gateway": ctx.observation.network_gateway,
                                }
                            ],
                        },
                        "Containers": {
                            container["Id"]: {"IPv4Address": ctx.observation.original_ipv4 + "/16"}
                        },
                    }
                ]
            )
        settlement = DeploymentDaemonSettlement(
            ctx.epoch,
            ctx.repository,
            ctx.journal,
            builder,
            ctx.tls,
            FixedDeploymentDaemonReads(docker),
        )
        observed, result = await settlement.observe(
            parent, predecessor=None if boot else ctx.bootstrap
        )
        await ctx.repository.settle_action(parent, result)
        ctx._retain("bootstrap" if boot else "final", observed)
        if boot:
            ctx._bootstrap_factory = BootstrapBindingFactory(
                ctx.repository, ctx.journal, builder, ctx.security_source
            )
            assert ctx.bootstrap_factory is not None
            ctx._bootstrap_commands = await ctx.bootstrap_factory.create(
                observed, ctx.absence, ctx.namespace.permissions
            )
        self.namespace_packets.deployment_docker = docker
        self.namespace_packets.deployment_values = values
        self.stage = "bootstrap_started" if boot else "final_started"

    async def prepare_bootstrap_security_and_keys(self) -> None:
        import base64

        from ai_workshop.labs.rag.indexing.access_epoch_admin_process import (
            RecordedBootstrapAdministrator,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_audits import (
            RecordedBootstrapAudits,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_control_native import (
            ConcreteNativeCutoverControl,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_key_process import (
            RecordedBootstrapKeyCommands,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_models import AccessEpochKeyEventRecord
        from ai_workshop.labs.rag.indexing.access_epoch_role_keys import BootstrapRoleKeyGroup
        from ai_workshop.labs.rag.indexing.access_epoch_types import canonical_json

        if self.stage != "bootstrap_started":
            raise ValueError("synthetic_fixture_stage_mismatch")
        ctx = self.context
        assert ctx.epoch is not None
        assert ctx.journal is not None
        assert ctx.native is not None
        assert ctx.deployment is not None
        assert ctx.bootstrap is not None
        assert ctx.bootstrap_commands is not None
        assert ctx.bootstrap_factory is not None
        assert ctx.keys is not None
        assert ctx.store is not None
        ctx._administrator = RecordedBootstrapAdministrator(
            ctx.epoch,
            ctx.repository,
            ctx.deployment,
            ctx.bootstrap,
            ctx.bootstrap_commands,
            ctx.journal,
            ctx.native,
            self.root,
            ctx.bootstrap_factory,
        )
        assert ctx.administrator is not None
        ticket = await ctx.administrator.prepare()
        parent = await ctx.repository.reserve_action(
            ctx.epoch, CutoverActionKind.BOOTSTRAP_ADMIN, ticket.expected
        )
        self.kernel.outputs.append(b"Synthetic20Character\n")
        credential = await ctx.administrator.run(parent, ticket)
        ctx._retain_reobserved("credential", credential)
        ctx._audits = RecordedBootstrapAudits(
            ctx.administrator, ctx.bootstrap_factory, ctx.repository, ctx.journal, ctx.native
        )
        audit_recipes = importlib.import_module(
            "tests.unit.labs.rag.indexing.test_access_epoch_bootstrap_audits"
        )
        auth = audit_recipes.authenticated()
        user = {
            k: v
            for k, v in auth.items()
            if k not in {"authentication_type", "authentication_realm", "lookup_realm"}
        }

        def audit_packets() -> list[bytes]:
            return [
                json.dumps(auth).encode() + b"\n200",
                json.dumps({"elastic": user}).encode() + b"\n200",
                b'{"api_keys": []}\n200',
                b"# fixture empty file realm\n",
                b"",
            ]

        self.kernel.outputs.extend(audit_packets())
        assert ctx.audits is not None and ctx.credential is not None
        cap = await ctx.audits.run(parent, ctx.credential)
        ctx._retain_reobserved("admin_security", cap)
        await ctx.repository.settle_action(
            parent,
            ControlSettlement(
                parent.action_id,
                parent.execution_id,
                parent.executor_generation,
                "settled",
                canonical_json(
                    {
                        "schema_version": 1,
                        "kind": "bootstrap_administrator_verified",
                        "action_id": str(parent.action_id),
                        "execution_id": str(parent.execution_id),
                        "executor_generation": parent.executor_generation,
                        "container_id": credential.container_id,
                        "submission_id": str(credential.submission_id),
                        "security": json.loads(cap.manifest_json),
                    }
                ),
                datetime.now(UTC),
            ),
        )
        control = ConcreteNativeCutoverControl(ctx)
        before = await ctx.revalidate()
        target = control._closed_parent_target(CutoverActionKind.REVOKE_HISTORICAL)
        ticket = ctx.journal.prepare_expected(
            CutoverActionKind.REVOKE_HISTORICAL, before.actions[-1].event_sequence, target
        )
        parent = await ctx.repository.reserve_action(
            ctx.epoch, CutoverActionKind.REVOKE_HISTORICAL, ticket.expected
        )
        self.kernel.outputs.extend(audit_packets())
        assert ctx.audits is not None and ctx.credential is not None
        cap = await ctx.audits.run(parent, ctx.credential)
        ctx._retain_reobserved("historical_security", cap)
        await ctx.repository.settle_action(
            parent,
            ControlSettlement(
                parent.action_id,
                parent.execution_id,
                parent.executor_generation,
                "settled",
                cap.manifest_json,
                datetime.now(UTC),
            ),
        )
        before = await ctx.revalidate()
        target = control._closed_parent_target(CutoverActionKind.ISSUE_ROLE_KEY)
        ticket = ctx.journal.prepare_expected(
            CutoverActionKind.ISSUE_ROLE_KEY, before.actions[-1].event_sequence, target
        )
        parent = await ctx.repository.reserve_action(
            ctx.epoch, CutoverActionKind.ISSUE_ROLE_KEY, ticket.expected
        )
        commands = RecordedBootstrapKeyCommands(
            ctx.epoch,
            parent,
            ctx.repository,
            ctx.keys,
            ctx.bootstrap_commands,
            ctx.journal,
            ctx.native,
            self.root,
        )

        def key_wire(call: str) -> None:
            assert call == "create"
            events = [
                row
                for (kind, _key), row in self.database.rows.items()
                if kind is AccessEpochKeyEventRecord and row.parent_action_id == parent.action_id
            ]
            current = max(events, key=lambda row: row.sequence)
            assert current.outcome == "pending" and current.kind == "issue"
            key_id = "synthetic-" + current.role
            assert ctx.epoch is not None
            name = (
                f"ai-workshop-{ctx.epoch.binding.access_epoch_id}-"
                f"{current.role}-{current.issuance_id}"
            )
            secret = "synthetic-unit-key-" + current.role
            packet = {
                "id": key_id,
                "name": name,
                "api_key": secret,
                "encoded": base64.b64encode((key_id + ":" + secret).encode()).decode(),
            }
            self.kernel.outputs.append(json.dumps(packet).encode() + b"\n200")

        self.kernel.before = key_wire
        try:
            group = BootstrapRoleKeyGroup(
                ctx.epoch,
                parent,
                ctx.keys,
                ctx.bootstrap_commands,
                commands,
                ctx.store,
                ctx.assert_owned,
                ctx.credential.password,
            )
            manifest = await group.advance()
            if manifest is None:
                raise ValueError("synthetic_role_group_incomplete")
        finally:
            self.kernel.before = None
        await ctx.repository.settle_action(
            parent,
            ControlSettlement(
                parent.action_id,
                parent.execution_id,
                parent.executor_generation,
                "settled",
                canonical_json(manifest),
                datetime.now(UTC),
            ),
        )
        self.namespace_packets.key_commands = commands
        self.stage = "role_keys_issued"

    async def capture_bootstrap(self) -> Any:
        """Issue actual physical source at the pending ninth action, no completion DTO."""
        from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_retirement import (
            RecordedBootstrapRetirement,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_final_auth_binding import (
            CompletedKeyReadPort,
            PreparedCredentialReadPort,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_inventory_binding import (
            InventoryReadBindingFactory,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_inventory_collection import (
            RecordedInventoryCollector,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_inventory_process import (
            RecordedInventoryReads,
        )

        if self.stage != "role_keys_issued":
            raise ValueError("synthetic_fixture_stage_mismatch")
        ctx = self.context
        assert ctx.epoch is not None
        assert ctx.journal is not None
        assert ctx.native is not None
        assert ctx.deployment is not None
        assert ctx.bootstrap is not None
        assert ctx.bootstrap_commands is not None
        assert ctx.bootstrap_factory is not None
        assert ctx.keys is not None
        assert ctx.store is not None
        assert ctx.tls is not None
        process = RecordedBootstrapRetirement(
            ctx.epoch,
            ctx.repository,
            ctx.journal,
            ctx.native,
            self.root,
            ctx.deployment,
            ctx.bootstrap,
        )
        ticket = await process.prepare(CutoverActionKind.STOP_BOOTSTRAP)
        parent = await ctx.repository.reserve_action(
            ctx.epoch, CutoverActionKind.STOP_BOOTSTRAP, ticket.expected
        )
        factory = InventoryReadBindingFactory.for_secure(
            ctx.repository,
            cast(CompletedKeyReadPort, ctx.keys),
            ctx.journal,
            ctx.deployment,
            ctx.bootstrap_factory,
            ctx.bootstrap_commands,
            ctx.tls,
            cast(PreparedCredentialReadPort, ctx.store),
        )
        binding = await factory.create_bootstrap(parent, ctx.bootstrap)
        reads = RecordedInventoryReads(factory, binding, ctx.repository, ctx.journal, ctx.native)
        collector = RecordedInventoryCollector(
            reads, namespace_source=ctx.namespace_source, namespace=ctx.namespace
        )
        ctx._collectors["bootstrap"] = collector
        packets = self.inventory_packets("bootstrap")
        order = (
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
        )
        self.kernel.outputs.extend(json.dumps(packets[key]).encode() + b"\n200" for key in order)
        physical = await collector.capture_physical(parent)
        self.namespace_packets.bootstrap_process = process
        self.namespace_packets.bootstrap_ticket = ticket
        self.namespace_packets.bootstrap_parent = parent
        self.namespace_packets.bootstrap_collector = collector
        self.namespace_packets.bootstrap_physical = physical
        self.stage = "bootstrap_physical"
        return parent, collector, physical

    async def complete_bootstrap(self) -> Any:
        """Join the retained physical sample through the context-owned real issuer."""
        if self.stage != "bootstrap_physical":
            raise ValueError("synthetic_fixture_stage_mismatch")
        ctx = self.context
        issuer = ctx.security_inventory_issuer
        assert issuer is not None
        parent = self.namespace_packets.bootstrap_parent
        collector = self.namespace_packets.bootstrap_collector
        physical = self.namespace_packets.bootstrap_physical
        cap = await issuer.observe(parent, collector, physical)
        issuer.assert_issued(cap)
        completed = await collector.complete_secure(parent, physical, issuer, cap)
        ctx._retain("bootstrap_security_inventory", cap)
        ctx._retain("bootstrap_preservation", cap.preservation)
        ctx._retain("bootstrap_inventory", completed)
        assert ctx.bootstrap_security_inventory is cap
        assert ctx.bootstrap_inventory is completed
        self.stage = "bootstrap_completed"
        return cap

    async def retire_bootstrap(self) -> None:
        from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_retirement import (
            BootstrapDaemonSettlement,
        )
        from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
            DAEMON,
            ORIGINAL_IMAGE_ID,
        )

        if self.stage != "bootstrap_completed":
            raise ValueError("synthetic_fixture_stage_mismatch")
        ctx = self.context
        assert ctx.epoch is not None and ctx.journal is not None
        assert ctx.deployment is not None and ctx.bootstrap is not None
        bootstrap = ctx.bootstrap
        finished = datetime.now(UTC) - timedelta(milliseconds=5)
        process = self.namespace_packets.bootstrap_process
        parent = self.namespace_packets.bootstrap_parent

        class Reads:
            async def daemon(self) -> str:
                return json.dumps({"id": DAEMON, "os": "linux"})

            async def metadata(self) -> str:
                return json.dumps(
                    {
                        "container_id": bootstrap.container_id,
                        "image_id": ORIGINAL_IMAGE_ID,
                        "running": False,
                        "restarting": False,
                        "dead": False,
                        "pid": 0,
                        "started_at": json.loads(bootstrap.manifest_json)["docker_started_at"],
                        "finished_at": finished.isoformat().replace("+00:00", "Z"),
                    }
                )

            async def all_ids(self) -> str:
                return ""

        settlement = BootstrapDaemonSettlement(
            ctx.epoch, ctx.repository, ctx.journal, ctx.deployment, bootstrap, Reads()
        )
        self.kernel.outputs.append((bootstrap.container_id + "\n").encode())
        await process.run(parent, self.namespace_packets.bootstrap_ticket)
        await ctx.repository.settle_action(parent, await settlement.observe(parent))
        ticket = await process.prepare(CutoverActionKind.RETIRE_BOOTSTRAP)
        parent = await ctx.repository.reserve_action(
            ctx.epoch, CutoverActionKind.RETIRE_BOOTSTRAP, ticket.expected
        )
        self.kernel.outputs.append((bootstrap.container_id + "\n").encode())
        await process.run(parent, ticket)
        result = await settlement.observe(parent)
        await ctx.repository.settle_action(parent, result)
        self.namespace_packets.retirement_action = parent
        self.namespace_packets.retirement_settlement = result
        self.stage = "bootstrap_retired"

    async def prepare_final_auth(self) -> None:
        from ai_workshop.labs.rag.indexing.access_epoch_final_auth import FinalAuthCommands
        from ai_workshop.labs.rag.indexing.access_epoch_final_auth_binding import (
            CompletedKeyReadPort,
            FinalAuthBindingFactory,
            PreparedCredentialReadPort,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_final_auth_process import (
            RecordedFinalAuthentication,
        )

        if self.stage != "final_started":
            raise ValueError("synthetic_fixture_stage_mismatch")
        ctx = self.context
        assert ctx.epoch is not None and ctx.journal is not None and ctx.native is not None
        assert ctx.keys is not None and ctx.store is not None and ctx.tls is not None
        assert ctx.deployment is not None and ctx.final is not None
        assert ctx.bootstrap_factory is not None and ctx.bootstrap_commands is not None
        factory = FinalAuthBindingFactory(
            ctx.repository,
            cast(CompletedKeyReadPort, ctx.keys),
            ctx.journal,
            ctx.deployment,
            ctx.bootstrap_factory,
            ctx.bootstrap_commands,
            ctx.tls,
            cast(PreparedCredentialReadPort, ctx.store),
        )
        binding = await factory.create(ctx.final)
        commands = FinalAuthCommands(binding, factory)
        ctx._final_auth_factory = factory
        ctx._final_authentication = RecordedFinalAuthentication(
            factory, binding, ctx.deployment, ctx.final, ctx.repository, ctx.journal, ctx.native
        )
        recipes = importlib.import_module(
            "tests.unit.labs.rag.indexing.test_access_epoch_final_auth"
        )
        wire_case = SimpleNamespace(binding=binding, builder=commands, m=recipes.module())
        # Only packet recipes are reused, never that test's fabricated issuer.
        for role in ("reader", "writer", "collector"):
            command = commands.authenticate(role)
            wire = recipes.response(wire_case, recipes.auth_value(wire_case, role))
            authenticated = commands.decode_authenticated(command, wire)
            privilege_command = commands.privileges(authenticated)
            self.kernel.outputs.extend(
                [
                    wire.stdout,
                    recipes.response(
                        wire_case, recipes.privilege_value(wire_case, privilege_command)
                    ).stdout,
                ]
            )
        ticket = await ctx._final_authentication.prepare()
        parent = await ctx.repository.reserve_action(
            ctx.epoch, CutoverActionKind.VERIFY_ACCESS, ticket.expected
        )
        observation = await ctx._final_authentication.run(parent, ticket)
        ctx._retain_reobserved("final_auth", observation)
        self.namespace_packets.final_parent = parent
        self.stage = "final_authenticated"

    async def capture_final(self) -> Any:
        from ai_workshop.labs.rag.indexing.access_epoch_final_auth_binding import (
            CompletedKeyReadPort,
            PreparedCredentialReadPort,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_inventory_binding import (
            InventoryReadBindingFactory,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_inventory_collection import (
            RecordedInventoryCollector,
        )
        from ai_workshop.labs.rag.indexing.access_epoch_inventory_process import (
            RecordedInventoryReads,
        )

        if self.stage != "final_authenticated":
            raise ValueError("synthetic_fixture_stage_mismatch")
        ctx = self.context
        assert ctx.journal is not None and ctx.native is not None
        assert ctx.keys is not None and ctx.store is not None and ctx.tls is not None
        assert ctx.deployment is not None and ctx.final is not None
        assert ctx.bootstrap_factory is not None and ctx.bootstrap_commands is not None
        parent = self.namespace_packets.final_parent
        factory = InventoryReadBindingFactory.for_secure(
            ctx.repository,
            cast(CompletedKeyReadPort, ctx.keys),
            ctx.journal,
            ctx.deployment,
            ctx.bootstrap_factory,
            ctx.bootstrap_commands,
            ctx.tls,
            cast(PreparedCredentialReadPort, ctx.store),
        )
        binding = await factory.create_final(parent, ctx.final)
        reads = RecordedInventoryReads(factory, binding, ctx.repository, ctx.journal, ctx.native)
        collector = RecordedInventoryCollector(
            reads, namespace_source=ctx.namespace_source, namespace=ctx.namespace
        )
        ctx._collectors["final"] = collector
        packets = self.inventory_packets("final")
        order = (
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
        )
        self.kernel.outputs.extend(json.dumps(packets[key]).encode() + b"\n200" for key in order)
        physical = await collector.capture_physical(parent)
        self.namespace_packets.final_collector = collector
        self.namespace_packets.final_physical = physical
        self.stage = "final_physical"
        return parent, collector, physical

    async def complete_final(self) -> Any:
        if self.stage != "final_physical":
            raise ValueError("synthetic_fixture_stage_mismatch")
        ctx = self.context
        issuer = ctx.security_inventory_issuer
        assert issuer is not None
        parent = self.namespace_packets.final_parent
        collector = self.namespace_packets.final_collector
        physical = self.namespace_packets.final_physical
        cap = await issuer.observe(parent, collector, physical)
        completed = await collector.complete_secure(parent, physical, issuer, cap)
        ctx._retain("final_security_inventory", cap)
        ctx._retain("final_preservation", cap.preservation)
        ctx._retain("final_inventory", completed)
        assert ctx.final_security_inventory is cap and ctx.final_inventory is completed
        self.stage = "final_completed"
        return cap

    async def queue_routes(self) -> None:
        """Enqueue external wire bytes; creates no route source or helpers."""
        import base64

        from ai_workshop.labs.rag.indexing.access_epoch_route_commands import RouteProbeKind
        from ai_workshop.labs.rag.indexing.alias_recovery_local_native import DAEMON, FixedCommand

        if self.stage != "final_completed":
            raise ValueError("synthetic_fixture_stage_mismatch")
        ctx = self.context
        assert ctx.route_commands is not None and ctx.tls_assets is not None
        assert ctx.final_authentication is not None
        binding = ctx.final_authentication.binding
        key = next(key for key in binding.keys if key.role == "collector")
        tls = json.loads(ctx.tls_assets.manifest_json)
        packets = self.inventory_packets("final")
        info = packets["nodes_info"]
        assert isinstance(info, dict)
        node = info["nodes"][ctx.observation.identity.stable_node_id]
        node.update(
            {
                "settings": {
                    "xpack.security.enabled": "true",
                    "xpack.security.http.ssl.enabled": "true",
                    "xpack.security.transport.ssl.enabled": "true",
                    "xpack.security.transport.ssl.client_authentication": "required",
                    "remote_cluster_server.enabled": "false",
                },
                "http": {
                    "bound_address": ["0.0.0.0:9200"],
                    "publish_address": ctx.observation.original_ipv4 + ":9200",
                },
                "transport": {
                    "bound_address": ["0.0.0.0:9300"],
                    "publish_address": ctx.observation.original_ipv4 + ":9300",
                    "profiles": {},
                },
                "roles": [
                    "master",
                    "data",
                    "data_content",
                    "data_hot",
                    "data_warm",
                    "data_cold",
                    "data_frozen",
                    "ingest",
                    "ml",
                    "transform",
                ],
            }
        )
        values = self.namespace_packets.deployment_values
        metadata = {
            "daemon_id": json.dumps({"ID": DAEMON, "OSType": "linux"}),
            "container": values[FixedCommand.SELECTED_SLOT_CONTAINER],
            "image": values[FixedCommand.SELECTED_IMAGE_RAW],
            "volume": values[FixedCommand.SELECTED_VOLUME_RAW],
            "network": values[FixedCommand.SELECTED_NETWORK_RAW],
            "all_ids": values[FixedCommand.ORIGINAL_ALL_IDS],
            "security_config": values[FixedCommand.SELECTED_SECURITY_CONFIG],
        }
        for purpose in RouteProbeKind:
            verb = purpose.value.removesuffix("_before").removesuffix("_after")
            if verb in metadata:
                raw = metadata[verb].encode()
            elif verb == "host_wrong_ca":
                raw = json.dumps(
                    {"schema_version": 1, "purpose": purpose.value, "code": "ca_rejected"}
                ).encode()
            else:
                transport = verb.startswith("transport_")
                wire: dict[str, Any] = {
                    "schema_version": 1,
                    "purpose": purpose.value,
                    "code": "https",
                    "protocol": "TLSv1.2" if transport else "TLSv1.3",
                    "chain_verified": True,
                    "leaf_der_sha256": tls[
                        "transport_leaf_der_sha256" if transport else "http_leaf_der_sha256"
                    ],
                }
                if transport:
                    wire["code"] = (
                        "mutual_tls"
                        if verb == "transport_certificate"
                        else "client_certificate_rejected"
                    )
                    if verb == "transport_no_certificate":
                        wire["fatal_alert"] = "certificate_required"
                else:
                    body: Any = {
                        "authentication_type": "api_key",
                        "enabled": True,
                        "username": "elastic",
                        "api_key": {
                            "id": key.key_id,
                            "name": key.name,
                            "managed_by": "elasticsearch",
                        },
                    }
                    status = 200
                    if "anonymous" in verb:
                        status, body = 401, {"status": 401, "error": {"type": "security_exception"}}
                    elif verb in {"nodes_info", "identity_state"}:
                        body = packets[verb]
                    wire.update(
                        status=status, body_b64=base64.b64encode(json.dumps(body).encode()).decode()
                    )
                raw = json.dumps(wire).encode()
            self.kernel.outputs.append(raw)
        self.stage = "routes_queued"

    async def capture_routes(self) -> Any:
        """Run one actual recorder, retaining it for subsequent same-issuer recovery."""
        from ai_workshop.labs.rag.indexing.access_epoch_route_process import RecordedNativeRoutes

        await self.queue_routes()
        ctx = self.context
        assert ctx.route_commands is not None
        runner = RecordedNativeRoutes(ctx, ctx.route_commands)
        before = self.kernel.created
        cap = await runner.observe(self.namespace_packets.final_parent)
        runner.assert_issued(cap)
        assert self.kernel.created - before == 27
        self.namespace_packets.routes_runner = runner
        self.namespace_packets.routes_cap = cap
        self.stage = "routes_captured"
        return cap


def _root_paths(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    # Configured fixture filesystem roots, never altered admission or issuers.
    for name in (
        "deployment",
        "control_native",
        "namespace_source",
        "original_apps",
        "app_retirement",
        "bootstrap_binding",
        "admin_process",
        "final_auth_binding",
        "final_auth_process",
        "inventory_binding",
        "inventory_process",
        "route_commands",
        "route_process",
        "deployment_process",
        "deployment_settlement",
    ):
        mod = importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_" + name)
        monkeypatch.setattr(mod, "PROJECT_ROOT", root)
    deployment = importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_deployment")
    monkeypatch.setattr(deployment, "_COMPOSE", root / "infrastructure/compose")


async def build_native_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> NativeFixture:
    """Build an owned PREPARED epoch with source-issued readonly prerequisites.

    Later stage builders must run real producers on this same graph. This
    foundation deliberately has no historical ticket, app or inventory cap.
    """
    root = tmp_path / "ai-workshop"
    root.mkdir()
    _root_paths(monkeypatch, root)
    packets = importlib.import_module(
        "tests.unit.labs.rag.indexing.test_access_epoch_index_inventory"
    )
    observers = importlib.import_module("tests.unit.labs.rag.indexing.test_access_epoch_native")
    original, _old_snapshot, executor, direct = observers.deployment_case(monkeypatch)
    settings = original.settings
    settings.rag_index_store_id = "rag"
    settings.elasticsearch_index_prefix = "rag"
    settings.database_url = (
        "postgresql+psycopg://synthetic:synthetic@127.0.0.1:15432/ai_workshop_local_clean"
    )
    # Fresh configuration is parsed by the genuine Settings class.
    lines = {
        "SECRET_KEY": settings.secret_key.get_secret_value(),
        "RAG_INDEX_STORE_ID": "rag",
        "RAG_INDEX_CLUSTER_UUID": "cluster",
        "ELASTICSEARCH_INDEX_PREFIX": "rag",
        "DATABASE_URL": settings.database_url,
    }
    (root / ".env").write_text(
        "".join("AI_WORKSHOP_" + key + "=" + str(value) + "\n" for key, value in lines.items()),
        encoding="utf-8",
    )
    db: Any = EpochDatabase()  # type: ignore[no-untyped-call]
    op = db.operation
    op.alias = f"rag-{packets.PROCESSING}-{packets.PROFILE}-active"
    op.indexing_profile_id, op.document_processing_profile_id = (
        UUID(packets.PROFILE),
        UUID(packets.PROCESSING),
    )
    op.targets = [packets.NAME]
    db.rows[RagIndexBuildRecord, UUID(packets.BUILD)] = RagIndexBuildRecord(
        id=UUID(packets.BUILD),
        indexing_profile_id=UUID(packets.PROFILE),
        document_processing_profile_id=UUID(packets.PROCESSING),
        index_name=packets.NAME,
    )
    # Actual service reads these profiles through its SQL transport.
    for value, kind in ((packets.PROFILE, "indexing"), (packets.PROCESSING, "document_processing")):
        db.rows[ProfileRecord, UUID(value)] = ProfileRecord(id=UUID(value), kind=kind)
    recovery = AliasRecoveryService(db, settings)
    snapshot = await recovery.preview(db.operation_id, db.actor)
    claim = await recovery.freeze(db.operation_id, db.actor, uuid4(), snapshot.sha256)
    observation = await original.observe_deployment(snapshot)
    row = deepcopy(packets.metadata()[packets.NAME])
    row["aliases"] = [snapshot.alias]
    row.pop("defaults")
    row["mappings"] = {"_doc": row["mappings"]}
    row.update(state="open", system=False)
    state = {"cluster_uuid": snapshot.cluster_uuid, "metadata": {"indices": {packets.NAME: row}}}
    listing = {
        "cluster_uuid": snapshot.cluster_uuid,
        "metadata": {
            "indices": {
                packets.NAME: {
                    "state": "open",
                    "settings": {"index.uuid": row["settings"]["index.uuid"]},
                }
            }
        },
    }
    transport = SimpleNamespace(
        state=state, listing=listing, http_calls=0, sql_calls=0, executor=executor, direct=direct
    )
    clients = httpx.AsyncClient

    async def request(req: httpx.Request) -> httpx.Response:
        transport.http_calls += 1
        assert req.method == "GET" and req.url.host == "127.0.0.1"
        assert req.url.port == 9200 and "authorization" not in req.headers
        body = transport.listing if req.url.path.endswith("/metadata") else transport.state
        return httpx.Response(200, json=body)

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return clients(transport=httpx.MockTransport(request), **kwargs)

    class Connection:
        async def execute(self, statement: Any) -> Any:
            transport.sql_calls += 1
            assert str(statement).startswith("SELECT ")
            ids = next(iter(statement.compile().params.values()))
            rows = [
                (key, db.rows[ProfileRecord, key].kind)
                for key in ids
                if (ProfileRecord, key) in db.rows
            ]
            return SimpleNamespace(all=lambda: rows)

    class Engine:
        @asynccontextmanager
        async def connect(self) -> Any:
            yield Connection()

        async def dispose(self) -> None:
            pass

    namespace_module = importlib.import_module(
        "ai_workshop.labs.rag.indexing.access_epoch_namespace_source"
    )
    monkeypatch.setattr(namespace_module.httpx, "AsyncClient", client)
    monkeypatch.setattr(namespace_module, "create_engine", lambda config: Engine())
    namespace_source = OriginalNamespaceSource(settings, original, observation)
    namespace = await namespace_source.observe(snapshot)

    class SecurityWire:
        async def read(self, path: str) -> list[object]:
            assert path.startswith("/_cat/indices/.security")
            return []

    security_source = OriginalSecurityAbsenceReader(original, SecurityWire())
    absence = await security_source.observe(snapshot)
    repo = SqlAlchemyAccessEpochRepository(db, IndexBinding("rag", "cluster"), "rag")
    context = NativeControlContext(
        settings,
        repo,
        claim,
        original,
        observation,
        namespace_source,
        namespace,
        security_source,
        absence,
    )
    # Synthetic software bytes are captured by the actual descriptor producer.
    kernel = PacketKernel()
    descriptor = importlib.import_module(
        "ai_workshop.labs.rag.indexing.access_epoch_security_descriptor_source"
    )
    binary_packets = [f"synthetic complete descriptor {index}\n".encode() for index in range(5)]
    kernel.outputs.extend(binary_packets)
    monkeypatch.setattr(descriptor, "_CWD", root)
    monkeypatch.setattr(
        descriptor, "_PINS", tuple(sha256(raw).hexdigest() for raw in binary_packets)
    )
    native_module = importlib.import_module(
        "ai_workshop.infrastructure.local.control_process_windows"
    )
    monkeypatch.setattr(native_module, "NativeWindowsProcess", lambda: kernel)
    routes = importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_route_commands")
    original_process = importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_process")
    monkeypatch.setattr(original_process, "_binary_sha", lambda: "c" * 64)
    monkeypatch.setattr(routes, "_binary_sha", lambda: "a" * 64)
    monkeypatch.setattr(routes, "_python_sha", lambda: "b" * 64)

    def jdk_run(argv: Any, **options: Any) -> Any:
        return SimpleNamespace(
            returncode=0,
            stderr=b"",
            stdout=json.dumps(
                {
                    "schema_version": 1,
                    "java_feature": 25,
                    "source_level": 21,
                    "compiler_present": True,
                }
            ).encode(),
        )

    monkeypatch.setattr(routes.subprocess, "run", jdk_run)
    await context.prepare_sources()
    epoch = await repo.acquire(claim, observation.identity)
    state_now = await repo.readback(claim)
    lock = WindowsControlLock(epoch.original.daemon_sha256, "ai-workshop", native=Kernel())
    assert state_now.executor_generation is not None
    owner = lock.acquire(UUID(epoch.binding.execution_id), state_now.executor_generation)
    memory = PrivateMemory()  # type: ignore[no-untyped-call]
    journal = ProtectedControlJournal(root, memory, memory, lock, owner, lock.scope_sha256)
    # Trusted unit assembler slots are permitted; all subsequent guards execute.
    context._epoch, context._lock, context._owner, context._journal = epoch, lock, owner, journal
    assert context._preflight_sources is not None
    context._native = context._preflight_sources.native
    context._store = WindowsCredentialStore(root, memory, memory)
    context._keys = SqlAlchemyEpochKeyRepository(repo)
    context._runtime_signature = context._runtime_values()
    context.assert_owned()
    await context.revalidate()
    return NativeFixture(root, context, db, kernel, memory, transport)
