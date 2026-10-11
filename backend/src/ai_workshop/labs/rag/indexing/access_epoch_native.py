"""Observe the original legacy deployment; never authorize or execute a cutover."""

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from typing import cast
from uuid import UUID, uuid4

from ai_workshop.config import Settings
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    OriginalDeploymentIdentity,
    OriginalTargetOrigin,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
    CONTAINER,
    CONTEXT_ENDPOINT_DIGEST,
    DAEMON,
    NETWORK,
    ORIGINAL_IMAGE_ID,
    CommandExecutor,
    DirectElasticsearchReader,
    ElasticsearchReader,
    FixedCommand,
    NativeCommandExecutor,
    ReadOnlyCommandExecutor,
    safe_preflight_diagnostic,
    validate_endpoint,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasOperationSnapshot

# Original deployment inventory, 2026-10-02; no caller-selected container/image/volume.
ORIGINAL_IMAGE = ORIGINAL_IMAGE_ID
ORIGINAL_VOLUME = "ai-workshop_elasticsearch-data"


@dataclass(frozen=True, slots=True)
class OriginalImageReference:
    image_id: str
    manifest_digest: str
    architecture: str


@dataclass(frozen=True, slots=True, eq=False)
class OriginalDeploymentObservation:
    """Same-read public source packets; issuance grants no control authority."""

    nonce: UUID
    snapshot_sha256: str
    identity: OriginalDeploymentIdentity
    origin: OriginalTargetOrigin
    image: OriginalImageReference
    cluster_name: str
    original_ipv4: str
    network_subnet: str
    network_gateway: str
    manifest_jsons: tuple[tuple[str, str], ...]


def _observation_signature(value: OriginalDeploymentObservation) -> tuple[object, ...]:
    """Snapshot primitives, never retain mutable nested objects as the signature."""
    if (
        type(value.nonce) is not UUID
        or type(value.identity) is not OriginalDeploymentIdentity
        or type(value.origin) is not OriginalTargetOrigin
        or type(value.image) is not OriginalImageReference
        or type(value.manifest_jsons) is not tuple
        or any(type(pair) is not tuple or len(pair) != 2 for pair in value.manifest_jsons)
    ):
        raise ValueError

    def primitives(
        child: OriginalDeploymentIdentity | OriginalTargetOrigin | OriginalImageReference,
    ) -> tuple[object, ...]:
        result: list[object] = []
        for field in fields(child):
            item = getattr(child, field.name)
            if type(item) is str:
                result.append(item)
            elif type(item) is datetime and item.utcoffset() == timedelta(0):
                result.append(item.isoformat())
            else:
                raise ValueError
        return tuple(result)

    strings = (
        value.snapshot_sha256,
        value.cluster_name,
        value.original_ipv4,
        value.network_subnet,
        value.network_gateway,
    )
    if any(type(item) is not str for item in strings) or any(
        type(item) is not str for pair in value.manifest_jsons for item in pair
    ):
        raise ValueError
    return (
        str(value.nonce),
        *strings,
        id(value.identity),
        primitives(value.identity),
        id(value.origin),
        primitives(value.origin),
        id(value.image),
        primitives(value.image),
        value.manifest_jsons,
    )


