"""Pure synthetic Docker packets; no Docker, native, DB or network execution."""

import importlib
import json
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_deployment import RuntimeDeployment
from ai_workshop.labs.rag.indexing.access_epoch_types import CutoverActionKind
from tests.unit.labs.rag.indexing import test_access_epoch_deployment as deployment

MAX_BYTES = 2 * 1024 * 1024
HASH_NAMES = (
    "http_ca_sha256",
    "transport_ca_sha256",
    "http_ca_der_sha256",
    "transport_ca_der_sha256",
    "http_leaf_der_sha256",
    "transport_leaf_der_sha256",
)
BODIES = ("daemon", "container", "network", "image", "volume")


def module():
    name = "ai_workshop.labs.rag.indexing.access_epoch_docker_packets"
    assert importlib.util.find_spec(name) is not None, "pure Docker identity validator missing"
    return importlib.import_module(name)


def encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def case():
    # Existing synthetic container fixture, no build/observe/native producer call.
    builder, epoch, _, _ = deployment.setup()
    action = deployment.action(builder, CutoverActionKind.START_SECURED)
    container = deployment.container_json(builder, action)
    daemon = {"ID": deployment.DAEMON, "OSType": "linux"}
    daemon_sha = sha256(
        encode(
            {
                "id": deployment.DAEMON,
                "os": "linux",
                "endpoint_sha256": deployment.CONTEXT_ENDPOINT_DIGEST,
            }
        )
    ).hexdigest()
    hashes = {key: str(index) * 64 for index, key in enumerate(HASH_NAMES, 1)}
    original_image = {
        "image_id": deployment.ORIGINAL_IMAGE_ID,
        "manifest_digest": deployment.MANIFEST,
        "architecture": "amd64",
    }
    original_volume = {
        "name": "ai-workshop_elasticsearch-data",
        "driver": "local",
        "scope": "local",
        "created_at": deployment.VOLUME_CREATED,
        "mountpoint": "/var/lib/docker/volumes/ai-workshop_elasticsearch-data/_data",
        "options": None,
        "daemon_sha256": daemon_sha,
    }
    bodies = {
        "daemon": daemon,
        "container": [container],
        "network": [
            {
                "Id": deployment.NETWORK,
                "Name": "ai-workshop_default",
                "Driver": "bridge",
                "Scope": "local",
                "Internal": False,
                "EnableIPv6": False,
                "IPAM": {
                    "Driver": "default",
                    "Config": [
                        {
                            "Subnet": "172.28.0.0/16",
                            "Gateway": "172.28.0.1",
                        }
                    ],
                },
                "Containers": {deployment.NEW: {"IPv4Address": "172.28.0.2/16"}},
            }
        ],
        "image": [
            {
                "Id": deployment.ORIGINAL_IMAGE_ID,
                "RepoDigests": [
                    "docker.elastic.co/elasticsearch/elasticsearch@" + deployment.MANIFEST
                ],
                "Os": "linux",
                "Architecture": "amd64",
            }
        ],
        "volume": [
            {
                "Name": original_volume["name"],
                "Driver": "local",
                "Scope": "local",
                "CreatedAt": deployment.VOLUME_CREATED,
                "Mountpoint": original_volume["mountpoint"],
                "Options": None,
            }
        ],
    }
    manifest = {
        "schema_version": 2,
        "epoch_id": epoch.binding.access_epoch_id,
        "action_id": str(action.action_id),
        "execution_id": str(action.execution_id),
        "kind": "start_secured",
        "cluster_name": "original-cluster",
        "original_ipv4": "172.28.0.2",
        "network_id": deployment.NETWORK,
        "network_subnet": "172.28.0.0/16",
        "network_gateway": "172.28.0.1",
        "container_id": deployment.NEW,
        "image_id": deployment.ORIGINAL_IMAGE_ID,
        "manifest_digest": deployment.MANIFEST,
        "daemon_id": deployment.DAEMON,
        "volume_name": original_volume["name"],
        "docker_started_at": deployment.NOW.isoformat(),
        "created_at": deployment.NOW.isoformat(),
        "observed_at": (deployment.NOW + timedelta(seconds=2)).isoformat(),
        "network_mode": "original_bridge",
        "tls_public_hashes": hashes,
        "public_security_profile": "project_http_tls_transport_mtls",
    }
    # This is the checked-in public YAML, never root .env or protected TLS files.
    secured = (
        deployment.module().PROJECT_ROOT / "infrastructure/elasticsearch/elasticsearch-secured.yml"
    ).read_bytes()
    return SimpleNamespace(
        bodies=bodies,
        manifest=manifest,
        original_image=original_image,
        original_volume=original_volume,
        hashes=hashes,
        secured=secured,
    )


def arguments(c):
    return {
        **{name + "_body": encode(value) for name, value in c.bodies.items()},
        "deployment_manifest_json": encode(c.manifest).decode(),
        "original_image_json": encode(c.original_image).decode(),
        "original_volume_json": encode(c.original_volume).decode(),
        "secured_config": c.secured,
        "tls_public_hashes": c.hashes,
    }


