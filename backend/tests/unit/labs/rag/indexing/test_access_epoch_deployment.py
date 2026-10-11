"""Synthetic deployment JSON only: no Docker, network, process or DB operations."""

import importlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_observations import IndexObservation
from ai_workshop.labs.rag.indexing.access_epoch_tls import PreparedTlsAssets
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    AccessEpochBinding,
    ControlExpectedIdentity,
    ControlSettlement,
    CutoverActionKind,
    OriginalDeploymentIdentity,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
    CONTAINER,
    CONTEXT_ENDPOINT_DIGEST,
    DAEMON,
    DOCKER_EXE,
    NETWORK,
    ORIGINAL_IMAGE_ID,
)
from tests.unit.labs.rag.indexing.access_epoch_fixtures import case

NOW = datetime(2026, 10, 8, 8, tzinfo=UTC)
NEW = "d" * 64
MANIFEST = "sha256:" + "e" * 64
VOLUME_CREATED = "2026-01-01T00:00:00Z"


def test_observed_origin_is_exact_reader_registry():
    builder, *_ = setup()
    observed = observation(builder, action(builder))
    assert builder.assert_observed(observed) is None
    with pytest.raises(module().DeploymentError):
        builder.assert_observed(replace(observed))
    other, *_ = setup()
    with pytest.raises(module().DeploymentError):
        other.assert_observed(observed)


def original_volume(daemon):
    return {
        "name": "ai-workshop_elasticsearch-data",
        "driver": "local",
        "scope": "local",
        "created_at": VOLUME_CREATED,
        "mountpoint": "/var/lib/docker/volumes/ai-workshop_elasticsearch-data/_data",
        "options": None,
        "daemon_sha256": daemon,
    }


def module():
    name = "ai_workshop.labs.rag.indexing.access_epoch_deployment"
    assert importlib.util.find_spec(name) is not None, "fixed deployment builder missing"
    return importlib.import_module(name)


def raw(value):
    return json.dumps(value).encode()


def setup():
    m = module()
    execution, epoch_id = uuid4(), uuid4()
    daemon = sha256(
        canonical_json(
            {"id": DAEMON, "os": "linux", "endpoint_sha256": CONTEXT_ENDPOINT_DIGEST}
        ).encode()
    ).hexdigest()
    volume = sha256(canonical_json(original_volume(daemon)).encode()).hexdigest()
    image = sha256(
        canonical_json(
            {"image_id": ORIGINAL_IMAGE_ID, "manifest_digest": MANIFEST, "architecture": "amd64"}
        ).encode()
    ).hexdigest()
    original = OriginalDeploymentIdentity(
        daemon,
        CONTAINER,
        "cluster",
        "stable",
        "old",
        volume,
        "b" * 64,
        image,
        "b" * 64,
        "b" * 64,
        NOW - timedelta(hours=1),
    )
    epoch = PreparedAccessEpoch(
        AccessEpochBinding(case().claim, str(epoch_id), str(execution), 1), original
    )
    directory = m.PROJECT_ROOT / ".local-data/access-epoch/private/tls" / str(epoch_id) / "bind"
    manifest = {
        "epoch_id": str(epoch_id),
        "original_ipv4": "172.28.0.2",
        "http_ca_sha256": "1" * 64,
        "transport_ca_sha256": "2" * 64,
        "http_ca_der_sha256": "3" * 64,
        "transport_ca_der_sha256": "4" * 64,
        "http_leaf_der_sha256": "5" * 64,
        "transport_leaf_der_sha256": "6" * 64,
    }
    tls = PreparedTlsAssets(
        epoch_id,
        uuid4(),
        "172.28.0.2",
        str(directory),
        tuple(
            str(directory / p / name)
            for p in ("http", "transport")
            for name in ("node.key", "node.crt", "ca.crt")
        ),
        canonical_json(manifest),
    )
    index = IndexObservation("synthetic-index", "index-uuid", 12, "7" * 64, "8" * 64)
    builder = m.DeploymentCommands(
        epoch, tls, MANIFEST, "original-cluster", "172.28.0.0/16", "172.28.0.1", (index,)
    )
    return builder, epoch, tls, index