def _original_network(
    value: object, container: dict[str, object], host: dict[str, object]
) -> tuple[str, str, str]:
    """Validate the selected original bridge and its exact container IPv4 endpoint."""
    if type(value) is not list or len(value) != 1:
        raise ValueError
    network = _object(value[0])
    ipam = _object(network.get("IPAM"))
    configs = ipam.get("Config")
    if (
        network.get("Id") != NETWORK
        or network.get("Name") != "ai-workshop_default"
        or network.get("Driver") != "bridge"
        or network.get("Scope") != "local"
        or network.get("Internal") is not False
        or network.get("EnableIPv6") is not False
        or host.get("NetworkMode") != "ai-workshop_default"
        or ipam.get("Driver") != "default"
        or type(configs) is not list
        or len(configs) != 1
    ):
        raise ValueError
    config = _object(configs[0])
    if set(config) != {"Subnet", "Gateway"} or any(type(x) is not str for x in config.values()):
        raise ValueError
    subnet = IPv4Network(cast(str, config["Subnet"]), strict=True)
    gateway = IPv4Address(cast(str, config["Gateway"]))
    endpoints = _object(_object(container.get("NetworkSettings")).get("Networks"))
    endpoint = _object(endpoints.get("ai-workshop_default"))
    if (
        set(endpoints) != {"ai-workshop_default"}
        or endpoint.get("NetworkID") != NETWORK
        or type(endpoint.get("IPAddress")) is not str
        or type(endpoint.get("IPPrefixLen")) is not int
        or endpoint.get("IPPrefixLen") != subnet.prefixlen
        or endpoint.get("Gateway") != str(gateway)
        or endpoint.get("GlobalIPv6Address") != ""
        or type(endpoint.get("GlobalIPv6PrefixLen")) is not int
        or endpoint.get("GlobalIPv6PrefixLen") != 0
        or endpoint.get("IPv6Gateway") != ""
    ):
        raise ValueError
    address = IPv4Address(cast(str, endpoint["IPAddress"]))
    if (
        gateway not in subnet
        or address not in subnet
        or gateway in (subnet.network_address, subnet.broadcast_address)
        or address in (subnet.network_address, subnet.broadcast_address, gateway)
    ):
        raise ValueError
    members = _object(network.get("Containers"))
    original = _object(members.get(CONTAINER))
    expected_address = f"{address}/{subnet.prefixlen}"
    if (
        original.get("Name") != "ai-workshop-elasticsearch-1"
        or original.get("IPv4Address") != expected_address
        or original.get("IPv6Address") != ""
    ):
        raise ValueError
    for key, member in members.items():
        if key == CONTAINER:
            continue
        member_address = _object(member).get("IPv4Address")
        if type(member_address) is not str or IPv4Interface(member_address).ip == address:
            raise ValueError
    return str(address), str(subnet), str(gateway)


def original_image_reference(value: object) -> OriginalImageReference:
    """A local config image ID is not a registry manifest digest."""
    metadata = _object(value)
    refs = metadata.get("repo_digests")
    architecture = metadata.get("architecture")
    prefix = "docker.elastic.co/elasticsearch/elasticsearch@"
    if (
        set(metadata) != {"image_id", "repo_digests", "os", "architecture"}
        or metadata["image_id"] != ORIGINAL_IMAGE
        or metadata["os"] != "linux"
        or type(architecture) is not str
        or re.fullmatch(r"[a-z0-9_]{1,32}", architecture) is None
        or type(refs) is not list
        or len(refs) != 1
        or type(refs[0]) is not str
        or re.fullmatch(re.escape(prefix) + r"sha256:[0-9a-f]{64}", refs[0]) is None
        or refs[0][len(prefix) :] == ORIGINAL_IMAGE
    ):
        raise LocalRecoveryRefusal("server_identity_changed")
    return OriginalImageReference(ORIGINAL_IMAGE, refs[0][len(prefix) :], architecture)


def _object(value: object) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise LocalRecoveryRefusal("local_enumeration_incomplete")
    return cast(dict[str, object], value)


