"""Full synthetic committed graph; only DBAPI, files, WinDLL and TLS sockets fake.

The original source/assembly/store/crypto, SQLAlchemy, native process lifecycle,
HTTP parser and pure packet validators remain production classes. No capability
issuer or guard is replaced. All protected writes map into pytest's directory.
"""

import ctypes
import io
import json
import os
import ssl
import threading
from dataclasses import asdict, replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

from ai_workshop.infrastructure.local.credential_store_windows import identity_json
from ai_workshop.infrastructure.search.access_credentials import SecuredStoreIdentity
from ai_workshop.labs.rag.indexing.access_epoch_auth_packets import finite_privilege_matrix
from ai_workshop.labs.rag.indexing.access_epoch_committed_snapshot import _actions
from ai_workshop.labs.rag.indexing.access_epoch_evidence_packets import _stored_control_manifest
from ai_workshop.labs.rag.indexing.access_epoch_models import (
    AccessEpochEventRecord,
    AccessEpochExecutionRecord,
    AccessEpochFloorRecord,
    AccessEpochRecord,
)
from ai_workshop.labs.rag.indexing.access_epoch_repository import AccessEpochReadback
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    canonical_json,
    decode_termination_proof,
)
from ai_workshop.labs.rag.indexing.alias_models import AliasRecoveryReceiptRecord
from ai_workshop.labs.rag.indexing.alias_recovery_types import digest, utc_text
from tests.unit.infrastructure.local.test_control_process_windows import Win32
from tests.unit.labs.rag.indexing import test_access_epoch_docker_packets as docker_fixture
from tests.unit.labs.rag.indexing import test_access_epoch_server_packets as server_fixture
from tests.unit.labs.rag.indexing.native_committed_https_fixture_support import prepare_https
from tests.unit.labs.rag.indexing.test_access_epoch_https_read import Peer
from tests.unit.labs.rag.indexing.test_access_epoch_secured_read_assembly import Function


def raw(value):
    return canonical_json(value).encode()


def reseed(graph):
    store, _, _, c, _ = graph
    for rows in store.tables.values():
        rows.clear()
    for row in c.db.rows.values():
        store.seed(row)


def refresh_evidence(graph, manifests, facts):
    """Keep ordinary synthetic rows, persisted evidence and protected anchor coherent."""
    _, _, deps, c, material = graph
    for name, payload in manifests.items():
        facts[name + "_sha256"] = sha256(payload.encode()).hexdigest()
    c.evidence = replace(
        c.evidence, proof_facts_json=canonical_json(facts), manifests=tuple(manifests.items())
    )
    c.proof = decode_termination_proof(facts)
    floor = c.repository.floor_from_verified(c.evidence)
    for (kind, _), row in c.db.rows.items():
        if kind is AccessEpochRecord:
            row.original = {
                key: utc_text(value) if isinstance(value, datetime) else value
                for key, value in asdict(c.epoch.original).items()
            }
            row.verified, row.manifests = facts, manifests
        elif kind is AccessEpochFloorRecord:
            row.identity = asdict(floor)
        elif kind is AliasRecoveryReceiptRecord:
            row.proof, row.proof_sha256 = facts, digest(facts)
    reseed(graph)
    anchor = SecuredStoreIdentity(
        floor.store_id,
        floor.cluster_uuid,
        floor.ordinal,
        UUID(floor.access_epoch_id),
        floor.container_id,
        floor.stable_node_id,
        floor.route_sha256,
        floor.auth_sha256,
        floor.config_sha256,
        floor.ca_sha256,
    )
    material.seed(
        str(material.private / "floor.dpapi"), deps.private.protect(identity_json(anchor))
    )


