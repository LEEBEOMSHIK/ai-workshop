"""Synthetic TLS and daemon responses exercise the production startup boundary."""

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.access_credentials import (
    AccessCredentialError,
    SecuredStoreIdentity,
)
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT, DeploymentCommands
from ai_workshop.labs.rag.indexing.access_epoch_runtime import OriginalRuntimeAdmission
from ai_workshop.labs.rag.indexing.access_epoch_types import CutoverActionKind, canonical_json
from tests.unit.labs.rag.indexing import test_access_epoch_deployment as df
from tests.unit.labs.rag.indexing import test_access_epoch_tls as tf

process_case = tf.process_case
tls_case = tf.tls_case


@pytest.fixture
async def runtime_case(tls_case, tmp_path, monkeypatch):
    c = tls_case
    action, ticket = await tf.reserve(c)
    assets = await c.materializer.execute(action, ticket)
    _, original, _, index = df.setup()
    epoch = replace(
        original, binding=replace(original.binding, access_epoch_id=str(assets.epoch_id))
    )
    directory = (
        PROJECT_ROOT / ".local-data/access-epoch/private/tls" / str(assets.epoch_id) / "bind"
    )
    fixed = replace(
        assets,
        bind_directory=str(directory),
        leaf_locations=tuple(
            str(directory / p / name)
            for p in ("http", "transport")
            for name in ("node.key", "node.crt", "ca.crt")
        ),
    )
    builder = DeploymentCommands(
        epoch, fixed, df.MANIFEST, "original-cluster", "172.28.0.0/16", "172.28.0.1", (index,)
    )
    captured = []

    def capture(value):
        value = replace(value, tls_public_hashes=builder.tls_hashes)
        captured.append(value)
        return value

    boot = df.observation(builder, df.action(builder), transform=capture)
    final_action = df.action(builder, CutoverActionKind.START_SECURED)
    docker = df.container_json(builder, final_action, "f" * 64)
    final = df.observation(builder, final_action, docker, boot, transform=capture)
    manifest = json.loads(assets.manifest_json)
    files = {
        Path(new): c.storage.files[old]
        for old, new in zip(assets.leaf_locations, fixed.leaf_locations, strict=True)
    }
    ca_path = tmp_path / "public-ca.crt"
    files[ca_path] = files[directory / "http/ca.crt"]
    files[PROJECT_ROOT / "infrastructure/elasticsearch/elasticsearch-secured.yml"] = captured[
        -1
    ].secured_config
    floor = SecuredStoreIdentity(
        "rag",
        "cluster",
        1,
        assets.epoch_id,
        final.container_id,
        "stable",
        "a" * 64,
        "b" * 64,
        "c" * 64,
        hashlib.sha256(assets.manifest_json.encode()).hexdigest(),
    )
    result = SimpleNamespace(
        docker=docker,
        network=json.loads(captured[-1].network),
        daemon={"ID": df.DAEMON, "OSType": "linux"},
        files=files,
        ca_path=ca_path,
        manifest=manifest,
        calls=[],
        docker_calls=[],
        capability=SimpleNamespace(
            pid=os.getpid(), epoch_id=floor.epoch_id, ordinal=1, role="reader", key_id="reader-key"
        ),
        auth={"authentication_type": "api_key", "api_key": {"id": "reader-key"}},
        info={
            "cluster_uuid": "cluster",
            "cluster_name": "original-cluster",
            "version": {"number": "9.5.2"},
        },
        state={
            "cluster_uuid": "cluster",
            "master_node": "stable",
            "nodes": {"stable": {"ephemeral_id": "new"}},
        },
        jvm={
            "cluster_name": "original-cluster",
            "_nodes": {"total": 1, "successful": 1, "failed": 0},
            "nodes": {"stable": {"jvm": {"start_time_in_millis": int(df.NOW.timestamp() * 1000)}}},
        },
    )

    class Client:
        async def authenticate(self):
            result.calls.append("authenticate")
            return result.auth

        async def info(self, **kwargs):
            result.calls.append("jvm" if kwargs else "info")
            return result.jvm if kwargs else result.info

        async def state(self, **kwargs):
            result.calls.append("state")
            return result.state

        async def close(self):
            result.calls.append("close")

        @property
        def security(self):
            return self

        @property
        def cluster(self):
            return self

        @property
        def nodes(self):
            return self

    def inspect(argv, **kwargs):
        result.docker_calls.append(argv)
        assert argv[:3] == (df.DOCKER_EXE, "--host", "npipe:////./pipe/dockerDesktopLinuxEngine")
        assert kwargs["shell"] is False
        assert not any(k.startswith(("DOCKER", "COMPOSE")) for k in kwargs["env"])
        suffix = argv[3:]
        if suffix == ("info", "--format", "{{json .}}"):
            value = result.daemon
        elif suffix == ("container", "inspect", floor.container_id):
            value = [result.docker]
        elif suffix == ("network", "inspect", df.NETWORK):
            value = result.network
        else:
            raise AssertionError("unexpected native command")
        return SimpleNamespace(returncode=0, stdout=json.dumps(value).encode(), stderr=b"")

    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_runtime.current_verified_launch",
        lambda: result.capability,
    )
    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_runtime.create_elasticsearch",
        lambda settings: Client(),
    )
    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_runtime.subprocess.run", inspect
    )
    monkeypatch.setattr(Path, "read_bytes", lambda p: result.files[p])
    runtime = OriginalRuntimeAdmission(PROJECT_ROOT)
    runtime.floor = floor
    runtime.proof = {
        "schema_version": 2,
        "proof_kind": "local_single_node_access_epoch",
        "access_epoch_id": str(floor.epoch_id),
        "execution_id": str(final.execution_id),
        "new_container_id": floor.container_id,
        "cluster_uuid": floor.cluster_uuid,
        "stable_node_id": floor.stable_node_id,
        "new_ephemeral_id": "new",
        "new_jvm_start_at": df.NOW.isoformat(timespec="microseconds"),
        "tls_public_ca_sha256": floor.ca_sha256,
        "new_config_sha256": floor.config_sha256,
        "route_policy_sha256": floor.route_sha256,
        "auth_policy_sha256": floor.auth_sha256,
        "store_id": floor.store_id,
        "minimum_access_epoch": floor.ordinal,
        "new_deployment_sha256": hashlib.sha256(final.manifest_json.encode()).hexdigest(),
    }
    runtime.manifests = {
        "new_config": canonical_json({"profile": "project_http_tls_transport_mtls"}),
        "route_policy": canonical_json({"host": "127.0.0.1", "port": 9200}),
        "auth_policy": canonical_json({"anonymous": False}),
        "tls_public_ca": assets.manifest_json,
        "credential_deployment": canonical_json(
            {"epoch_id": str(floor.epoch_id), "ordinal": 1, "keys": {"reader": "reader-key"}}
        ),
        "new_deployment": final.manifest_json,
    }
    floor = replace(
        floor,
        config_sha256=hashlib.sha256(runtime.manifests["new_config"].encode()).hexdigest(),
        route_sha256=hashlib.sha256(runtime.manifests["route_policy"].encode()).hexdigest(),
        auth_sha256=hashlib.sha256(runtime.manifests["auth_policy"].encode()).hexdigest(),
    )
    runtime.floor = floor
    runtime.proof.update(
        new_config_sha256=floor.config_sha256,
        route_policy_sha256=floor.route_sha256,
        auth_policy_sha256=floor.auth_sha256,
    )
    runtime.proof["credential_deployment_sha256"] = hashlib.sha256(
        runtime.manifests["credential_deployment"].encode()
    ).hexdigest()
    result.runtime = runtime
    result.settings = Settings(
        _env_file=None,
        secret_key="synthetic-test-secret-value-00000000",
        elasticsearch_ca_certs=ca_path,
        elasticsearch_role="reader",
        elasticsearch_api_key=SecretStr("synthetic-reader-credential"),
        elasticsearch_url="https://127.0.0.1:9200",
        elasticsearch_access_epoch_id=floor.epoch_id,
        elasticsearch_access_epoch=1,
    )
    return result


