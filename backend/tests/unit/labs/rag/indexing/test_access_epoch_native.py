"""Native epoch preflight observes deployment without granting transition authority."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasOperationSnapshot
from tests.unit.labs.rag.indexing.test_alias_recovery_local_native import native_backend


def case(monkeypatch):
    from ai_workshop.labs.rag.indexing.access_epoch_native import OriginalAccessEpochPreflight

    original, runner, reader = native_backend(monkeypatch)
    runner.container["Name"] = "/ai-workshop-elasticsearch-1"
    runner.container["Created"] = "2026-09-01T00:00:00Z"
    runner.container["Image"] = (
        "sha256:80d3ab189f131fca45c958c281975078ac88d8b133200fbae33d70baa40f4654"
    )
    runner.container["Mounts"][0]["Name"] = "ai-workshop_elasticsearch-data"
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import FixedCommand

    runner.responses[FixedCommand.IMAGE_METADATA] = {
        "image_id": runner.container["Image"],
        "repo_digests": ["docker.elastic.co/elasticsearch/elasticsearch@sha256:" + "d" * 64],
        "os": "linux",
        "architecture": "arm64",
    }
    runner.responses[FixedCommand.ORIGINAL_VOLUME_METADATA] = {
        "name": "ai-workshop_elasticsearch-data",
        "driver": "local",
        "scope": "local",
        "created_at": "2026-09-01T00:00:00Z",
        "options": None,
        "mountpoint": "/var/lib/docker/volumes/ai-workshop_elasticsearch-data/_data",
    }
    reader.responses["/"]["cluster_name"] = "ai-workshop"
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import NETWORK

    runner.container["NetworkSettings"]["Networks"] = {
        "ai-workshop_default": {"NetworkID": NETWORK}
    }
    snapshot = AliasOperationSnapshot(
        uuid4(),
        "local_rag_indexes",
        "cluster",
        "active",
        uuid4(),
        uuid4(),
        (),
        datetime.now(UTC),
        "legacy_unknown",
    )
    return OriginalAccessEpochPreflight(original.settings, runner, reader), snapshot, runner, reader


async def test_original_origin_is_observed_with_identity_and_cleared_on_failure(monkeypatch):
    probe, snapshot, runner, reader = case(monkeypatch)
    runner.container["Config"]["Env"].append("xpack.security.enabled=false")
    identity = await probe.observe_original(snapshot)
    assert probe.original_origin.container_id == identity.container_id
    assert probe.original_origin.daemon_sha256 == identity.daemon_sha256
    assert probe.original_origin.name == "ai-workshop-elasticsearch-1"
    assert probe.original_origin.created_at == datetime(2026, 9, 1, tzinfo=UTC)
    runner.container["Created"] = "private-body-marker"
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

    with pytest.raises(LocalRecoveryRefusal):
        await probe.observe_original(snapshot)
    assert probe.original_origin is None


async def test_original_observation_remains_blocked_without_history_and_never_drains_clients(
    monkeypatch,
):
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import FixedCommand

    probe, snapshot, runner, reader = case(monkeypatch)
    result = await probe.preflight(snapshot)
    assert result["deployment_observed"] is True
    assert result["preflight"] == "blocked"
    assert result["diagnostic"] == "historical_control_settlement_unknown"
    assert result["historical_control_settlement"] == "unknown"
    assert result["termination_proven"] is False and result["parity"] == "not_run"
    assert runner.commands == [
        FixedCommand.CONTEXT,
        FixedCommand.DAEMON,
        FixedCommand.CONTAINER,
        FixedCommand.IMAGE_METADATA,
    ]
    assert probe.image_reference.manifest_digest == "sha256:" + "d" * 64
    assert probe.image_reference.image_id == runner.container["Image"]
    assert reader.paths == ["/", "/_cluster/health", "/_cluster/state/master_node,nodes"]
    assert "config" not in result and "env" not in result


@pytest.mark.parametrize(
    "change,diagnostic",
    [
        ("volume", "protected_mount_unverified"),
        ("image", "server_identity_changed"),
        ("node", "single_node_topology_unverified"),
        ("cluster", "cluster_changed"),
        ("stopped", "server_not_running"),
        ("context", "docker_context_changed"),
    ],
)
async def test_changed_original_deployment_refuses_without_mutations(
    monkeypatch, change, diagnostic
):
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import FixedCommand

    probe, snapshot, runner, reader = case(monkeypatch)
    if change == "volume":
        runner.container["Mounts"][0]["Name"] = "other-private-volume"
    elif change == "image":
        runner.container["Image"] = "other-private-image"
    elif change == "node":
        reader.responses["/_cluster/health"]["number_of_nodes"] = 2
    elif change == "cluster":
        reader.responses["/"]["cluster_uuid"] = "other-private-cluster"
    elif change == "stopped":
        runner.container["State"]["Running"] = False
    elif change == "context":
        runner.responses[FixedCommand.CONTEXT][0]["Name"] = "other"
    result = await probe.preflight(snapshot)
    assert result["preflight"] == "blocked" and result["deployment_observed"] is False
    assert result["diagnostic"] == diagnostic
    assert FixedCommand.START not in runner.commands and FixedCommand.STOP not in runner.commands
    assert "other-private" not in str(result)


async def test_untrusted_exception_and_environment_never_appear_in_result(monkeypatch):
    probe, snapshot, runner, reader = case(monkeypatch)
    runner.container["Config"]["Env"].append("PRIVATE_KEY=synthetic-secret-marker")
    result = await probe.preflight(snapshot)
    assert "synthetic-secret-marker" not in str(result)

    async def broken(path):
        raise RuntimeError("synthetic-secret-marker")

    reader.read = broken
    result = await probe.preflight(snapshot)
    assert result["diagnostic"] == "access_epoch_observation_failed"
    assert "synthetic-secret-marker" not in str(result)


async def test_invalid_binding_refuses_before_any_native_io(monkeypatch):
    from dataclasses import replace

    probe, snapshot, runner, reader = case(monkeypatch)
    result = await probe.preflight(replace(snapshot, store_id="other"))
    assert result["diagnostic"] == "access_epoch_binding_mismatch"
    assert not runner.commands and not reader.paths


@pytest.mark.parametrize(
    "change",
    [
        "config_as_manifest",
        "other_id",
        "no_manifest",
        "wrong_repo",
        "many_manifests",
        "private_field",
        "other_os",
    ],
)
async def test_original_manifest_reference_is_distinct_and_bound_to_config_image(
    monkeypatch, change
):
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import FixedCommand

    probe, snapshot, runner, reader = case(monkeypatch)
    metadata = runner.responses[FixedCommand.IMAGE_METADATA]
    if change == "config_as_manifest":
        metadata["repo_digests"] = [
            "docker.elastic.co/elasticsearch/elasticsearch@" + metadata["image_id"]
        ]
    elif change == "other_id":
        metadata["image_id"] = "sha256:" + "a" * 64
    elif change == "no_manifest":
        metadata["repo_digests"] = []
    elif change == "wrong_repo":
        metadata["repo_digests"] = ["private-registry/elasticsearch@sha256:" + "d" * 64]
    elif change == "many_manifests":
        metadata["repo_digests"] *= 2
    elif change == "private_field":
        metadata["Env"] = ["synthetic-private-marker"]
    else:
        metadata["os"] = "windows"
    result = await probe.preflight(snapshot)
    assert result["deployment_observed"] is False
    assert probe.image_reference is None
    assert reader.paths == []
    assert "synthetic-private-marker" not in str(result)


async def test_original_identity_uses_public_projection_without_private_environment_hash(
    monkeypatch,
):
    from ai_workshop.labs.rag.indexing.access_epoch_types import OriginalDeploymentIdentity

    probe, snapshot, runner, reader = case(monkeypatch)
    runner.container["Config"]["Env"].append("xpack.security.enabled=false")
    first = await probe.observe_original(snapshot)
    assert type(first) is OriginalDeploymentIdentity
    assert first.container_id == runner.container["Id"]
    assert first.jvm_start_at > snapshot.created_at.replace(year=2026, month=9, day=28)
    runner.container["Config"]["Env"].append("PRIVATE_KEY=synthetic-private-marker")
    assert await probe.observe_original(snapshot) == first
    assert "synthetic-private-marker" not in str(first)
    assert "/_nodes/jvm" in reader.paths


@pytest.mark.parametrize("change", ["security", "duplicate_security", "bad_jvm", "wrong_jvm_node"])
async def test_original_identity_requires_exact_legacy_security_and_jvm_binding(
    monkeypatch, change
):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

    probe, snapshot, runner, reader = case(monkeypatch)
    runner.container["Config"]["Env"].append("xpack.security.enabled=false")
    if change == "security":
        runner.container["Config"]["Env"][-1] = "xpack.security.enabled=true"
    elif change == "duplicate_security":
        runner.container["Config"]["Env"].append("xpack.security.enabled=false")
    elif change == "bad_jvm":
        reader.responses["/_nodes/jvm"]["nodes"]["node"]["jvm"]["start_time_in_millis"] = True
    else:
        reader.responses["/_nodes/jvm"]["nodes"]["other"] = reader.responses["/_nodes/jvm"][
            "nodes"
        ].pop("node")
    with pytest.raises(LocalRecoveryRefusal):
        await probe.observe_original(snapshot)


async def test_failed_observation_does_not_leave_an_image_reference_for_admission(monkeypatch):
    probe, snapshot, runner, reader = case(monkeypatch)
    reader.responses["/"]["cluster_uuid"] = "other"
    result = await probe.preflight(snapshot)
    assert result["deployment_observed"] is False and probe.image_reference is None


def deployment_case(monkeypatch):
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
        CONTAINER,
        NETWORK,
        FixedCommand,
    )

    probe, snapshot, runner, reader = case(monkeypatch)
    runner.container["Config"]["Env"].append("xpack.security.enabled=false")
    runner.container["HostConfig"]["NetworkMode"] = "ai-workshop_default"
    runner.container["NetworkSettings"]["Networks"]["ai-workshop_default"].update(
        IPAddress="172.24.0.3",
        IPPrefixLen=16,
        Gateway="172.24.0.1",
        GlobalIPv6Address="",
        GlobalIPv6PrefixLen=0,
        IPv6Gateway="",
    )
    runner.responses[FixedCommand.SELECTED_NETWORK_RAW] = [
        {
            "Id": NETWORK,
            "Name": "ai-workshop_default",
            "Driver": "bridge",
            "Scope": "local",
            "Internal": False,
            "EnableIPv6": False,
            "IPAM": {
                "Driver": "default",
                "Config": [
                    {
                        "Subnet": "172.24.0.0/16",
                        "Gateway": "172.24.0.1",
                    }
                ],
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
    return probe, snapshot, runner, reader


async def test_deployment_packets_match_identity_hashes_and_exclude_private_bodies(monkeypatch):
    import hashlib
    import json

    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import FixedCommand

    probe, snapshot, runner, reader = deployment_case(monkeypatch)
    first = await probe.observe_original(snapshot)
    assert FixedCommand.SELECTED_NETWORK_RAW not in runner.commands
    runner.container["Config"]["Env"].append("PRIVATE_KEY=synthetic-private-marker")
    runner.container["HostConfig"]["PrivateField"] = "synthetic-private-marker"
    observed = await probe.observe_deployment(snapshot)
    assert observed.identity == first
    assert observed.snapshot_sha256 == snapshot.sha256
    assert observed.origin == probe.original_origin
    assert observed.image == probe.image_reference
    assert observed.cluster_name == "ai-workshop"
    assert (observed.original_ipv4, observed.network_subnet, observed.network_gateway) == (
        "172.24.0.3",
        "172.24.0.0/16",
        "172.24.0.1",
    )
    expected = {
        "daemon_identity": first.daemon_sha256,
        "original_volume_identity": first.volume_sha256,
        "protected_mount": first.mount_sha256,
        "protected_image": first.image_sha256,
        "old_config": first.config_sha256,
        "old_deployment": first.deployment_sha256,
    }
    assert len(observed.manifest_jsons) == 6
    for name, value in observed.manifest_jsons:
        assert hashlib.sha256(value.encode()).hexdigest() == expected[name]
        assert type(json.loads(value)) is dict
        assert "synthetic-private-marker" not in value
    assert runner.commands.count(FixedCommand.SELECTED_NETWORK_RAW) == 1
    assert probe.assert_observed(observed) is None


@pytest.mark.parametrize(
    "change",
    [
        "network_id",
        "network_name",
        "driver",
        "scope",
        "internal",
        "ipv6",
        "ipam_driver",
        "multiple_subnets",
        "bad_subnet",
        "foreign_gateway",
        "gateway_network",
        "gateway_broadcast",
        "foreign_ip",
        "ip_gateway",
        "ip_network",
        "ip_broadcast",
        "prefix_bool",
        "prefix",
        "endpoint_gateway",
        "endpoint_ipv6",
        "missing_container",
        "wrong_member_ip",
        "wrong_member_name",
        "duplicate_ip",
        "network_mode",
    ],
)
async def test_deployment_requires_same_original_bridge_and_exact_ipv4_membership(
    monkeypatch, change
):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import CONTAINER, FixedCommand

    probe, snapshot, runner, reader = deployment_case(monkeypatch)
    network = runner.responses[FixedCommand.SELECTED_NETWORK_RAW][0]
    endpoint = runner.container["NetworkSettings"]["Networks"]["ai-workshop_default"]
    ipam = network["IPAM"]["Config"][0]
    if change in {"network_id", "network_name", "driver", "scope", "internal", "ipv6"}:
        key, value = {
            "network_id": ("Id", "other"),
            "network_name": ("Name", "other"),
            "driver": ("Driver", "overlay"),
            "scope": ("Scope", "swarm"),
            "internal": ("Internal", True),
            "ipv6": ("EnableIPv6", True),
        }[change]
        network[key] = value
    elif change == "ipam_driver":
        network["IPAM"]["Driver"] = "other"
    elif change == "multiple_subnets":
        network["IPAM"]["Config"] *= 2
    elif change in {"bad_subnet", "foreign_gateway", "gateway_network", "gateway_broadcast"}:
        key, value = {
            "bad_subnet": ("Subnet", "172.24.0.3/16"),
            "foreign_gateway": ("Gateway", "192.0.2.1"),
            "gateway_network": ("Gateway", "172.24.0.0"),
            "gateway_broadcast": ("Gateway", "172.24.255.255"),
        }[change]
        ipam[key] = value
    elif change in {"foreign_ip", "ip_gateway", "ip_network", "ip_broadcast"}:
        endpoint["IPAddress"] = {
            "foreign_ip": "192.0.2.3",
            "ip_gateway": "172.24.0.1",
            "ip_network": "172.24.0.0",
            "ip_broadcast": "172.24.255.255",
        }[change]
    elif change in {"prefix_bool", "prefix", "endpoint_gateway", "endpoint_ipv6"}:
        key, value = {
            "prefix_bool": ("IPPrefixLen", True),
            "prefix": ("IPPrefixLen", 24),
            "endpoint_gateway": ("Gateway", "172.24.0.2"),
            "endpoint_ipv6": ("GlobalIPv6Address", "::1"),
        }[change]
        endpoint[key] = value
    elif change == "missing_container":
        network["Containers"] = {}
    elif change == "wrong_member_ip":
        network["Containers"][CONTAINER]["IPv4Address"] = "172.24.0.4/16"
    elif change == "wrong_member_name":
        network["Containers"][CONTAINER]["Name"] = "other"
    elif change == "duplicate_ip":
        network["Containers"]["a" * 64] = dict(network["Containers"][CONTAINER])
    else:
        runner.container["HostConfig"]["NetworkMode"] = "other"
    with pytest.raises(LocalRecoveryRefusal) as caught:
        await probe.observe_deployment(snapshot)
    assert caught.value.diagnostic == "access_epoch_observation_failed"
    assert probe.image_reference is None and probe.original_origin is None


@pytest.mark.parametrize(
    "change",
    [
        "copy",
        "foreign_issuer",
        "nonce",
        "nested_nonce",
        "snapshot",
        "identity",
        "identity_value",
        "origin_value",
        "image_value",
        "cluster",
        "ipv4",
        "subnet",
        "gateway",
        "packets",
        "packet_list",
    ],
)
async def test_deployment_observation_is_exact_issued_and_immutable_by_value(monkeypatch, change):
    from dataclasses import replace

    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

    probe, snapshot, runner, reader = deployment_case(monkeypatch)
    observed = await probe.observe_deployment(snapshot)
    value = observed
    issuer = probe
    if change == "copy":
        value = replace(observed)
    elif change == "foreign_issuer":
        issuer = deployment_case(monkeypatch)[0]
    elif change == "nonce":
        object.__setattr__(observed, "nonce", uuid4())
    elif change == "nested_nonce":
        object.__setattr__(observed.nonce, "int", uuid4().int)
    elif change == "identity":
        object.__setattr__(observed, "identity", replace(observed.identity, container_id="other"))
    elif change in {"identity_value", "origin_value", "image_value"}:
        child, key = {
            "identity_value": (observed.identity, "container_id"),
            "origin_value": (observed.origin, "name"),
            "image_value": (observed.image, "architecture"),
        }[change]
        object.__setattr__(child, key, "other")
    else:
        key, changed = {
            "snapshot": ("snapshot_sha256", "a" * 64),
            "cluster": ("cluster_name", "other"),
            "ipv4": ("original_ipv4", "172.24.0.4"),
            "subnet": ("network_subnet", "172.24.0.0/24"),
            "gateway": ("network_gateway", "172.24.0.2"),
            "packets": ("manifest_jsons", (("old_config", "{}"),)),
            "packet_list": ("manifest_jsons", list(observed.manifest_jsons)),
        }[change]
        object.__setattr__(observed, key, changed)
    with pytest.raises(LocalRecoveryRefusal):
        issuer.assert_observed(value)


async def test_issued_deployment_survives_later_reads_without_reusing_last_observation(monkeypatch):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

    probe, snapshot, runner, reader = deployment_case(monkeypatch)
    observed = await probe.observe_deployment(snapshot)
    await probe.observe_original(snapshot)
    assert probe.assert_observed(observed) is None
    runner.container["Created"] = "synthetic-private-marker"
    with pytest.raises(LocalRecoveryRefusal):
        await probe.observe_deployment(snapshot)
    assert probe.image_reference is None and probe.original_origin is None
    assert probe.assert_observed(observed) is None


async def test_deployment_uses_own_read_locals_when_identity_query_interleaves(monkeypatch):
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import FixedCommand

    probe, snapshot, runner, reader = deployment_case(monkeypatch)
    initial = await probe.observe_original(snapshot)
    original_run = runner.run

    async def interleaved(command):
        if command == FixedCommand.SELECTED_NETWORK_RAW:
            runner.responses[FixedCommand.IMAGE_METADATA]["architecture"] = "amd64"
            runner.container["Created"] = "2026-09-02T00:00:00Z"
            await probe.observe_original(snapshot)
        return await original_run(command)

    runner.run = interleaved
    observed = await probe.observe_deployment(snapshot)
    assert observed.identity == initial
    assert observed.image.architecture == "arm64"
    assert observed.origin.created_at == datetime(2026, 9, 1, tzinfo=UTC)
    assert probe.image_reference.architecture == "amd64"
    assert probe.assert_observed(observed) is None


async def test_deployment_rejects_snapshot_mutation_during_observation(monkeypatch):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import FixedCommand

    probe, snapshot, runner, reader = deployment_case(monkeypatch)
    original_run = runner.run

    async def altered(command):
        if command == FixedCommand.SELECTED_NETWORK_RAW:
            object.__setattr__(snapshot.indexing_profile_id, "int", uuid4().int)
        return await original_run(command)

    runner.run = altered
    with pytest.raises(LocalRecoveryRefusal):
        await probe.observe_deployment(snapshot)


async def test_deployment_rejects_duplicate_original_ip_with_other_prefix(monkeypatch):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import FixedCommand

    probe, snapshot, runner, reader = deployment_case(monkeypatch)
    network = runner.responses[FixedCommand.SELECTED_NETWORK_RAW][0]
    network["Containers"]["a" * 64] = {
        "Name": "synthetic-peer",
        "IPv4Address": "172.24.0.3/24",
        "IPv6Address": "",
    }
    with pytest.raises(LocalRecoveryRefusal):
        await probe.observe_deployment(snapshot)