def prepare_full_graph(graph):
    """Adapt independent Docker/server recipes to the exact committed epoch."""
    _, _, _, c, _ = graph
    docker = docker_fixture.case()
    manifests = dict(c.evidence.manifests)
    manifests.update(
        daemon_identity=canonical_json(
            {
                "id": docker_fixture.deployment.DAEMON,
                "os": "linux",
                "endpoint_sha256": docker_fixture.deployment.CONTEXT_ENDPOINT_DIGEST,
            }
        ),
        protected_image=canonical_json(docker.original_image),
        original_volume_identity=canonical_json(docker.original_volume),
    )
    c.epoch = replace(
        c.epoch,
        original=replace(
            c.epoch.original,
            daemon_sha256=sha256(manifests["daemon_identity"].encode()).hexdigest(),
            image_sha256=sha256(manifests["protected_image"].encode()).hexdigest(),
            volume_sha256=sha256(manifests["original_volume_identity"].encode()).hexdigest(),
        ),
    )
    refresh_evidence(graph, manifests, json.loads(c.evidence.proof_facts_json))
    tls, permissions = prepare_https(graph)
    facts = json.loads(c.evidence.proof_facts_json)
    # ES returns epoch milliseconds. The committed expected JVM must represent
    # exactly that instant rather than a fixture-generated submillisecond value.
    jvm = c.proof.new_jvm_start_at
    facts["new_jvm_start_at"] = utc_text(jvm.replace(microsecond=jvm.microsecond // 1000 * 1000))
    events = sorted(
        (row for (kind, _), row in c.db.rows.items() if kind is AccessEpochEventRecord),
        key=lambda row: row.sequence,
    )
    execution = next(
        row for (kind, _), row in c.db.rows.items() if kind is AccessEpochExecutionRecord
    )
    start = next(row for row in events if row.kind == "start_secured" and row.outcome == "settled")
    old_epoch = docker.manifest["epoch_id"]
    old_container = docker.manifest["container_id"]
    # Only public fixture identities/addresses are substituted, never a parser
    # result or an issuance object. All resulting bytes face production checks.
    text = canonical_json(docker.bodies)
    for before, after in (
        (old_epoch, c.epoch.binding.access_epoch_id),
        (old_container, facts["new_container_id"]),
        ("172.28.", "172.18."),
    ):
        text = text.replace(before, after)
    docker.bodies = json.loads(text)
    container = docker.bodies["container"][0]
    container["Created"] = facts["new_server_started_at"]
    container["State"]["StartedAt"] = facts["new_server_started_at"]
    docker.hashes = {name: json.loads(tls.manifest_json)[name] for name in docker.hashes}
    docker.manifest.update(
        epoch_id=c.epoch.binding.access_epoch_id,
        execution_id=c.epoch.binding.execution_id,
        action_id=str(start.action_id),
        original_ipv4="172.18.0.2",
        network_subnet="172.18.0.0/16",
        network_gateway="172.18.0.1",
        container_id=facts["new_container_id"],
        docker_started_at=facts["new_server_started_at"],
        created_at=facts["new_server_started_at"],
        observed_at=facts["access_verified_at"],
        tls_public_hashes=docker.hashes,
    )
    start.manifest_json = canonical_json(docker.manifest)
    phase = next(row.phase for (kind, _), row in c.db.rows.items() if kind is AccessEpochRecord)
    state = AccessEpochReadback(
        c.epoch,
        phase,
        _actions(events, execution),
        "open",
        "frozen",
        None,
        c.proof.old_server_stopped_at,
        execution.executor_generation,
    )
    manifests = dict(c.evidence.manifests) | {
        "new_deployment": start.manifest_json,
        "control_settlement": _stored_control_manifest(c.epoch, state),
    }
    refresh_evidence(graph, manifests, facts)
    server = server_fixture.packets()
    server_text = canonical_json(server)
    for before, after in (
        ("synthetic-cluster-id", facts["cluster_uuid"]),
        ("synthetic-cluster", docker.manifest["cluster_name"]),
        (server_fixture.NODE, facts["stable_node_id"]),
        ("synthetic-ephemeral", facts["new_ephemeral_id"]),
        (server_fixture.IP, docker.manifest["original_ipv4"]),
    ):
        server_text = server_text.replace(before, after)
    server = json.loads(server_text)
    server["nodes"]["nodes"][facts["stable_node_id"]]["jvm"]["start_time_in_millis"] = int(
        c.proof.new_jvm_start_at.timestamp() * 1000
    )
    expected = server_fixture.expected_values() | {
        "cluster_uuid": facts["cluster_uuid"],
        "cluster_name": docker.manifest["cluster_name"],
        "stable_node_id": facts["stable_node_id"],
        "ephemeral_id": facts["new_ephemeral_id"],
        "jvm_start_at": c.proof.new_jvm_start_at,
        "container_started_at": c.proof.new_server_started_at,
        "original_ipv4": docker.manifest["original_ipv4"],
    }
    return SimpleNamespace(
        graph=graph,
        docker=docker,
        tls=tls,
        permissions=permissions,
        server=server,
        expected=expected,
    )


class ReadKernel(Win32):
    """Real ctypes structures/handle accounting; no native executable is spawned."""

    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.after_child = None
        self.exit_status = 0
        super().__init__()

    def call(self, name, *args):
        if name == "CloseHandle" and isinstance(args[0], ctypes.c_void_p):
            args = (args[0].value, *args[1:])
        if name == "CreateProcessW":
            assert self.bodies, "unexpected_docker_child"
            self.output = self.bodies.pop(0)
        if name == "GetExitCodeProcess":
            args[1]._obj.value = self.exit_status
            return 1
        if name == "GetCurrentThreadId":
            return threading.get_ident()
        if name == "CloseHandle" and args[0] not in self.open:
            # NativeWindowsPrivateState's independent token handle.
            assert args[0] == 41
            return 1
        result = super().call(name, *args)
        if name == "CreateProcessW" and self.after_child is not None:
            self.after_child(len(self.created))
        return result


def install_capture_transport(monkeypatch, material, kernel):
    """Allow only read-check captures in temporary storage; retain all other bans."""
    captures = material.private / "read-checks"
    old_open, old_mkdir, old_unlink, old_dll = io.open, Path.mkdir, Path.unlink, ctypes.WinDLL

    def capture(path):
        return isinstance(path, str | Path) and Path(path).is_relative_to(captures)

    def opened(path, mode="r", *args, **kwargs):
        return old_open(material.mapped(path) if capture(path) else path, mode, *args, **kwargs)

    def mkdir(path, *args, **kwargs):
        mapped = material.mapped(path) if capture(path) or path == material.private.parent else path
        return old_mkdir(mapped, *args, **kwargs)

    def unlink(path, *args, **kwargs):
        return old_unlink(material.mapped(path) if capture(path) else path, *args, **kwargs)

    def move(source, destination, flags):
        assert capture(source) and capture(destination) and flags == 8
        a, b = material.mapped(source), material.mapped(destination)
        assert a is not None and b is not None
        if b.exists():
            ctypes.set_last_error(183)
            return False
        os.rename(a, b)
        return True

    def descriptor(_text, version, result, _size):
        assert version == 1
        result._obj.value = 999
        return True

    def dacl(_descriptor, present, result, defaulted):
        present._obj.value, result._obj.value, defaulted._obj.value = (
            1,
            ctypes.addressof(material.acl),
            0,
        )
        return True

    def dll(name, **kwargs):
        result = old_dll(name, **kwargs)
        if name == "kernel32":
            for method, value in vars(kernel).items():
                if callable(value) and method not in {
                    "LocalFree",
                    "ConvertStringSecurityDescriptorToSecurityDescriptorW",
                }:
                    setattr(result, method, Function(value))
            result.MoveFileExW = Function(move)
        elif name == "advapi32":
            result.ConvertStringSecurityDescriptorToSecurityDescriptorW = Function(descriptor)
            result.GetSecurityDescriptorDacl = Function(dacl)
            result.SetNamedSecurityInfoW = Function(lambda *_: 0)
        return result

    monkeypatch.setattr(io, "open", opened)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(ctypes, "WinDLL", dll)


def install_binary_transport(monkeypatch, material):
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import DOCKER_EXE

    binary = Path(DOCKER_EXE)
    target = material.temporary / "synthetic-docker.exe"
    target.write_bytes(b"synthetic-docker-binary-never-executed")
    paths = {binary: target}
    for index, ancestor in enumerate(binary.parents):
        mapped = material.temporary / f"binary-parent-{index}"
        mapped.mkdir()
        paths[ancestor] = mapped
    previous_stat, previous_read = Path.stat, Path.read_bytes

    def stat(path, *args, **kwargs):
        return previous_stat(paths.get(path, path), *args, **kwargs)

    def read(path):
        return previous_read(paths.get(path, path))

    monkeypatch.setattr(Path, "stat", stat)
    monkeypatch.setattr(Path, "read_bytes", read)
    return target


class ReadPeer(Peer):
    def __init__(self, body, leaf):
        super().__init__()
        self.hook = None
        self.cleanup_error = False
        self.leaf = leaf
        self.respond(body)

    def event(self, name):
        super().event(name)
        if getattr(self, "hook", None) is not None:
            self.hook(name)

    def close(self):
        super().close()
        if self.cleanup_error:
            raise OSError("synthetic_socket_cleanup_unverified")


def install_https_transport(monkeypatch, recipe, catalog, *, rounds=1):
    from ai_workshop.labs.rag.indexing import access_epoch_https_read as https

    bodies = [raw(recipe.server[name]) for name in ("info", "state", "nodes")]
    for key in catalog.keys:
        bodies.append(
            raw(
                {
                    "username": "elastic",
                    "roles": [],
                    "full_name": None,
                    "email": None,
                    "metadata": {},
                    "enabled": True,
                    "authentication_type": "api_key",
                    "authentication_realm": {"name": "_es_api_key", "type": "_es_api_key"},
                    "lookup_realm": {"name": "_es_api_key", "type": "_es_api_key"},
                    "api_key": {
                        "id": key.key_id,
                        "name": key.key_name,
                        "managed_by": "elasticsearch",
                    },
                }
            )
        )
        bodies.append(
            raw(finite_privilege_matrix(catalog.epoch_id, catalog.permissions, key.role)[1])
        )
    leaf = x509.load_pem_x509_certificate(recipe.tls.bundle.http.leaf_certificate_pem).public_bytes(
        Encoding.DER
    )
    peers = [ReadPeer(body, leaf) for _ in range(rounds) for body in bodies]
    used = []

    def socket(family, kind):
        assert family == https.AF_INET and kind == https.SOCK_STREAM
        assert len(used) < len(peers), "unexpected_https_read"
        peer = peers[len(used)]
        used.append(peer)
        peer.event("socket")
        return peer

    class Context:
        def __init__(self, protocol):
            assert protocol == ssl.PROTOCOL_TLS_CLIENT
            self.check_hostname = True
            self.verify_mode = ssl.CERT_REQUIRED
            self.minimum_version = ssl.TLSVersion.TLSv1_2

        def load_verify_locations(self, *, cadata):
            assert cadata == catalog.http_ca_pem.decode("ascii")

        def set_alpn_protocols(self, protocols):
            assert protocols == ["http/1.1"]

        def wrap_socket(self, peer, *, server_hostname, do_handshake_on_connect):
            assert peer is used[-1] and server_hostname == "127.0.0.1"
            assert do_handshake_on_connect is False
            peer.event("wrap")
            return peer

    monkeypatch.setattr(https, "socket", socket)
    monkeypatch.setattr(https, "SSLContext", Context)
    return SimpleNamespace(peers=peers, used=used)


async def catalog_from_new_assembly(recipe):
    from ai_workshop.labs.rag.indexing.access_epoch_committed_https import (
        _read_committed_https_catalog,
    )
    from ai_workshop.labs.rag.indexing.access_epoch_committed_tls import NativeCommittedTlsReader
    from ai_workshop.labs.rag.indexing.access_epoch_secured_read import NativeSecuredReadSource
    from ai_workshop.labs.rag.indexing.access_epoch_secured_read_assembly import (
        NativeSecuredReadAssembly,
    )

    async with NativeSecuredReadAssembly.open_original() as assembly:
        deps = assembly.bind_committed()
        source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
        binding = await source.bind_verified(recipe.graph[3].claim)
        reader = await NativeCommittedTlsReader._open_bound_source(source, binding)
        try:
            return (await _read_committed_https_catalog(source, binding, reader)).catalog
        finally:
            reader.close()


async def prepare_transport(graph, monkeypatch, *, rounds=1):
    from ai_workshop.infrastructure.local.windows_private_state import NativeWindowsPrivateState
    from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT

    recipe = prepare_full_graph(graph)
    kernel = ReadKernel(
        [raw(recipe.docker.bodies[name]) for _ in range(rounds) for name in docker_fixture.BODIES]
    )
    install_capture_transport(monkeypatch, graph[4], kernel)
    binary = install_binary_transport(monkeypatch, graph[4])
    probe = NativeWindowsPrivateState(PROJECT_ROOT)
    probe.assert_origin()
    catalog = await catalog_from_new_assembly(recipe)
    https = install_https_transport(monkeypatch, recipe, catalog, rounds=rounds)
    return SimpleNamespace(
        recipe=recipe, graph=graph, kernel=kernel, catalog=catalog, https=https, binary=binary
    )


def assert_clean(fixture):
    store, _, _, _, material = fixture.graph
    assert not fixture.kernel.open and not material.retained
    assert store.dml_count == store.commit_count == 0
    assert all("close" in peer.events for peer in fixture.https.used)
    assert all(connection.closed for connection in store.connections)