class OriginalAccessEpochPreflight:
    def __init__(
        self,
        settings: Settings,
        executor: CommandExecutor | None = None,
        reader: ElasticsearchReader | None = None,
    ) -> None:
        self.settings = settings
        self.executor = ReadOnlyCommandExecutor(executor or NativeCommandExecutor())
        self.reader = reader or DirectElasticsearchReader()
        self.image_reference: OriginalImageReference | None = None
        self.original_origin: OriginalTargetOrigin | None = None
        self._observed: dict[OriginalDeploymentObservation, tuple[object, ...]] = {}

    async def preflight(self, snapshot: AliasOperationSnapshot) -> dict[str, object]:
        result: dict[str, object] = {
            "preflight": "blocked",
            "termination_proven": False,
            "parity": "not_run",
            "deployment_observed": False,
            "historical_control_settlement": "unknown",
            "route_verification": "not_performed",
        }
        self.image_reference = None
        self.original_origin = None
        try:
            await self._observe(snapshot)
        except LocalRecoveryRefusal as exc:
            self.image_reference = None
            result["diagnostic"] = (
                exc.diagnostic
                if exc.diagnostic == "access_epoch_binding_mismatch"
                else safe_preflight_diagnostic(exc.diagnostic, "access_epoch_observation_failed")
            )
        except Exception:
            self.image_reference = None
            result["diagnostic"] = "access_epoch_observation_failed"
        else:
            result.update(
                deployment_observed=True, diagnostic="historical_control_settlement_unknown"
            )
        return result

    async def _json(self, command: FixedCommand) -> object:
        return cast(object, json.loads(await self.executor.run(command)))

    async def observe_original(
        self, snapshot: AliasOperationSnapshot
    ) -> OriginalDeploymentIdentity:
        self.image_reference = None
        self.original_origin = None
        try:
            result = await self._observe(snapshot, collect_identity=True)
            if type(result) is not OriginalDeploymentIdentity:
                raise ValueError
            return result
        except Exception:
            self.image_reference = None
            self.original_origin = None
            raise LocalRecoveryRefusal("access_epoch_observation_failed") from None

    async def observe_deployment(
        self, snapshot: AliasOperationSnapshot
    ) -> OriginalDeploymentObservation:
        self.image_reference = None
        self.original_origin = None
        try:
            snapshot_sha256 = snapshot.sha256
            result = await self._observe(snapshot, collect_identity=True, collect_deployment=True)
            if (
                type(result) is not OriginalDeploymentObservation
                or snapshot.sha256 != snapshot_sha256
                or result.snapshot_sha256 != snapshot_sha256
            ):
                raise ValueError
            self._observed[result] = _observation_signature(result)
            return result
        except Exception:
            self.image_reference = None
            self.original_origin = None
            raise LocalRecoveryRefusal("access_epoch_observation_failed") from None

    def assert_observed(self, value: object) -> None:
        try:
            if (
                type(value) is not OriginalDeploymentObservation
                or value not in self._observed
                or self._observed[value] != _observation_signature(value)
            ):
                raise ValueError
        except Exception:
            raise LocalRecoveryRefusal("access_epoch_observation_failed") from None

    async def _observe(
        self,
        snapshot: AliasOperationSnapshot,
        *,
        collect_identity: bool = False,
        collect_deployment: bool = False,
    ) -> OriginalDeploymentIdentity | OriginalDeploymentObservation | None:
        if self.settings.environment != "local" or sys.platform != "win32":
            raise LocalRecoveryRefusal("windows_local_required")
        if (snapshot.store_id, snapshot.cluster_uuid) != (
            self.settings.rag_index_store_id,
            self.settings.rag_index_cluster_uuid,
        ):
            raise LocalRecoveryRefusal("access_epoch_binding_mismatch")
        validate_endpoint(self.settings.elasticsearch_url, os.environ)
        contexts = await self._json(FixedCommand.CONTEXT)
        if type(contexts) is not list or len(contexts) != 1:
            raise LocalRecoveryRefusal("docker_context_changed")
        context = _object(contexts[0])
        endpoint = _object(_object(context.get("Endpoints")).get("docker")).get("Host")
        if (
            context.get("Name") != "desktop-linux"
            or type(endpoint) is not str
            or hashlib.sha256(endpoint.encode()).hexdigest() != CONTEXT_ENDPOINT_DIGEST
        ):
            raise LocalRecoveryRefusal("docker_context_changed")
        daemon = _object(await self._json(FixedCommand.DAEMON))
        if daemon.get("ID") != DAEMON or daemon.get("OSType") != "linux":
            raise LocalRecoveryRefusal("docker_daemon_changed")
        containers = await self._json(FixedCommand.CONTAINER)
        if type(containers) is not list or len(containers) != 1:
            raise LocalRecoveryRefusal("server_identity_changed")
        container = _object(containers[0])
        if container.get("Id") != CONTAINER or container.get("Image") != ORIGINAL_IMAGE:
            raise LocalRecoveryRefusal("server_identity_changed")
        state = _object(container.get("State"))
        if state.get("Running") is not True or state.get("Restarting") is not False:
            raise LocalRecoveryRefusal("server_not_running")
        config, host = _object(container.get("Config")), _object(container.get("HostConfig"))
        env = config.get("Env")
        if (
            type(env) is not list
            or "discovery.type=single-node" not in env
            or host.get("PortBindings")
            != {"9200/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9200"}]}
            or host.get("Privileged") is not False
            or host.get("AutoRemove") is not False
        ):
            raise LocalRecoveryRefusal("single_node_topology_unverified")
        mounts = container.get("Mounts")
        if type(mounts) is not list or len(mounts) != 1:
            raise LocalRecoveryRefusal("protected_mount_unverified")
        mount = _object(mounts[0])
        if (
            mount.get("Name") != ORIGINAL_VOLUME
            or mount.get("Type") != "volume"
            or mount.get("Destination") != "/usr/share/elasticsearch/data"
            or mount.get("Driver") != "local"
            or mount.get("RW") is not True
        ):
            raise LocalRecoveryRefusal("protected_mount_unverified")
        image_reference = original_image_reference(await self._json(FixedCommand.IMAGE_METADATA))
        self.image_reference = image_reference
        info = _object(await self.reader.read("/"))
        if info.get("cluster_uuid") != snapshot.cluster_uuid:
            raise LocalRecoveryRefusal("cluster_changed")
        health = _object(await self.reader.read("/_cluster/health"))
        if any(
            type(health.get(key)) is not int or health[key] != 1
            for key in ("number_of_nodes", "number_of_data_nodes")
        ):
            raise LocalRecoveryRefusal("single_node_topology_unverified")
        cluster = _object(await self.reader.read("/_cluster/state/master_node,nodes"))
        nodes = _object(cluster.get("nodes"))
        if cluster.get("cluster_uuid") != snapshot.cluster_uuid:
            raise LocalRecoveryRefusal("cluster_changed")
        if len(nodes) != 1 or cluster.get("master_node") not in nodes:
            raise LocalRecoveryRefusal("single_node_topology_unverified")
        node = _object(next(iter(nodes.values())))
        if type(node.get("ephemeral_id")) is not str or not node["ephemeral_id"]:
            raise LocalRecoveryRefusal("single_node_topology_unverified")
        if not collect_identity:
            return None
        # No Config.Env/HostConfig body or body hash may enter public evidence.
        if [x for x in env if type(x) is str and x.startswith("xpack.security.enabled=")] != [
            "xpack.security.enabled=false"
        ]:
            raise LocalRecoveryRefusal("access_epoch_observation_failed")
        name = info.get("cluster_name")
        if type(name) is not str or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", name) is None:
            raise LocalRecoveryRefusal("access_epoch_observation_failed")
        networks = _object(_object(container.get("NetworkSettings")).get("Networks"))
        if (
            set(networks) != {"ai-workshop_default"}
            or _object(networks["ai-workshop_default"]).get("NetworkID") != NETWORK
        ):
            raise LocalRecoveryRefusal("access_epoch_observation_failed")
        jvm = _object(await self.reader.read("/_nodes/jvm"))
        jvm_nodes = _object(jvm.get("nodes"))
        counters = _object(jvm.get("_nodes"))
        if (
            set(jvm_nodes) != set(nodes)
            or set(counters) != {"total", "successful", "failed"}
            or any(
                type(counters[key]) is not int or counters[key] != expected
                for key, expected in (("total", 1), ("successful", 1), ("failed", 0))
            )
        ):
            raise LocalRecoveryRefusal("single_node_topology_unverified")
        stable = next(iter(nodes))
        milliseconds = _object(_object(jvm_nodes[stable]).get("jvm")).get("start_time_in_millis")
        if type(milliseconds) is not int or not 0 < milliseconds < 253402300800000:
            raise LocalRecoveryRefusal("single_node_topology_unverified")
        started = datetime.fromtimestamp(milliseconds // 1000, UTC) + timedelta(
            milliseconds=milliseconds % 1000
        )
        docker_started = datetime.fromisoformat(cast(str, state.get("StartedAt")))
        if docker_started.utcoffset() != timedelta(
            0
        ) or not docker_started <= started <= datetime.now(UTC):
            raise LocalRecoveryRefusal("single_node_topology_unverified")
        volume = _object(await self._json(FixedCommand.ORIGINAL_VOLUME_METADATA))
        if (
            set(volume) != {"name", "driver", "scope", "created_at", "mountpoint", "options"}
            or volume["name"] != ORIGINAL_VOLUME
            or volume["driver"] != "local"
            or volume["scope"] != "local"
            or volume["options"] is not None
            or volume["mountpoint"]
            != "/var/lib/docker/volumes/ai-workshop_elasticsearch-data/_data"
            or type(volume["created_at"]) is not str
        ):
            raise LocalRecoveryRefusal("protected_mount_unverified")
        created = datetime.fromisoformat(volume["created_at"])
        if created.utcoffset() != timedelta(0) or created > docker_started:
            raise LocalRecoveryRefusal("protected_mount_unverified")

        packets: dict[str, str] = {}

        def fingerprint(key: str, value: dict[str, object]) -> str:
            packets[key] = canonical_json(value)
            return hashlib.sha256(packets[key].encode()).hexdigest()

        daemon_sha = fingerprint(
            "daemon_identity",
            {"id": DAEMON, "os": "linux", "endpoint_sha256": CONTEXT_ENDPOINT_DIGEST},
        )
        container_created = container.get("Created")
        if (
            container.get("Name") != "/ai-workshop-elasticsearch-1"
            or type(container_created) is not str
        ):
            raise LocalRecoveryRefusal("access_epoch_observation_failed")
        created_at = datetime.fromisoformat(container_created)
        if created_at.utcoffset() != timedelta(0) or created_at > docker_started:
            raise LocalRecoveryRefusal("access_epoch_observation_failed")
        origin = OriginalTargetOrigin(
            CONTAINER, daemon_sha, "ai-workshop-elasticsearch-1", created_at
        )
        self.original_origin = origin
        volume_sha = fingerprint("original_volume_identity", volume | {"daemon_sha256": daemon_sha})
        mount_sha = fingerprint(
            "protected_mount",
            {"name": ORIGINAL_VOLUME, "destination": mount["Destination"], "rw": True},
        )
        image_sha = fingerprint(
            "protected_image",
            {
                "image_id": image_reference.image_id,
                "manifest_digest": image_reference.manifest_digest,
                "architecture": image_reference.architecture,
            },
        )
        public_config = {
            "cluster_name": name,
            "discovery.type": "single-node",
            "xpack.security.enabled": False,
            "port_bindings": host["PortBindings"],
            "privileged": False,
            "auto_remove": False,
            "network_id": NETWORK,
        }
        config_sha = fingerprint("old_config", public_config)
        deployment_sha = fingerprint(
            "old_deployment",
            {
                "container_id": CONTAINER,
                "image_sha256": image_sha,
                "volume_sha256": volume_sha,
                "mount_sha256": mount_sha,
                "config_sha256": config_sha,
                "docker_started_at": state["StartedAt"],
            },
        )
        identity = OriginalDeploymentIdentity(
            daemon_sha,
            CONTAINER,
            snapshot.cluster_uuid,
            stable,
            cast(str, node["ephemeral_id"]),
            volume_sha,
            mount_sha,
            image_sha,
            config_sha,
            deployment_sha,
            started,
        )
        if not collect_deployment:
            return identity
        address, subnet, gateway = _original_network(
            await self._json(FixedCommand.SELECTED_NETWORK_RAW), container, host
        )
        return OriginalDeploymentObservation(
            uuid4(),
            snapshot.sha256,
            identity,
            origin,
            image_reference,
            name,
            address,
            subnet,
            gateway,
            tuple(packets.items()),
        )