def action(builder, kind=CutoverActionKind.START_BOOTSTRAP):
    return ReservedCutoverAction(
        uuid4(),
        builder.execution_id,
        9,
        kind,
        ControlExpectedIdentity(canonical_json({"target_sha256": builder.target_sha256(kind)}), 8),
        str(uuid4()),
    )


def retirement(builder, current, predecessor=None):
    kind = (
        CutoverActionKind.RETIRE_OLD if predecessor is None else CutoverActionKind.RETIRE_BOOTSTRAP
    )
    container = CONTAINER if predecessor is None else predecessor.container_id
    retired_action = replace(current, action_id=uuid4(), kind=kind, sequence=7)
    manifest = {
        "container_id": container,
        "daemon_sha256": builder.epoch.original.daemon_sha256,
        "action_id": str(retired_action.action_id),
        "sequence": 7,
        "method": "exact_synchronous_command_and_terminal_readback",
        "retired_at": (NOW - timedelta(seconds=5)).isoformat(timespec="microseconds"),
        "stopped_action_id": str(uuid4()),
    }
    settlement = ControlSettlement(
        retired_action.action_id,
        current.execution_id,
        current.executor_generation,
        "settled",
        canonical_json(manifest),
        NOW - timedelta(seconds=5),
    )
    return module().RetiredPredecessor(retired_action, settlement, predecessor)


def build_case(kind=CutoverActionKind.START_BOOTSTRAP):
    builder, epoch, tls, index = setup()
    a = action(builder, kind)
    command = builder.build(a, retirement(builder, a), raw({"ID": DAEMON, "OSType": "linux"}), b"")
    return builder, a, command, tls, index


def container_json(builder, a, container_id=NEW):
    m = module()
    boot = a.kind == CutoverActionKind.START_BOOTSTRAP
    compose = "compose.access-epoch-bootstrap.yaml" if boot else "compose.access-epoch-secured.yaml"
    volume = {
        "Type": "volume",
        "Name": "ai-workshop_elasticsearch-data",
        "Driver": "local",
        "Source": "/var/lib/docker/volumes/ai-workshop_elasticsearch-data/_data",
        "Destination": "/usr/share/elasticsearch/data",
        "RW": True,
        "Propagation": "",
    }
    mounts = [volume]
    sources = [
        (
            str(m.PROJECT_ROOT / "infrastructure/elasticsearch/elasticsearch-secured.yml"),
            "/usr/share/elasticsearch/config/elasticsearch.yml",
        )
    ]
    sources += [
        (
            path,
            "/usr/share/elasticsearch/config/access-epoch-tls/" + "/".join(Path(path).parts[-2:]),
        )
        for path in builder.tls.leaf_locations
    ]
    mounts += [
        {
            "Type": "bind",
            "Source": source,
            "Destination": target,
            "RW": False,
            "Propagation": "rprivate",
        }
        for source, target in sources
    ]
    ports = {} if boot else {"9200/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9200"}]}
    return {
        "Id": container_id,
        "Name": "/ai-workshop-elasticsearch-1",
        "Image": ORIGINAL_IMAGE_ID,
        "Created": NOW.isoformat(),
        "State": {
            "Running": True,
            "Restarting": False,
            "Dead": False,
            "Paused": False,
            "Status": "running",
            "Pid": 123,
            "StartedAt": NOW.isoformat(),
        },
        "Config": {
            "Image": "docker.elastic.co/elasticsearch/elasticsearch:9.5.2@" + MANIFEST,
            "Env": [
                *m.IMAGE_ENV,
                "ES_JAVA_OPTS=-Xms1g -Xmx1g",
                "AI_WORKSHOP_ES_ORIGINAL_CLUSTER_NAME=original-cluster",
            ],
            "Entrypoint": ["/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"],
            "Cmd": ["eswrapper"],
            "User": "1000:0",
            "WorkingDir": "/usr/share/elasticsearch",
            "Labels": {
                "com.docker.compose.project": "ai-workshop",
                "com.docker.compose.service": "elasticsearch",
                "com.docker.compose.container-number": "1",
                "com.docker.compose.oneoff": "False",
                "com.docker.compose.project.config_files": str(
                    m.PROJECT_ROOT / "infrastructure/compose" / compose
                ),
                "com.docker.compose.project.working_dir": str(
                    m.PROJECT_ROOT / "infrastructure/compose"
                ),
                "com.docker.compose.image": ORIGINAL_IMAGE_ID,
                "com.docker.compose.config-hash": "c" * 64,
                "com.docker.compose.version": "2.39.4",
            },
            "Healthcheck": {"Test": ["NONE"]},
        },
        "HostConfig": {
            "NetworkMode": "none" if boot else "ai-workshop_default",
            "PortBindings": ports,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "Privileged": False,
            "AutoRemove": False,
            "PublishAllPorts": False,
            "CapAdd": None,
            "Devices": [],
            "DeviceRequests": None,
            "ExtraHosts": None,
            "Links": None,
            "VolumesFrom": None,
            "PidMode": "",
            "IpcMode": "private",
            "UTSMode": "",
            "SecurityOpt": None,
            "Mounts": [
                {
                    "Type": "volume",
                    "Source": "ai-workshop_elasticsearch-data",
                    "Target": "/usr/share/elasticsearch/data",
                    "VolumeOptions": {"NoCopy": True},
                },
                *[
                    {
                        "Type": "bind",
                        "Source": source,
                        "Target": target,
                        "ReadOnly": True,
                        "BindOptions": {"CreateMountpoint": False},
                    }
                    for source, target in sources
                ],
            ],
        },
        "Mounts": mounts,
        "NetworkSettings": {
            "Ports": ports,
            "Networks": {}
            if boot
            else {
                "ai-workshop_default": {
                    "NetworkID": NETWORK,
                    "IPAddress": "172.28.0.2",
                    "IPPrefixLen": 16,
                    "Gateway": "172.28.0.1",
                    "GlobalIPv6Address": "",
                }
            },
        },
    }