@pytest.mark.parametrize("representation", ["pem", "wrong_der"])
async def test_actual_generated_tls_assets_use_pem_hash_for_runtime_admission(
    runtime_case, representation
):
    c = runtime_case
    assert c.manifest["http_ca_sha256"] == hashlib.sha256(c.files[c.ca_path]).hexdigest()
    assert c.manifest["http_ca_sha256"] != c.manifest["http_ca_der_sha256"]
    if representation == "wrong_der":
        c.manifest["http_ca_sha256"] = c.manifest["http_ca_der_sha256"]
        c.runtime.manifests["tls_public_ca"] = canonical_json(c.manifest)
        with pytest.raises(AccessCredentialError, match="access_epoch_mismatch"):
            await c.runtime.probe(c.settings)
    else:
        assert await c.runtime.probe(c.settings) == c.runtime.floor
        assert c.calls == ["authenticate", "info", "state", "jvm", "close"]
        assert len(c.docker_calls) == 3
        manifest = json.loads(c.runtime.manifests["new_deployment"])
        assert "host_config_json" not in manifest
        assert manifest["cluster_name"] == "original-cluster"


@pytest.mark.parametrize(
    "change",
    [
        "secret_env",
        "privileged",
        "host_network",
        "ip",
        "transport_port",
        "mount",
        "daemon",
        "started",
        "image",
        "ephemeral",
        "cluster_name",
        "jvm",
        "key",
        "capability",
        "partial",
        "proof",
        "config",
        "public_ca",
        "bool_node_count",
    ],
)
async def test_startup_requires_actual_authority_and_selected_topology(runtime_case, change):
    c = runtime_case
    if change == "secret_env":
        c.docker["Config"]["Env"].append("ELASTIC_PASSWORD=synthetic-forbidden")
    elif change == "privileged":
        c.docker["HostConfig"]["Privileged"] = True
    elif change == "host_network":
        c.docker["HostConfig"]["NetworkMode"] = "host"
    elif change == "ip":
        c.docker["NetworkSettings"]["Networks"]["ai-workshop_default"]["IPAddress"] = "172.28.0.4"
    elif change == "transport_port":
        c.docker["HostConfig"]["PortBindings"]["9300/tcp"] = [
            {"HostIp": "127.0.0.1", "HostPort": "9300"}
        ]
    elif change == "mount":
        c.docker["Mounts"][2]["RW"] = True
    elif change == "daemon":
        c.daemon["ID"] = "different"
    elif change == "started":
        c.docker["State"]["StartedAt"] = "2026-10-08T09:00:00+00:00"
    elif change == "image":
        c.docker["Image"] = "sha256:" + "1" * 64
    elif change == "ephemeral":
        c.state["nodes"]["stable"]["ephemeral_id"] = "different"
    elif change == "cluster_name":
        c.info["cluster_name"] = "different"
    elif change == "jvm":
        c.jvm["nodes"]["stable"]["jvm"]["start_time_in_millis"] += 1
    elif change == "key":
        c.auth["api_key"]["id"] = "wrong"
    elif change == "capability":
        c.capability = None
    elif change == "partial":
        c.runtime.manifests["new_deployment"] = canonical_json(
            {
                "docker_started_at": c.docker["State"]["StartedAt"],
                "image_id": c.docker["Image"],
                "host_config_json": canonical_json(c.docker["HostConfig"]),
            }
        )
        c.runtime.proof["new_deployment_sha256"] = hashlib.sha256(
            c.runtime.manifests["new_deployment"].encode()
        ).hexdigest()
    elif change == "proof":
        c.runtime.proof["new_deployment_sha256"] = "0" * 64
    elif change == "config":
        c.files[PROJECT_ROOT / "infrastructure/elasticsearch/elasticsearch-secured.yml"] = (
            b"xpack.security.enabled: false"
        )
    elif change == "public_ca":
        c.files[c.ca_path] = b"synthetic-invalid-public-ca"
    elif change == "bool_node_count":
        c.jvm["_nodes"]["successful"] = True
    with pytest.raises(AccessCredentialError, match="access_epoch_mismatch"):
        await c.runtime.probe(c.settings)


