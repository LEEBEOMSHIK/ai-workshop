"""Actual preepoch sources over fixed synthetic DBAPI/HTTP/OS transports.

No production constants, guards, issuers, runtime slots or Settings are replaced.
The public javap capture is data only, never historical operational authority.
"""

import ctypes
import gzip
import hashlib
import io
import json
import subprocess
from collections.abc import AsyncIterator, Awaitable, Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from psycopg.types import TypeInfo

from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord
from ai_workshop.labs.rag.indexing import access_epoch_route_commands as routes
from ai_workshop.labs.rag.indexing import access_epoch_security_descriptor_source as descriptors
from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from ai_workshop.labs.rag.indexing.access_epoch_namespace_source import OriginalNamespaceSource
from ai_workshop.labs.rag.indexing.access_epoch_native import OriginalAccessEpochPreflight
from ai_workshop.labs.rag.indexing.access_epoch_original_security import (
    OriginalSecurityAbsenceReader,
)
from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
    NativeSecuredReadAssembly,
)
from ai_workshop.labs.rag.indexing.alias_models import AliasOperationRecord
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
    CONTAINER,
    DOCKER_EXE,
    NETWORK,
    ORIGINAL_IMAGE_ID,
    FixedCommand,
    command_argv,
)
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.identity.models import UserRecord
from tests.unit.labs.rag.indexing import native_sql_row_transport_support as sql
from tests.unit.labs.rag.indexing import test_access_epoch_index_inventory as packets
from tests.unit.labs.rag.indexing.native_fresh_secured_read_fixture_support import (
    ReadKernel,
    install_binary_transport,
    install_capture_transport,
)
from tests.unit.labs.rag.indexing.native_private_material_transport_support import MaterialTransport
from tests.unit.labs.rag.indexing.test_access_epoch_secured_read_assembly import missing_hstore
from tests.unit.labs.rag.indexing.test_alias_recovery_local_native import FixedExecutor, Reader

pytest_plugins = ["tests.unit.labs.rag.indexing.test_access_epoch_secured_read_assembly"]


class PreepochKernel(ReadKernel):
    """Keep stdout/stderr separate when public packets exceed one 64KiB read."""

    def __init__(self, bodies: tuple[bytes, ...]) -> None:
        self.pipe_reads: dict[int, int] = {}
        self.streams: dict[int, bytes] = {}
        super().__init__(bodies)  # type: ignore[no-untyped-call]

    def call(self, name: str, *args: Any) -> Any:
        if name == "PeekNamedPipe":
            args[4]._obj.value = len(self.streams[args[0]])
            return 1
        if name == "ReadFile":
            data = self.streams[args[0]][: args[2]]
            self.streams[args[0]] = self.streams[args[0]][args[2] :]
            ctypes.memmove(args[1], data, len(data))
            args[3]._obj.value = len(data)
            return 1
        result = super().call(name, *args)  # type: ignore[no-untyped-call]
        if name == "CreatePipe":
            self.pipe_reads[args[1]._obj.value] = args[0]._obj.value
        if name == "CreateProcessW":
            startup = args[8]._obj.StartupInfo
            self.streams[self.pipe_reads[startup.hStdOutput]] = self.output
            self.streams[self.pipe_reads[startup.hStdError]] = b""
            self.output = b""
        return result


def public_descriptor_packets() -> tuple[bytes, ...]:
    path = (
        PROJECT_ROOT
        / "backend/tests/fixtures/elasticsearch"
        / "es-9.5.2-public-descriptor-packets.json.gz"
    )
    compressed = path.read_bytes()
    assert hashlib.sha256(compressed).hexdigest() == (
        "a5923aa842c8eab385cc858c14fa59b7adac7201ca0f39f668a7f24c8951f168"
    )
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        decoded = stream.read(4 * 1024 * 1024 + 1)
    assert len(decoded) <= 4 * 1024 * 1024
    value = json.loads(decoded)
    assert type(value) is dict and set(value) == {"schema_version", "packets"}
    assert type(value["schema_version"]) is int and value["schema_version"] == 1
    assert type(value["packets"]) is list and len(value["packets"]) == 5
    bodies = []
    for row, (_, name), digest in zip(
        value["packets"], descriptors._CLASSES, descriptors._PINS, strict=True
    ):
        assert type(row) is dict and set(row) == {"class", "sha256", "body"}
        assert row["class"] == name and row["sha256"] == digest
        assert type(row["body"]) is str
        body = row["body"].encode("utf-8")
        assert 0 < len(body) <= 1024 * 1024
        assert hashlib.sha256(body).hexdigest() == digest
        bodies.append(body)
    assert sum(map(len, bodies)) <= 4 * 1024 * 1024
    return tuple(bodies)