def test_exact_five_packets_return_only_runtime_public_identity_without_mutation():
    m = module()
    c = case()
    c.bodies["image"][0]["Config"] = {"Env": ["PRIVATE=synthetic-private-marker"]}
    c.bodies["container"][0]["Config"]["Labels"]["vendor.private"] = "synthetic-private-marker"
    c.bodies["volume"][0]["Labels"] = {"private": "synthetic-private-marker"}
    before = deepcopy(c.bodies)
    actual = m.validate_docker_identity(**arguments(c))
    assert type(actual) is RuntimeDeployment
    assert asdict(actual) == {
        "epoch_id": UUID(c.manifest["epoch_id"]),
        "execution_id": UUID(c.manifest["execution_id"]),
        "container_id": deployment.NEW,
        "cluster_name": "original-cluster",
        "started_at": deployment.NOW,
    }
    assert c.bodies == before
    assert "synthetic-private-marker" not in repr(actual)
    assert "Env" not in repr(actual) and "HostConfig" not in repr(actual)


def test_hash_dictionary_order_does_not_change_named_tls_binding():
    m = module()
    c = case()
    c.hashes = dict(reversed(tuple(c.hashes.items())))
    assert m.validate_docker_identity(**arguments(c)).container_id == deployment.NEW


@pytest.mark.parametrize(
    "change",
    ["id", "digest", "repository", "empty", "many", "digest_type", "os", "architecture", "missing"],
)
def test_actual_image_must_match_original_config_manifest_architecture(change):
    m = module()
    c = case()
    image = c.bodies["image"][0]
    if change == "id":
        image["Id"] = "sha256:" + "a" * 64
    elif change == "digest":
        image["RepoDigests"] = ["docker.elastic.co/elasticsearch/elasticsearch@sha256:" + "f" * 64]
    elif change == "repository":
        image["RepoDigests"] = ["other.example/elasticsearch@" + deployment.MANIFEST]
    elif change == "empty":
        image["RepoDigests"] = []
    elif change == "many":
        image["RepoDigests"] *= 2
    elif change == "digest_type":
        image["RepoDigests"] = image["RepoDigests"][0]
    elif change == "missing":
        del image["Architecture"]
    else:
        image["Os" if change == "os" else "Architecture"] = "other"
    with pytest.raises(ValueError):
        m.validate_docker_identity(**arguments(c))


@pytest.mark.parametrize(
    "change", ["name", "driver", "scope", "created", "mountpoint", "options", "missing"]
)
def test_volume_recreation_or_storage_change_is_not_preservation(change):
    m = module()
    c = case()
    volume = c.bodies["volume"][0]
    if change == "missing":
        del volume["Options"]
    else:
        key, value = {
            "name": ("Name", "other-volume"),
            "driver": ("Driver", "other"),
            "scope": ("Scope", "global"),
            "created": ("CreatedAt", "2026-02-01T00:00:00Z"),
            "mountpoint": ("Mountpoint", "/other/path"),
            "options": ("Options", {}),
        }[change]
        volume[key] = value
    with pytest.raises(ValueError):
        m.validate_docker_identity(**arguments(c))


@pytest.mark.parametrize(
    "change",
    [
        "image_extra",
        "image_missing",
        "image_arch",
        "image_manifest",
        "volume_extra",
        "volume_missing",
        "volume_daemon",
        "volume_created",
        "volume_options",
        "config_as_manifest",
    ],
)
def test_original_public_projections_are_closed_and_bound_to_actual_packets(change):
    m = module()
    c = case()
    if change == "image_extra":
        c.original_image["caller_approved"] = True
    elif change == "image_missing":
        del c.original_image["architecture"]
    elif change == "image_arch":
        c.original_image["architecture"] = "arm64"
    elif change == "image_manifest":
        c.original_image["manifest_digest"] = "sha256:" + "f" * 64
    elif change == "config_as_manifest":
        c.original_image["manifest_digest"] = deployment.ORIGINAL_IMAGE_ID
    elif change == "volume_extra":
        c.original_volume["caller_approved"] = True
    elif change == "volume_missing":
        del c.original_volume["daemon_sha256"]
    elif change == "volume_daemon":
        c.original_volume["daemon_sha256"] = "f" * 64
    elif change == "volume_created":
        c.original_volume["created_at"] = "2026-02-01T00:00:00Z"
    else:
        c.original_volume["options"] = {}
    with pytest.raises(ValueError):
        m.validate_docker_identity(**arguments(c))


@pytest.mark.parametrize(
    "change", ["image_digest", "volume_options", "volume_future", "volume_naive", "volume_bad_date"]
)
def test_matching_two_bad_inputs_cannot_bypass_deployment_or_original_contract(change):
    m = module()
    c = case()
    if change == "image_digest":
        digest = "sha256:" + "f" * 64
        c.original_image["manifest_digest"] = digest
        c.bodies["image"][0]["RepoDigests"] = [
            "docker.elastic.co/elasticsearch/elasticsearch@" + digest
        ]
    elif change == "volume_options":
        c.original_volume["options"] = c.bodies["volume"][0]["Options"] = {}
    else:
        value = {
            "volume_future": "2030-01-01T00:00:00Z",
            "volume_naive": "2026-01-01T00:00:00",
            "volume_bad_date": "synthetic-private-marker",
        }[change]
        c.original_volume["created_at"] = c.bodies["volume"][0]["CreatedAt"] = value
    with pytest.raises(ValueError) as error:
        m.validate_docker_identity(**arguments(c))
    assert "synthetic-private-marker" not in str(error.value)