@pytest.mark.parametrize(
    "field",
    [
        "route_policy_sha256",
        "auth_policy_sha256",
        "store_id",
        "minimum_access_epoch",
        "credential_deployment_sha256",
    ],
)
async def test_proof_cannot_mix_other_epoch_policy_or_credential_manifest(runtime_case, field):
    c = runtime_case
    c.runtime.proof[field] = "different"
    with pytest.raises(AccessCredentialError, match="access_epoch_mismatch"):
        await c.runtime.probe(c.settings)


async def test_absent_ephemeral_id_is_not_a_matching_current_process(runtime_case):
    c = runtime_case
    c.runtime.proof["new_ephemeral_id"] = None
    c.state["nodes"]["stable"]["ephemeral_id"] = None
    with pytest.raises(AccessCredentialError, match="access_epoch_mismatch"):
        await c.runtime.probe(c.settings)


@pytest.mark.parametrize("name", ["new_config", "route_policy", "auth_policy"])
async def test_public_policy_manifest_must_match_protected_floor(runtime_case, name):
    c = runtime_case
    c.runtime.manifests[name] = canonical_json({"synthetic_other_public_policy": True})
    with pytest.raises(AccessCredentialError, match="access_epoch_mismatch"):
        await c.runtime.probe(c.settings)