def observation(builder, a, container=None, predecessor=None, *, transform=None):
    m = module()
    container = container or container_json(builder, a)
    network = (
        None
        if a.kind == CutoverActionKind.START_BOOTSTRAP
        else raw(
            [
                {
                    "Id": NETWORK,
                    "Name": "ai-workshop_default",
                    "Driver": "bridge",
                    "Scope": "local",
                    "Internal": False,
                    "EnableIPv6": False,
                    "IPAM": {
                        "Driver": "default",
                        "Config": [{"Subnet": "172.28.0.0/16", "Gateway": "172.28.0.1"}],
                    },
                    "Containers": {container["Id"]: {"IPv4Address": "172.28.0.2/16"}},
                }
            ]
        )
    )
    readback = m.RawDeploymentReadback(
        raw({"ID": DAEMON, "OSType": "linux"}),
        raw([container]),
        raw(
            [
                {
                    "Id": ORIGINAL_IMAGE_ID,
                    "RepoDigests": ["docker.elastic.co/elasticsearch/elasticsearch@" + MANIFEST],
                    "Os": "linux",
                    "Architecture": "amd64",
                }
            ]
        ),
        raw(
            [
                {
                    "Name": "ai-workshop_elasticsearch-data",
                    "Driver": "local",
                    "Scope": "local",
                    "Mountpoint": "/var/lib/docker/volumes/ai-workshop_elasticsearch-data/_data",
                    "Options": None,
                    "CreatedAt": VOLUME_CREATED,
                }
            ]
        ),
        network,
        (container["Id"] + "\n").encode(),
        ("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64, "6" * 64),
        (m.PROJECT_ROOT / "infrastructure/elasticsearch/elasticsearch-secured.yml").read_bytes(),
    )
    if transform:
        readback = transform(readback)
    return builder.decode_daemon(
        a, readback, predecessor=predecessor, observed_at=NOW + timedelta(seconds=2)
    )


def test_fixed_compose_grammar_env_and_one_shot_action():
    builder, a, command, _, _ = build_case()
    assert command.argv[:4] == (
        DOCKER_EXE,
        "--host",
        "npipe:////./pipe/dockerDesktopLinuxEngine",
        "compose",
    )
    assert command.argv[-8:] == (
        "up",
        "--detach",
        "--no-deps",
        "--no-build",
        "--no-recreate",
        "--pull",
        "never",
        "elasticsearch",
    )
    assert command.environment["COMPOSE_DISABLE_ENV_FILE"] == "true"
    assert set(command.environment) == {
        "COMPOSE_DISABLE_ENV_FILE",
        "AI_WORKSHOP_ES_ORIGINAL_MANIFEST_DIGEST",
        "AI_WORKSHOP_ES_ORIGINAL_VOLUME",
        "AI_WORKSHOP_ES_TLS_DIRECTORY",
        "AI_WORKSHOP_ES_ORIGINAL_CLUSTER_NAME",
    }
    assert command.cwd == module().PROJECT_ROOT / "infrastructure/compose"
    with pytest.raises(module().DeploymentError):
        builder.build(a, retirement(builder, a), raw({"ID": DAEMON, "OSType": "linux"}), b"")


def test_complete_daemon_readback_is_public_and_not_authenticated_preservation():
    builder, a, _, _, _ = build_case()
    result = observation(builder, a)
    assert result.container_id == NEW and result.kind == CutoverActionKind.START_BOOTSTRAP
    assert not hasattr(result, "preservation_verified")
    public = json.loads(result.manifest_json)
    assert public["container_id"] == NEW
    assert "HostConfig" not in result.manifest_json and "Env" not in result.manifest_json
    assert "config-hash" not in result.manifest_json and "node.key" not in result.manifest_json


@pytest.mark.parametrize(
    "mutation",
    [
        "env",
        "entrypoint",
        "cmd",
        "user",
        "image",
        "name",
        "privileged",
        "ports",
        "network",
        "mount_rw",
        "mount_extra",
        "mount_source",
        "nocopy",
        "labels",
        "healthcheck",
        "restart",
    ],
)
def test_changed_or_broad_raw_container_configuration_is_rejected(mutation):
    builder, a, _, _, _ = build_case()
    data = container_json(builder, a)
    if mutation == "env":
        data["Config"]["Env"].append("ELASTIC_PASSWORD=synthetic-private")
    elif mutation == "entrypoint":
        data["Config"]["Entrypoint"] = ["sh"]
    elif mutation == "cmd":
        data["Config"]["Cmd"] = ["eswrapper", "-Expack.security.enabled=false"]
    elif mutation == "user":
        data["Config"]["User"] = "root"
    elif mutation == "image":
        data["Image"] = "sha256:" + "f" * 64
    elif mutation == "name":
        data["Name"] = "/ai-workshop-elasticsearch"
    elif mutation == "privileged":
        data["HostConfig"]["Privileged"] = True
    elif mutation == "ports":
        data["HostConfig"]["PortBindings"] = {"9300/tcp": []}
    elif mutation == "network":
        data["HostConfig"]["NetworkMode"] = "host"
    elif mutation == "mount_rw":
        data["Mounts"][1]["RW"] = True
    elif mutation == "mount_extra":
        data["Mounts"].append(data["Mounts"][0])
    elif mutation == "mount_source":
        data["Mounts"][2]["Source"] += "-wrong"
    elif mutation == "nocopy":
        data["HostConfig"]["Mounts"][0]["VolumeOptions"]["NoCopy"] = False
    elif mutation == "labels":
        data["Config"]["Labels"]["com.docker.compose.service"] = "other"
    elif mutation == "healthcheck":
        data["Config"]["Healthcheck"] = {"Test": ["CMD", "curl", "http://localhost:9200"]}
    elif mutation == "restart":
        data["HostConfig"]["RestartPolicy"]["Name"] = "always"
    with pytest.raises(module().DeploymentError, match="^deployment_readback_denied$"):
        observation(builder, a, data)


def test_final_requires_observed_bootstrap_retirement_and_fresh_id():
    builder, bootstrap_action, _, _, _ = build_case()
    bootstrap = observation(builder, bootstrap_action)
    final = replace(
        action(builder, CutoverActionKind.START_SECURED),
        executor_generation=bootstrap_action.executor_generation,
    )
    with pytest.raises(module().DeploymentError):
        builder.build(
            final, retirement(builder, final), raw({"ID": DAEMON, "OSType": "linux"}), b""
        )
    # Failed attempts are consumed; a fresh action object cannot replay the phase.
    other, _, _, _ = setup()
    with pytest.raises(module().DeploymentError):
        other.build(
            final,
            retirement(builder, final, bootstrap),
            raw({"ID": DAEMON, "OSType": "linux"}),
            b"",
        )


def test_final_success_checks_original_network_and_new_immutable_container():
    builder, bootstrap_action, _, _, _ = build_case()
    bootstrap = observation(builder, bootstrap_action)
    final = replace(
        action(builder, CutoverActionKind.START_SECURED),
        executor_generation=bootstrap_action.executor_generation,
    )
    command = builder.build(
        final, retirement(builder, final, bootstrap), raw({"ID": DAEMON, "OSType": "linux"}), b""
    )
    assert command.environment["AI_WORKSHOP_ES_ORIGINAL_IPV4"] == "172.28.0.2"
    assert command.argv[command.argv.index("--file") + 1].endswith(
        "compose.access-epoch-secured.yaml"
    )
    data = container_json(builder, final, "f" * 64)
    result = observation(builder, final, data, bootstrap)
    assert result.container_id != bootstrap.container_id
    with pytest.raises(module().DeploymentError):
        observation(builder, final, container_json(builder, final), bootstrap)


@pytest.mark.parametrize("inventory", [CONTAINER, "occupied-slot"])
def test_existing_predecessor_or_compose_service_prevents_submission(inventory):
    builder, _, _, _ = setup()
    a = action(builder)
    value = {
        "ID": CONTAINER if inventory == CONTAINER else NEW,
        "Names": "ai-workshop-elasticsearch-1",
        "Labels": "com.docker.compose.project=ai-workshop,com.docker.compose.service=elasticsearch",
    }
    with pytest.raises(module().DeploymentError):
        builder.build(a, retirement(builder, a), raw({"ID": DAEMON, "OSType": "linux"}), raw(value))


def test_authenticated_cluster_and_index_preservation_is_separate_exact_readback():
    builder, a, _, _, index = build_case()
    daemon = observation(builder, a)
    root = {
        "cluster_name": "original-cluster",
        "cluster_uuid": "cluster",
        "version": {"number": "9.5.2"},
    }
    state = {
        "cluster_uuid": "cluster",
        "master_node": "stable",
        "nodes": {"stable": {"ephemeral_id": "fresh-bootstrap"}},
    }
    nodes = {
        "cluster_name": "original-cluster",
        "_nodes": {"total": 1, "successful": 1, "failed": 0},
        "nodes": {"stable": {"jvm": {"start_time_in_millis": int(NOW.timestamp() * 1000)}}},
    }
    result = builder.decode_preservation(
        daemon, raw(root), raw(state), raw(nodes), (index,), observed_at=NOW + timedelta(seconds=3)
    )
    assert result.stable_node_id == "stable" and result.ephemeral_id == "fresh-bootstrap"
    with pytest.raises(module().DeploymentError):
        builder.decode_preservation(
            daemon,
            raw(root),
            raw(state),
            raw(nodes),
            (replace(index, count=13),),
            observed_at=NOW + timedelta(seconds=3),
        )


def test_actual_network_none_endpoint_with_no_addresses_is_supported():
    builder, a, _, _, _ = build_case()
    data = container_json(builder, a)
    data["NetworkSettings"]["Networks"] = {
        "none": {
            "NetworkID": "9" * 64,
            "EndpointID": "a" * 64,
            "IPAddress": "",
            "Gateway": "",
            "IPPrefixLen": 0,
            "GlobalIPv6Address": "",
            "IPv6Gateway": "",
            "GlobalIPv6PrefixLen": 0,
        }
    }
    assert observation(builder, a, data)
    data["NetworkSettings"]["Networks"]["none"]["IPAddress"] = "172.28.0.2"
    with pytest.raises(module().DeploymentError):
        observation(builder, a, data)


def test_security_configuration_file_cannot_be_replaced_by_auth_off_content(monkeypatch):
    builder, a, _, _, _ = build_case()
    original = Path.read_bytes

    def changed(path):
        content = original(path)
        return content.replace(b"xpack.security.enabled: true", b"xpack.security.enabled: false")

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(module().DeploymentError):
        observation(builder, a)


@pytest.mark.parametrize(
    "field",
    [
        "volume_created",
        "image_arch",
        "tls_hash",
        "daemon",
        "old_live",
        "duplicates",
        "config_unknown",
    ],
)
def test_original_identity_tls_and_strict_json_regressions(field):
    builder, a, _, _, _ = build_case()

    def transform(value):
        if field == "volume_created":
            data = json.loads(value.volume)
            data[0]["CreatedAt"] = "2026-10-08T08:00:00Z"
            return replace(value, volume=raw(data))
        if field == "image_arch":
            data = json.loads(value.image)
            data[0]["Architecture"] = "arm64"
            return replace(value, image=raw(data))
        if field == "tls_hash":
            return replace(value, tls_public_hashes=("9" * 64, *value.tls_public_hashes[1:]))
        if field == "daemon":
            return replace(value, daemon=raw({"ID": "other", "OSType": "linux"}))
        if field == "old_live":
            return replace(
                value, all_container_ids=value.all_container_ids + CONTAINER.encode() + b"\n"
            )
        if field == "duplicates":
            return replace(
                value, daemon=b'{"ID":"other","ID":"' + DAEMON.encode() + b'","OSType":"linux"}'
            )
        return replace(
            value,
            secured_config=value.secured_config + b"\nxpack.security.http.ssl.enabled: false\n",
        )

    with pytest.raises(module().DeploymentError, match="^deployment_readback_denied$"):
        observation(builder, a, transform=transform)


def test_inert_vendor_labels_are_not_config_authority_or_public_output():
    builder, a, _, _, _ = build_case()
    data = container_json(builder, a)
    data["Config"]["Labels"]["org.vendor.synthetic"] = "synthetic-private-marker"
    result = observation(builder, a, data)
    assert "synthetic-private-marker" not in repr(result)
    data["Config"]["Labels"]["com.docker.compose.hook"] = "post_start"
    with pytest.raises(module().DeploymentError):
        observation(builder, a, data)


def test_command_environment_is_immutable_and_cannot_gain_secret_or_override():
    _, _, command, _, _ = build_case()
    with pytest.raises(TypeError):
        command.environment["COMPOSE_FILE"] = "other.yaml"


@pytest.mark.parametrize(
    "setting,value",
    [
        ("Tmpfs", {"/usr/share/elasticsearch/config": "rw"}),
        ("GroupAdd", ["0"]),
        ("Sysctls", {"net.ipv4.ip_forward": "1"}),
        ("UsernsMode", "host"),
    ],
)
def test_extra_security_sensitive_host_overrides_are_rejected(setting, value):
    builder, a, _, _, _ = build_case()
    data = container_json(builder, a)
    data["HostConfig"][setting] = value
    with pytest.raises(module().DeploymentError):
        observation(builder, a, data)


def preservation_bytes(ephemeral, started):
    return (
        raw(
            {
                "cluster_name": "original-cluster",
                "cluster_uuid": "cluster",
                "version": {"number": "9.5.2"},
            }
        ),
        raw(
            {
                "cluster_uuid": "cluster",
                "master_node": "stable",
                "nodes": {"stable": {"ephemeral_id": ephemeral}},
            }
        ),
        raw(
            {
                "cluster_name": "original-cluster",
                "_nodes": {"total": 1, "successful": 1, "failed": 0},
                "nodes": {
                    "stable": {"jvm": {"start_time_in_millis": int(started.timestamp() * 1000)}}
                },
            }
        ),
    )


def test_final_preservation_requires_bootstrap_baseline_and_new_jvm_identity():
    builder, a, _, _, index = build_case()
    bootstrap = observation(builder, a)
    final = replace(
        action(builder, CutoverActionKind.START_SECURED), executor_generation=a.executor_generation
    )
    data = container_json(builder, final, "f" * 64)
    secured = observation(builder, final, data, bootstrap)
    current = preservation_bytes("fresh-final", NOW + timedelta(seconds=1))
    with pytest.raises(module().DeploymentError):
        builder.decode_preservation(
            secured, *current, (index,), observed_at=NOW + timedelta(seconds=3)
        )
    builder.decode_preservation(
        bootstrap,
        *preservation_bytes("fresh-bootstrap", NOW),
        (index,),
        observed_at=NOW + timedelta(seconds=3),
    )
    assert builder.decode_preservation(
        secured, *current, (index,), observed_at=NOW + timedelta(seconds=3)
    )
    with pytest.raises(module().DeploymentError):
        builder.decode_preservation(
            secured,
            *preservation_bytes("fresh-bootstrap", NOW + timedelta(seconds=1)),
            (index,),
            observed_at=NOW + timedelta(seconds=3),
        )


@pytest.mark.parametrize(
    "field", ["network_id", "ip", "gateway", "network_ipam", "collision", "transport_publish"]
)
def test_final_original_network_and_route_deviation_is_denied(field):
    builder, a, _, _, _ = build_case()
    bootstrap = observation(builder, a)
    final = replace(
        action(builder, CutoverActionKind.START_SECURED), executor_generation=a.executor_generation
    )
    data = container_json(builder, final, "f" * 64)

    def transform(value):
        if field == "network_ipam":
            network = json.loads(value.network)
            network[0]["IPAM"]["Config"][0]["Subnet"] = "172.29.0.0/16"
            return replace(value, network=raw(network))
        if field == "collision":
            network = json.loads(value.network)
            network[0]["Containers"]["9" * 64] = {"IPv4Address": "172.28.0.2/16"}
            return replace(value, network=raw(network))
        container = json.loads(value.container)
        current = container[0]
        if field == "transport_publish":
            current["NetworkSettings"]["Ports"]["9300/tcp"] = [
                {"HostIp": "127.0.0.1", "HostPort": "9300"}
            ]
        else:
            key = {"network_id": "NetworkID", "ip": "IPAddress", "gateway": "Gateway"}[field]
            current["NetworkSettings"]["Networks"]["ai-workshop_default"][key] = "wrong"
        return replace(value, container=raw(container))

    with pytest.raises(module().DeploymentError):
        observation(builder, final, data, bootstrap, transform=transform)


@pytest.mark.parametrize("bad", [True, False, 1.0, 0.0, "1"])
def test_preservation_node_counts_are_exact_integers(bad):
    builder, a, _, _, index = build_case()
    daemon = observation(builder, a)
    cluster, state, nodes = preservation_bytes("fresh-bootstrap", NOW)
    value = json.loads(nodes)
    key = "failed" if bad in (False, 0.0) else "total"
    value["_nodes"][key] = bad
    with pytest.raises(module().DeploymentError, match="^deployment_readback_denied$"):
        builder.decode_preservation(
            daemon, cluster, state, raw(value), (index,), observed_at=NOW + timedelta(seconds=3)
        )


@pytest.mark.parametrize("bad", [True, None, datetime(2026, 10, 8)])
def test_preservation_observed_timestamp_is_exact_utc_datetime(bad):
    builder, a, _, _, index = build_case()
    daemon = observation(builder, a)
    with pytest.raises(module().DeploymentError):
        builder.decode_preservation(
            daemon, *preservation_bytes("fresh-bootstrap", NOW), (index,), observed_at=bad
        )


def test_target_digest_binds_original_network_ipam_values():
    builder, epoch, tls, index = setup()
    changed = module().DeploymentCommands(
        epoch, tls, MANIFEST, "original-cluster", "172.28.0.0/16", "172.28.0.3", (index,)
    )
    assert builder.target_sha256(CutoverActionKind.START_BOOTSTRAP) != changed.target_sha256(
        CutoverActionKind.START_BOOTSTRAP
    )


def test_native_runner_can_require_exact_builder_issued_command_object():
    builder, _, command, _, _ = build_case()
    assert builder.assert_issued(command) is None
    with pytest.raises(module().DeploymentError):
        builder.assert_issued(replace(command))
    other, _, _, _ = setup()
    with pytest.raises(module().DeploymentError):
        other.assert_issued(command)