def original_packets(cluster: str, prefix: str) -> tuple[dict[Any, Any], dict[str, Any], str, str]:
    # Reuse only ordinary synthetic wire data, not the old fixture's fake ports.
    wire: Any = FixedExecutor()  # type: ignore[no-untyped-call]
    direct: Any = Reader()  # type: ignore[no-untyped-call]
    container = wire.container
    container.update(Name="/ai-workshop-elasticsearch-1", Image=ORIGINAL_IMAGE_ID)
    container["Config"]["Env"].append("xpack.security.enabled=false")
    container["HostConfig"]["NetworkMode"] = "ai-workshop_default"
    container["Mounts"][0]["Name"] = "ai-workshop_elasticsearch-data"
    container["NetworkSettings"]["Networks"] = {
        "ai-workshop_default": {
            "NetworkID": NETWORK,
            "IPAddress": "172.24.0.3",
            "IPPrefixLen": 16,
            "Gateway": "172.24.0.1",
            "GlobalIPv6Address": "",
            "GlobalIPv6PrefixLen": 0,
            "IPv6Gateway": "",
        }
    }
    wire.responses[FixedCommand.IMAGE_METADATA] = {
        "image_id": ORIGINAL_IMAGE_ID,
        "repo_digests": ["docker.elastic.co/elasticsearch/elasticsearch@sha256:" + "d" * 64],
        "os": "linux",
        "architecture": "arm64",
    }
    wire.responses[FixedCommand.ORIGINAL_VOLUME_METADATA] = {
        "name": "ai-workshop_elasticsearch-data",
        "driver": "local",
        "scope": "local",
        "created_at": "2026-09-01T00:00:00Z",
        "options": None,
        "mountpoint": "/var/lib/docker/volumes/ai-workshop_elasticsearch-data/_data",
    }
    wire.responses[FixedCommand.SELECTED_NETWORK_RAW] = [
        {
            "Id": NETWORK,
            "Name": "ai-workshop_default",
            "Driver": "bridge",
            "Scope": "local",
            "Internal": False,
            "EnableIPv6": False,
            "IPAM": {
                "Driver": "default",
                "Config": [{"Subnet": "172.24.0.0/16", "Gateway": "172.24.0.1"}],
            },
            "Containers": {
                CONTAINER: {
                    "Name": "ai-workshop-elasticsearch-1",
                    "IPv4Address": "172.24.0.3/16",
                    "IPv6Address": "",
                }
            },
        }
    ]
    for body in direct.responses.values():
        if "cluster_uuid" in body:
            body["cluster_uuid"] = cluster
    direct.responses["/"]["cluster_name"] = "ai-workshop"
    direct.responses["/_cat/indices/.security*"] = []
    name = f"{prefix}-{packets.PROCESSING}-{packets.PROFILE}-{packets.BUILD}"
    alias = f"{prefix}-{packets.PROCESSING}-{packets.PROFILE}-active"
    row = deepcopy(packets.metadata()[packets.NAME])
    row["aliases"] = [alias]
    row.pop("defaults")
    row["mappings"] = {"_doc": row["mappings"]}
    row.update(state="open", system=False)
    direct.responses["/_cluster/state/metadata,routing_table"] = {
        "cluster_uuid": cluster,
        "metadata": {"indices": {name: row}},
    }
    direct.responses["/_cluster/state/metadata"] = {
        "cluster_uuid": cluster,
        "metadata": {
            "indices": {
                name: {"state": "open", "settings": {"index.uuid": row["settings"]["index.uuid"]}}
            }
        },
    }
    supported = (
        FixedCommand.CONTEXT,
        FixedCommand.DAEMON,
        FixedCommand.CONTAINER,
        FixedCommand.IMAGE_METADATA,
        FixedCommand.ORIGINAL_VOLUME_METADATA,
        FixedCommand.SELECTED_NETWORK_RAW,
    )
    return {key: wire.responses[key] for key in supported}, direct.responses, name, alias