@pytest.mark.parametrize(
    "change",
    [
        "daemon_id",
        "daemon_os",
        "container_id",
        "running",
        "pid_bool",
        "network",
        "env",
        "mount",
        "config",
        "tls_missing",
        "tls_extra",
        "tls_swapped",
    ],
)
def test_runtime_deployment_checks_remain_mandatory(change):
    m = module()
    c = case()
    container = c.bodies["container"][0]
    if change in {"daemon_id", "daemon_os"}:
        c.bodies["daemon"]["ID" if change == "daemon_id" else "OSType"] = "other"
    elif change == "container_id":
        container["Id"] = "a" * 64
    elif change == "running":
        container["State"]["Running"] = False
    elif change == "pid_bool":
        container["State"]["Pid"] = True
    elif change == "network":
        c.bodies["network"][0]["Id"] = "a" * 64
    elif change == "env":
        container["Config"]["Env"].append("PRIVATE=synthetic-private-marker")
    elif change == "mount":
        container["Mounts"][0]["Name"] = "other-volume"
    elif change == "config":
        c.secured = c.secured.replace(
            b"xpack.security.enabled: true", b"xpack.security.enabled: false"
        )
    elif change == "tls_missing":
        del c.hashes[HASH_NAMES[0]]
    elif change == "tls_extra":
        c.hashes["other"] = "a" * 64
    else:
        # A copied dictionary prevents changing the expected manifest simultaneously.
        c.hashes = dict(c.hashes)
        c.hashes[HASH_NAMES[0]], c.hashes[HASH_NAMES[1]] = (
            c.hashes[HASH_NAMES[1]],
            c.hashes[HASH_NAMES[0]],
        )
    with pytest.raises(ValueError) as error:
        m.validate_docker_identity(**arguments(c))
    assert "synthetic-private-marker" not in str(error.value)


@pytest.mark.parametrize("name", ["container", "network", "image", "volume"])
@pytest.mark.parametrize("change", ["object", "empty", "many", "scalar"])
def test_inspect_packets_require_exact_single_object_array(name, change):
    m = module()
    c = case()
    original = c.bodies[name]
    c.bodies[name] = {"object": original[0], "empty": [], "many": original * 2, "scalar": [True]}[
        change
    ]
    with pytest.raises(ValueError):
        m.validate_docker_identity(**arguments(c))


@pytest.mark.parametrize("name", BODIES)
@pytest.mark.parametrize(
    "change", ["duplicate", "nonfinite", "overflow", "utf8", "text", "bytearray"]
)
def test_each_response_rejects_ambiguous_json_or_wire_coercion(name, change):
    m = module()
    c = case()
    args = arguments(c)
    raw = args[name + "_body"]
    if change in {"duplicate", "nonfinite", "overflow"}:
        prefix = {
            "duplicate": b'"private":1,"private":2,',
            "nonfinite": b'"private":NaN,',
            "overflow": b'"private":1e999,',
        }[change]
        # Keep the original valid shape: a permissive JSON parser would otherwise pass.
        raw = raw.replace(b"{", b"{" + prefix, 1)
    else:
        raw = {"utf8": b"\xff", "text": raw.decode(), "bytearray": bytearray(raw)}[change]
    args[name + "_body"] = raw
    with pytest.raises(ValueError):
        m.validate_docker_identity(**args)


@pytest.mark.parametrize("name", BODIES)
def test_each_packet_accepts_exact_2mib_limit_and_rejects_one_extra_byte(name):
    m = module()
    c = case()
    args = arguments(c)
    key = name + "_body"
    args[key] += b" " * (MAX_BYTES - len(args[key]))
    assert m.validate_docker_identity(**args).container_id == deployment.NEW
    args[key] += b" "
    with pytest.raises(ValueError):
        m.validate_docker_identity(**args)


@pytest.mark.parametrize(
    "name", ["deployment_manifest_json", "original_image_json", "original_volume_json"]
)
@pytest.mark.parametrize("change", ["duplicate", "nonfinite", "oversize", "bytes"])
def test_bound_manifests_do_not_adopt_ambiguous_or_coerced_caller_data(name, change):
    m = module()
    args = arguments(case())
    raw = args[name]
    if change == "duplicate":
        first = next(iter(json.loads(raw)))
        duplicate = json.dumps(first) + ":" + json.dumps(json.loads(raw)[first]) + ","
        args[name] = "{" + duplicate + raw[1:]
    elif change == "nonfinite":
        args[name] = '{"private":1e999,' + raw[1:]
    elif change == "oversize":
        args[name] += " " * (MAX_BYTES + 1)
    else:
        args[name] = raw.encode()
    with pytest.raises(ValueError):
        m.validate_docker_identity(**args)