def install_external_reads(monkeypatch: pytest.MonkeyPatch, graph: Any) -> None:
    commands = {tuple(command_argv(key)): (key, body) for key, body in graph.commands.items()}

    def run(argv: Any, **options: Any) -> Any:
        assert options["shell"] is False and options["capture_output"] is True
        assert options["creationflags"] == subprocess.CREATE_NO_WINDOW
        if tuple(argv) in commands:
            assert options["check"] is False and options["timeout"] == 45
            key, body = commands[tuple(argv)]
            graph.command_calls.append(key)
            return SimpleNamespace(returncode=0, stdout=json.dumps(body).encode(), stderr=b"")
        assert tuple(argv) == (
            DOCKER_EXE,
            "--host",
            routes._PIPE,
            "exec",
            "--interactive",
            CONTAINER,
            *routes._JAVA_PREFIX,
            *routes._JAVA_FLAGS,
            "--source",
            "21",
            "/dev/stdin",
        )
        assert options["input"] == routes._SUPPORT_SOURCE and options["timeout"] == 30
        graph.jdk_calls += 1
        return SimpleNamespace(
            returncode=0,
            stdout=b'{"schema_version":1,"java_feature":25,"source_level":21,"compiler_present":true}',
            stderr=b"",
        )

    async def http(_transport: Any, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.host == "127.0.0.1"
        assert request.url.port == 9200 and "authorization" not in request.headers
        graph.http_calls.append(request.url.path)
        return httpx.Response(200, json=graph.http[request.url.path])

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", http)


@pytest.fixture
async def preepoch_graph(
    factory: Callable[[], Awaitable[NativeSecuredReadAssembly]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[Any]:
    material = MaterialTransport(monkeypatch, tmp_path)
    kernel = PreepochKernel(public_descriptor_packets())
    install_capture_transport(monkeypatch, material, kernel)  # type: ignore[no-untyped-call]
    install_binary_transport(monkeypatch, material)  # type: ignore[no-untyped-call]
    store = sql.RelationalRows()
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", store.connect)
    monkeypatch.setattr(TypeInfo, "fetch", missing_hstore)
    assembly = await factory()
    settings, repository = assembly._settings, assembly.control_repository
    assert type(settings.rag_index_cluster_uuid) is str
    commands, http, name, alias = original_packets(
        settings.rag_index_cluster_uuid, settings.elasticsearch_index_prefix
    )
    graph = SimpleNamespace(
        assembly=assembly,
        store=store,
        material=material,
        kernel=kernel,
        commands=commands,
        http=http,
        command_calls=[],
        http_calls=[],
        jdk_calls=0,
    )
    graph.transport = SimpleNamespace(
        command_calls=graph.command_calls, http_calls=graph.http_calls
    )
    install_external_reads(monkeypatch, graph)
    actor, operation = uuid4(), uuid4()
    store.seed(UserRecord(id=actor, role="owner", is_active=True))
    for value, kind in ((packets.PROFILE, "indexing"), (packets.PROCESSING, "document_processing")):
        store.seed(ProfileRecord(id=UUID(value), kind=kind))
    store.seed(
        RagIndexBuildRecord(
            id=UUID(packets.BUILD),
            indexing_profile_id=UUID(packets.PROFILE),
            document_processing_profile_id=UUID(packets.PROCESSING),
            index_name=name,
        )
    )
    store.seed(
        AliasOperationRecord(
            id=operation,
            store_id=settings.rag_index_store_id,
            cluster_uuid=settings.rag_index_cluster_uuid,
            alias=alias,
            indexing_profile_id=UUID(packets.PROFILE),
            document_processing_profile_id=UUID(packets.PROCESSING),
            targets=[name],
            state="open",
            phase="legacy_unknown",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    try:
        snapshot = await repository.recovery.preview(operation, actor)
        claim = await repository.recovery.freeze(operation, actor, uuid4(), snapshot.sha256)
        original = OriginalAccessEpochPreflight(settings)
        observation = await original.observe_deployment(snapshot)
        namespace_source = OriginalNamespaceSource(settings, original, observation)
        namespace = await namespace_source.observe(snapshot)
        security = OriginalSecurityAbsenceReader(original, original.reader)
        absence = await security.observe(snapshot)
        graph.context = NativeControlContext(
            settings,
            repository,
            claim,
            original,
            observation,
            namespace_source,
            namespace,
            security,
            absence,
        )
        graph.namespace_source = namespace_source
        graph.namespace = namespace
        graph.after_construction = deepcopy(store.tables)
        graph.before_dml = store.dml_count
        graph.before_commit = store.commit_count
        yield graph
    finally:
        await assembly.close()
        assert all(connection.closed for connection in store.connections)
        assert kernel.open == set() and not material.retained


@pytest.fixture
async def preepoch_context(preepoch_graph: Any) -> Any:
    """Prepared actual sources; still no epoch, held owner or operational support."""
    await preepoch_graph.context.prepare_sources()
    preepoch_graph.context.assert_preflight_sources()
    return preepoch_graph
