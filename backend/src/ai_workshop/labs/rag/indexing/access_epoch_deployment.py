"""Fixed Compose grammar and private-input/public-output deployment observations.

This module does not execute, authorize, commit or prove delegate settlement.
The recorded controller supplies current reservation, protected TLS readback and
authoritative daemon responses. Process exit alone is never an observation.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Any
from uuid import UUID

import yaml

from ai_workshop.labs.rag.indexing.access_epoch_observations import (
    IndexObservation,
    validate_preservation,
)
from ai_workshop.labs.rag.indexing.access_epoch_tls import PreparedTlsAssets
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlSettlement,
    CutoverActionKind,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
    strict_utc,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
    CONTAINER,
    CONTEXT_ENDPOINT_DIGEST,
    DAEMON,
    DOCKER_EXE,
    NETWORK,
    ORIGINAL_IMAGE_ID,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import utc_text

PROJECT_ROOT = Path(__file__).absolute().parents[6]
_COMPOSE = PROJECT_ROOT / "infrastructure/compose"
_VOLUME = "ai-workshop_elasticsearch-data"
_NAME = "/ai-workshop-elasticsearch-1"
_PREFIX = "docker.elastic.co/elasticsearch/elasticsearch"
_PIPE = "npipe:////./pipe/dockerDesktopLinuxEngine"
_KINDS = {CutoverActionKind.START_BOOTSTRAP, CutoverActionKind.START_SECURED}
IMAGE_ENV = (
    "PATH=/usr/share/elasticsearch/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "ELASTIC_CONTAINER=true",
    "container=oci",
    "SHELL=/bin/bash",
)
_HASHES = (
    "http_ca_sha256",
    "transport_ca_sha256",
    "http_ca_der_sha256",
    "transport_ca_der_sha256",
    "http_leaf_der_sha256",
    "transport_leaf_der_sha256",
)
_SECURITY_SETTINGS: dict[str, object] = {
    "cluster.name": "${AI_WORKSHOP_ES_ORIGINAL_CLUSTER_NAME}",
    "discovery.type": "single-node",
    "network.host": "0.0.0.0",
    "http.port": 9200,
    "transport.port": 9300,
    "xpack.security.enabled": True,
    "xpack.security.autoconfiguration.enabled": False,
    "xpack.security.enrollment.enabled": False,
    "xpack.security.authc.anonymous.roles": [],
    "xpack.security.authc.realms.file.file1.order": 0,
    "xpack.security.authc.realms.file.file1.enabled": True,
    "xpack.security.authc.realms.native.native1.order": 1,
    "xpack.security.authc.realms.native.native1.enabled": True,
    "remote_cluster_server.enabled": False,
    "node.roles": [
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
for _purpose in ("http", "transport"):
    _SECURITY_SETTINGS.update(
        {
            f"xpack.security.{_purpose}.ssl.enabled": True,
            f"xpack.security.{_purpose}.ssl.verification_mode": "full",
            f"xpack.security.{_purpose}.ssl.client_authentication": "none"
            if _purpose == "http"
            else "required",
            f"xpack.security.{_purpose}.ssl.key": f"access-epoch-tls/{_purpose}/node.key",
            f"xpack.security.{_purpose}.ssl.certificate": f"access-epoch-tls/{_purpose}/node.crt",
            f"xpack.security.{_purpose}.ssl.certificate_authorities": [
                f"access-epoch-tls/{_purpose}/ca.crt"
            ],
        }
    )


def _security_config(raw: bytes) -> None:
    if type(raw) is not bytes or not 0 < len(raw) <= 16384:
        raise _denied()
    tree = yaml.compose(raw, Loader=yaml.SafeLoader)
    value = yaml.safe_load(raw)
    if (
        not isinstance(tree, yaml.MappingNode)
        or type(value) is not dict
        or len(tree.value) != len(value)
        or canonical_json(value) != canonical_json(_SECURITY_SETTINGS)
    ):
        raise _denied()


class DeploymentError(ValueError):
    """Body-free failure, never carries Docker JSON or private source paths."""


def _denied() -> DeploymentError:
    return DeploymentError("deployment_readback_denied")


def _hex(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise _denied()
        value[name] = item
    return value


def _constant(_: str) -> None:
    raise _denied()


def _json(raw: bytes) -> Any:
    if type(raw) is not bytes or not 0 < len(raw) <= 4194304:
        raise _denied()
    return json.loads(
        raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs, parse_constant=_constant
    )


def _one(raw: bytes) -> dict[str, Any]:
    value = _json(raw)
    if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
        raise _denied()
    return value[0]


def _time(value: object) -> datetime:
    if type(value) is not str:
        raise _denied()
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0):
        raise _denied()
    return parsed


def _source(actual: object, expected: str) -> bool:
    # Docker Desktop may report its exact Linux translation of this Windows path.
    path = PureWindowsPath(expected)
    translated = "/run/desktop/mnt/host/" + path.drive[0].lower() + "/" + "/".join(path.parts[1:])
    return type(actual) is str and actual in {expected, path.as_posix(), translated}


@dataclass(frozen=True, slots=True, eq=False)
class DeploymentCommand:
    action: ReservedCutoverAction
    argv: tuple[str, ...]
    environment: Mapping[str, str] = field(repr=False)
    cwd: Path


@dataclass(frozen=True, slots=True, eq=False)
class ObservedDeployment:
    action_id: UUID
    execution_id: UUID
    kind: CutoverActionKind
    container_id: str
    started_at: datetime
    manifest_json: str


@dataclass(frozen=True, slots=True, eq=False)
class PreservedDeployment:
    deployment: ObservedDeployment
    stable_node_id: str
    ephemeral_id: str
    jvm_started_at: datetime
    manifest_json: str


@dataclass(frozen=True, slots=True, eq=False)
class RetiredPredecessor:
    action: ReservedCutoverAction
    settlement: ControlSettlement
    bootstrap: ObservedDeployment | None = None


@dataclass(frozen=True, slots=True, eq=False)
class RawDeploymentReadback:
    daemon: bytes = field(repr=False)
    container: bytes = field(repr=False)
    image: bytes = field(repr=False)
    volume: bytes = field(repr=False)
    network: bytes | None = field(repr=False)
    all_container_ids: bytes = field(repr=False)
    tls_public_hashes: tuple[str, ...]
    secured_config: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class _SelectedTopology:
    manifest_digest: str
    cluster_name: str
    original_ipv4: str
    leaf_locations: tuple[str, ...] = field(repr=False)
    network: IPv4Network
    gateway: IPv4Address

    def _compose(self, kind: CutoverActionKind) -> Path:
        name = "bootstrap" if kind == CutoverActionKind.START_BOOTSTRAP else "secured"
        return _COMPOSE / f"compose.access-epoch-{name}.yaml"

    def _config(self, container: dict[str, Any], kind: CutoverActionKind) -> None:
        config, host = container["Config"], container["HostConfig"]
        expected_env = {
            *IMAGE_ENV,
            "ES_JAVA_OPTS=-Xms1g -Xmx1g",
            "AI_WORKSHOP_ES_ORIGINAL_CLUSTER_NAME=" + self.cluster_name,
        }
        env = config["Env"]
        if (
            type(env) is not list
            or len(env) != len(expected_env)
            or set(env) != expected_env
            or config["Entrypoint"] != ["/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
            or config["Cmd"] != ["eswrapper"]
            or config["User"] != "1000:0"
            or config["WorkingDir"] != "/usr/share/elasticsearch"
            or config["Image"] != f"{_PREFIX}:9.5.2@{self.manifest_digest}"
            or config["Healthcheck"] != {"Test": ["NONE"]}
            or host["RestartPolicy"] != {"Name": "no", "MaximumRetryCount": 0}
            or any(
                host[name] is not False for name in ("Privileged", "AutoRemove", "PublishAllPorts")
            )
            or host["PidMode"] != ""
            or host["IpcMode"] != "private"
            or host["UTSMode"] != ""
            or host.get("UsernsMode", "") != ""
            or any(host.get(k) not in (None, {}) for k in ("Tmpfs", "Sysctls"))
            or host.get("GroupAdd") not in (None, [])
            or any(
                host.get(k) not in (None, [])
                for k in (
                    "CapAdd",
                    "Devices",
                    "DeviceRequests",
                    "ExtraHosts",
                    "Links",
                    "VolumesFrom",
                    "SecurityOpt",
                )
            )
        ):
            raise _denied()
        labels = config["Labels"]
        expected = {
            "com.docker.compose.project": "ai-workshop",
            "com.docker.compose.service": "elasticsearch",
            "com.docker.compose.container-number": "1",
            "com.docker.compose.oneoff": "False",
            "com.docker.compose.project.config_files": str(self._compose(kind)),
            "com.docker.compose.project.working_dir": str(_COMPOSE),
            "com.docker.compose.image": ORIGINAL_IMAGE_ID,
        }
        if type(labels) is not dict or any(labels.get(k) != v for k, v in expected.items()):
            raise _denied()
        # Inert labels are not returned or hashed. Compose hash/version are metadata only.
        for key, value in labels.items():
            if (
                type(key) is not str
                or type(value) is not str
                or len(key) > 256
                or len(value) > 4096
            ):
                raise _denied()
            if key.startswith("com.docker.compose.") and key not in set(expected) | {
                "com.docker.compose.config-hash",
                "com.docker.compose.version",
                "com.docker.compose.depends_on",
            }:
                raise _denied()
        if (
            not _hex(labels.get("com.docker.compose.config-hash"))
            or re.fullmatch(
                r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?",
                labels.get("com.docker.compose.version", ""),
            )
            is None
            or labels.get("com.docker.compose.depends_on", "") != ""
            or "com.docker.compose.replace" in labels
        ):
            raise _denied()

    def _mounts(self, container: dict[str, Any]) -> None:
        mounts, requests = container["Mounts"], container["HostConfig"]["Mounts"]
        if (
            type(mounts) is not list
            or type(requests) is not list
            or len(mounts) != 8
            or len(requests) != 8
        ):
            raise _denied()
        by_target = {m["Destination"]: m for m in mounts}
        by_request = {m["Target"]: m for m in requests}
        if len(by_target) != 8 or len(by_request) != 8 or set(by_target) != set(by_request):
            raise _denied()
        data = by_target["/usr/share/elasticsearch/data"]
        request = by_request["/usr/share/elasticsearch/data"]
        if (
            data["Type"] != "volume"
            or data["Name"] != _VOLUME
            or data["Driver"] != "local"
            or data["Source"] != f"/var/lib/docker/volumes/{_VOLUME}/_data"
            or data["RW"] is not True
            or request["Type"] != "volume"
            or request["Source"] != _VOLUME
            or request.get("ReadOnly", False) is not False
            or request.get("VolumeOptions") != {"NoCopy": True}
        ):
            raise _denied()
        pairs = [
            (
                str(PROJECT_ROOT / "infrastructure/elasticsearch/elasticsearch-secured.yml"),
                "/usr/share/elasticsearch/config/elasticsearch.yml",
            )
        ]
        pairs += [
            (p, "/usr/share/elasticsearch/config/access-epoch-tls/" + "/".join(Path(p).parts[-2:]))
            for p in self.leaf_locations
        ]
        for source, target in pairs:
            actual, request = by_target[target], by_request[target]
            if (
                actual["Type"] != "bind"
                or actual["RW"] is not False
                or actual.get("Propagation") != "rprivate"
                or not _source(actual["Source"], source)
                or request["Type"] != "bind"
                or not _source(request["Source"], source)
                or request["ReadOnly"] is not True
                or request.get("BindOptions", {}).get("CreateMountpoint", False) is not False
            ):
                raise _denied()

    def _network(
        self, container: dict[str, Any], kind: CutoverActionKind, raw: bytes | None
    ) -> None:
        host, settings = container["HostConfig"], container["NetworkSettings"]
        if kind == CutoverActionKind.START_BOOTSTRAP:
            if (
                host["NetworkMode"] != "none"
                or host["PortBindings"] not in (None, {})
                or raw is not None
            ):
                raise _denied()
            networks = settings["Networks"]
            if (
                type(networks) is not dict
                or set(networks) not in (set(), {"none"})
                or any((settings["Ports"] or {}).values())
            ):
                raise _denied()
            if networks:
                endpoint = networks["none"]
                if (
                    type(endpoint) is not dict
                    or any(
                        endpoint.get(k, "") != ""
                        for k in ("IPAddress", "Gateway", "GlobalIPv6Address", "IPv6Gateway")
                    )
                    or any(
                        type(endpoint.get(k, 0)) is not int or endpoint.get(k, 0) != 0
                        for k in ("IPPrefixLen", "GlobalIPv6PrefixLen")
                    )
                ):
                    raise _denied()
            return
        ports = {"9200/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9200"}]}
        active_ports = {k: v for k, v in settings["Ports"].items() if v}
        if (
            host["NetworkMode"] != "ai-workshop_default"
            or host["PortBindings"] != ports
            or active_ports != ports
            or set(settings["Networks"]) != {"ai-workshop_default"}
            or raw is None
        ):
            raise _denied()
        attached = settings["Networks"]["ai-workshop_default"]
        if (
            attached["NetworkID"] != NETWORK
            or attached["IPAddress"] != self.original_ipv4
            or attached["IPPrefixLen"] != self.network.prefixlen
            or attached["Gateway"] != str(self.gateway)
            or attached.get("GlobalIPv6Address", "") != ""
        ):
            raise _denied()
        network = _one(raw)
        if (
            network["Id"] != NETWORK
            or network["Name"] != "ai-workshop_default"
            or network["Driver"] != "bridge"
            or network["Scope"] != "local"
            or network["Internal"] is not False
            or network["EnableIPv6"] is not False
            or network["IPAM"]["Driver"] != "default"
            or network["IPAM"]["Config"]
            != [{"Subnet": str(self.network), "Gateway": str(self.gateway)}]
        ):
            raise _denied()
        address = self.original_ipv4 + "/" + str(self.network.prefixlen)
        matches = [
            key for key, val in network["Containers"].items() if val.get("IPv4Address") == address
        ]
        if matches != [container["Id"]]:
            raise _denied()


@dataclass(frozen=True, slots=True)
class RuntimeDeployment:
    epoch_id: UUID
    execution_id: UUID
    container_id: str
    cluster_name: str
    started_at: datetime


def verify_runtime_deployment(
    manifest_json: str,
    *,
    daemon: bytes,
    container: bytes,
    network: bytes,
    secured_config: bytes,
    tls_public_hashes: tuple[str, ...],
) -> RuntimeDeployment:
    """Pure selected-field check of current raw readbacks, never a launch capability."""
    try:
        value = _json(manifest_json.encode())
        if type(value) is not dict or set(value) != {
            "schema_version",
            "epoch_id",
            "action_id",
            "execution_id",
            "kind",
            "cluster_name",
            "original_ipv4",
            "network_id",
            "network_subnet",
            "network_gateway",
            "container_id",
            "image_id",
            "manifest_digest",
            "daemon_id",
            "volume_name",
            "docker_started_at",
            "created_at",
            "observed_at",
            "network_mode",
            "tls_public_hashes",
            "public_security_profile",
        }:
            raise _denied()
        epoch_id, execution_id = UUID(value["epoch_id"]), UUID(value["execution_id"])
        for key in ("epoch_id", "action_id", "execution_id"):
            if str(UUID(value[key])) != value[key]:
                raise _denied()
        subnet, gateway = (
            IPv4Network(value["network_subnet"], strict=True),
            IPv4Address(value["network_gateway"]),
        )
        address = IPv4Address(value["original_ipv4"])
        created, started, observed = (
            _time(value[k]) for k in ("created_at", "docker_started_at", "observed_at")
        )
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != 2
            or value["kind"] != CutoverActionKind.START_SECURED.value
            or value["image_id"] != ORIGINAL_IMAGE_ID
            or value["daemon_id"] != DAEMON
            or value["network_id"] != NETWORK
            or value["volume_name"] != _VOLUME
            or value["network_mode"] != "original_bridge"
            or value["public_security_profile"] != "project_http_tls_transport_mtls"
            or not _hex(value["container_id"])
            or value["container_id"] == CONTAINER
            or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value["cluster_name"]) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", value["manifest_digest"]) is None
            or value["manifest_digest"] == ORIGINAL_IMAGE_ID
            or str(address) != value["original_ipv4"]
            or str(subnet) != value["network_subnet"]
            or str(gateway) != value["network_gateway"]
            or address not in subnet
            or gateway not in subnet
            or address in {subnet.network_address, subnet.broadcast_address, gateway}
            or address.is_loopback
            or address.is_multicast
            or address.is_unspecified
            or not created <= started <= observed
            or len(tls_public_hashes) != len(_HASHES)
            or any(not _hex(x) for x in tls_public_hashes)
            or value["tls_public_hashes"] != dict(zip(_HASHES, tls_public_hashes, strict=True))
        ):
            raise _denied()
        directory = PROJECT_ROOT / ".local-data/access-epoch/private/tls" / str(epoch_id) / "bind"
        selected = _SelectedTopology(
            value["manifest_digest"],
            value["cluster_name"],
            str(address),
            tuple(
                str(directory / purpose / name)
                for purpose in ("http", "transport")
                for name in ("node.key", "node.crt", "ca.crt")
            ),
            subnet,
            gateway,
        )
        raw, current = _one(container), _json(daemon)
        state = raw["State"]
        if (
            current["ID"] != DAEMON
            or current["OSType"] != "linux"
            or raw["Id"] != value["container_id"]
            or raw["Name"] != _NAME
            or raw["Image"] != ORIGINAL_IMAGE_ID
            or state["StartedAt"] != value["docker_started_at"]
            or _time(raw["Created"]) != created
            or state["Running"] is not True
            or state["Status"] != "running"
            or type(state["Pid"]) is not int
            or state["Pid"] <= 0
            or any(state[k] is not False for k in ("Restarting", "Dead", "Paused"))
        ):
            raise _denied()
        _security_config(secured_config)
        selected._config(raw, CutoverActionKind.START_SECURED)
        selected._mounts(raw)
        selected._network(raw, CutoverActionKind.START_SECURED, network)
        return RuntimeDeployment(
            epoch_id, execution_id, value["container_id"], value["cluster_name"], started
        )
    except Exception:
        raise _denied() from None


class DeploymentCommands:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        tls: PreparedTlsAssets,
        manifest_digest: str,
        cluster_name: str,
        network_subnet: str,
        network_gateway: str,
        indices: tuple[IndexObservation, ...],
    ) -> None:
        try:
            self.epoch, self.tls = epoch, tls
            self.execution_id = UUID(epoch.binding.execution_id)
            self.manifest_digest, self.cluster_name = manifest_digest, cluster_name
            self.network = IPv4Network(network_subnet, strict=True)
            self.gateway = IPv4Address(network_gateway)
            address = IPv4Address(tls.original_ipv4)
            directory = (
                PROJECT_ROOT / ".local-data/access-epoch/private/tls" / str(tls.epoch_id) / "bind"
            )
            expected_files = tuple(
                str(directory / purpose / name)
                for purpose in ("http", "transport")
                for name in ("node.key", "node.crt", "ca.crt")
            )
            manifest = _json(tls.manifest_json.encode())
            if (
                type(tls) is not PreparedTlsAssets
                or str(tls.epoch_id) != epoch.binding.access_epoch_id
                or tls.bind_directory != str(directory)
                or tls.leaf_locations != expected_files
                or manifest.get("epoch_id") != str(tls.epoch_id)
                or manifest.get("original_ipv4") != tls.original_ipv4
                or any(not _hex(manifest.get(k)) for k in _HASHES)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_digest) is None
                or manifest_digest == ORIGINAL_IMAGE_ID
                or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", cluster_name) is None
                or str(address) != tls.original_ipv4
                or address not in self.network
                or address
                in {self.network.network_address, self.network.broadcast_address, self.gateway}
                or self.gateway not in self.network
                or str(self.gateway) != network_gateway
                or address.is_loopback
                or address.is_multicast
                or address.is_unspecified
                or epoch.original.container_id != CONTAINER
                or epoch.original.daemon_sha256
                != sha256(
                    canonical_json(
                        {"id": DAEMON, "os": "linux", "endpoint_sha256": CONTEXT_ENDPOINT_DIGEST}
                    ).encode()
                ).hexdigest()
            ):
                raise _denied()
            validate_preservation(indices, indices)
            self._topology = _SelectedTopology(
                manifest_digest,
                cluster_name,
                tls.original_ipv4,
                tls.leaf_locations,
                self.network,
                self.gateway,
            )
            self.indices = indices
            self.tls_hashes = tuple(manifest[k] for k in _HASHES)
            self._built: set[CutoverActionKind] = set()
            self._actions: set[UUID] = set()
            self._commands: set[DeploymentCommand] = set()
            self._observed: set[ObservedDeployment] = set()
            self._preserved: dict[ObservedDeployment, PreservedDeployment] = {}
            self._predecessors: dict[ObservedDeployment, ObservedDeployment] = {}
        except Exception:
            raise _denied() from None

    def target_sha256(self, kind: CutoverActionKind) -> str:
        if type(kind) is not CutoverActionKind or kind not in _KINDS:
            raise _denied()
        return sha256(
            canonical_json(
                {
                    "kind": kind.value,
                    "execution_id": str(self.execution_id),
                    "epoch_id": self.epoch.binding.access_epoch_id,
                    "original_image_id": ORIGINAL_IMAGE_ID,
                    "manifest_digest": self.manifest_digest,
                    "original_volume": _VOLUME,
                    "cluster_name": self.cluster_name,
                    "original_ipv4": self.tls.original_ipv4,
                    "original_network_id": NETWORK,
                    "network_subnet": str(self.network),
                    "network_gateway": str(self.gateway),
                    "original_volume_sha256": self.epoch.original.volume_sha256,
                    "original_image_sha256": self.epoch.original.image_sha256,
                    "tls_public_hashes": list(self.tls_hashes),
                }
            ).encode()
        ).hexdigest()

    def _action(self, action: ReservedCutoverAction) -> None:
        if (
            type(action) is not ReservedCutoverAction
            or action.kind not in _KINDS
            or action.execution_id != self.execution_id
            or type(action.action_id) is not UUID
            or type(action.sequence) is not int
            or action.sequence <= 0
            or action.expected.preceding_sequence != action.sequence - 1
            or str(UUID(action.executor_generation)) != action.executor_generation
            or _json(action.expected.identity_json.encode()).get("target_sha256")
            != self.target_sha256(action.kind)
        ):
            raise _denied()

    @staticmethod
    def _daemon(raw: bytes) -> None:
        value = _json(raw)
        if value.get("ID") != DAEMON or value.get("OSType") != "linux":
            raise _denied()

    def build(
        self,
        action: ReservedCutoverAction,
        retired: RetiredPredecessor,
        daemon: bytes,
        inventory: bytes,
    ) -> DeploymentCommand:
        try:
            self._action(action)
            if action.kind in self._built or action.action_id in self._actions:
                raise _denied()
            self._built.add(action.kind)
            self._actions.add(action.action_id)  # Consume before uncertain validation/submission.
            self._daemon(daemon)
            bootstrap = retired.bootstrap
            old_kind = CutoverActionKind.RETIRE_OLD
            old_id = CONTAINER
            if action.kind == CutoverActionKind.START_SECURED:
                if (
                    bootstrap not in self._observed
                    or bootstrap.kind != CutoverActionKind.START_BOOTSTRAP
                ):
                    raise _denied()
                old_kind, old_id = CutoverActionKind.RETIRE_BOOTSTRAP, bootstrap.container_id
            elif bootstrap is not None:
                raise _denied()
            old, settled = retired.action, retired.settlement
            manifest = _json(settled.manifest_json.encode())
            if (
                old.kind != old_kind
                or old.execution_id != action.execution_id
                or old.executor_generation != action.executor_generation
                or old.sequence >= action.sequence
                or settled.action_id != old.action_id
                or settled.execution_id != action.execution_id
                or settled.executor_generation != action.executor_generation
                or settled.outcome != "settled"
                or manifest.get("container_id") != old_id
                or manifest.get("daemon_sha256") != self.epoch.original.daemon_sha256
                or manifest.get("action_id") != str(old.action_id)
                or manifest.get("sequence") != old.sequence
                or manifest.get("method") != "exact_synchronous_command_and_terminal_readback"
                or strict_utc(manifest.get("retired_at")) != settled.observed_at
            ):
                raise _denied()
            if type(inventory) is not bytes or len(inventory) > 4194304:
                raise _denied()
            seen = set()
            for line in inventory.splitlines():
                row = _json(line)
                identity = row.get("ID")
                if not _hex(identity) or identity in seen or identity in {CONTAINER, old_id}:
                    raise _denied()
                seen.add(identity)
                labels = row.get("Labels")
                if type(labels) is not str or type(row.get("Names")) is not str:
                    raise _denied()
                if row["Names"].lstrip("/") == _NAME[1:] or (
                    "com.docker.compose.project=ai-workshop" in labels.split(",")
                    and "com.docker.compose.service=elasticsearch" in labels.split(",")
                ):
                    raise _denied()
            environment = {
                "COMPOSE_DISABLE_ENV_FILE": "true",
                "AI_WORKSHOP_ES_ORIGINAL_MANIFEST_DIGEST": self.manifest_digest,
                "AI_WORKSHOP_ES_ORIGINAL_VOLUME": _VOLUME,
                "AI_WORKSHOP_ES_TLS_DIRECTORY": self.tls.bind_directory,
                "AI_WORKSHOP_ES_ORIGINAL_CLUSTER_NAME": self.cluster_name,
            }
            if action.kind == CutoverActionKind.START_SECURED:
                environment["AI_WORKSHOP_ES_ORIGINAL_IPV4"] = self.tls.original_ipv4
            if sum(len(k) + len(v) for k, v in environment.items()) > 8192:
                raise _denied()
            command = DeploymentCommand(
                action,
                (
                    DOCKER_EXE,
                    "--host",
                    _PIPE,
                    "compose",
                    "--project-name",
                    "ai-workshop",
                    "--project-directory",
                    str(_COMPOSE),
                    "--file",
                    str(self._topology._compose(action.kind)),
                    "up",
                    "--detach",
                    "--no-deps",
                    "--no-build",
                    "--no-recreate",
                    "--pull",
                    "never",
                    "elasticsearch",
                ),
                MappingProxyType(environment),
                _COMPOSE,
            )
            self._commands.add(command)
            return command
        except Exception:
            raise _denied() from None

    def assert_issued(self, command: DeploymentCommand) -> None:
        """Identity membership only; current DB/owner and one-time execution are runner duties."""
        try:
            if type(command) is not DeploymentCommand or command not in self._commands:
                raise _denied()
            self._action(command.action)
            if (
                command.action.action_id not in self._actions
                or command.action.kind not in self._built
            ):
                raise _denied()
        except Exception:
            raise _denied() from None

    def assert_observed(self, value: ObservedDeployment) -> None:
        """Check reader origin only; current ownership and settlement are runner duties."""
        if (
            type(value) is not ObservedDeployment
            or value not in self._observed
            or value.execution_id != self.execution_id
            or value.kind not in _KINDS
        ):
            raise _denied()

    def decode_daemon(
        self,
        action: ReservedCutoverAction,
        readback: RawDeploymentReadback,
        *,
        predecessor: ObservedDeployment | None = None,
        observed_at: datetime,
    ) -> ObservedDeployment:
        try:
            self._action(action)
            self._daemon(readback.daemon)
            if type(observed_at) is not datetime or observed_at.utcoffset() != timedelta(0):
                raise _denied()
            old_ids = {CONTAINER}
            if action.kind == CutoverActionKind.START_SECURED:
                if (
                    predecessor not in self._observed
                    or predecessor.kind != CutoverActionKind.START_BOOTSTRAP
                ):
                    raise _denied()
                old_ids.add(predecessor.container_id)
            elif predecessor is not None:
                raise _denied()
            container, image, volume = (
                _one(readback.container),
                _one(readback.image),
                _one(readback.volume),
            )
            _security_config(readback.secured_config)
            identity, state = container["Id"], container["State"]
            if (
                type(readback.all_container_ids) is not bytes
                or len(readback.all_container_ids) > 4194304
            ):
                raise _denied()
            ids = readback.all_container_ids.decode("ascii").splitlines()
            if (
                not _hex(identity)
                or identity in old_ids
                or container["Name"] != _NAME
                or container["Image"] != ORIGINAL_IMAGE_ID
                or image["Id"] != ORIGINAL_IMAGE_ID
                or image["RepoDigests"] != [f"{_PREFIX}@{self.manifest_digest}"]
                or len(ids) != len(set(ids))
                or any(not _hex(x) for x in ids)
                or identity not in ids
                or old_ids.intersection(ids)
                or state["Running"] is not True
                or any(state[k] is not False for k in ("Restarting", "Dead", "Paused"))
                or state["Status"] != "running"
                or type(state["Pid"]) is not int
                or state["Pid"] <= 0
                or readback.tls_public_hashes != self.tls_hashes
                or volume["Name"] != _VOLUME
                or volume["Driver"] != "local"
                or volume["Scope"] != "local"
                or volume["Mountpoint"] != f"/var/lib/docker/volumes/{_VOLUME}/_data"
                or volume["Options"] is not None
                or image["Os"] != "linux"
                or type(image["Architecture"]) is not str
                or re.fullmatch(r"[a-z0-9_]{1,32}", image["Architecture"]) is None
            ):
                raise _denied()
            volume_public = {
                "name": volume["Name"],
                "driver": volume["Driver"],
                "scope": volume["Scope"],
                "created_at": volume["CreatedAt"],
                "mountpoint": volume["Mountpoint"],
                "options": None,
                "daemon_sha256": self.epoch.original.daemon_sha256,
            }
            image_public = {
                "image_id": image["Id"],
                "manifest_digest": self.manifest_digest,
                "architecture": image["Architecture"],
            }
            if (
                sha256(canonical_json(volume_public).encode()).hexdigest()
                != self.epoch.original.volume_sha256
                or sha256(canonical_json(image_public).encode()).hexdigest()
                != self.epoch.original.image_sha256
            ):
                raise _denied()
            created, started = _time(container["Created"]), _time(state["StartedAt"])
            if not self.epoch.original.jvm_start_at < created <= started <= observed_at:
                raise _denied()
            self._topology._config(container, action.kind)
            self._topology._mounts(container)
            self._topology._network(container, action.kind, readback.network)
            public = {
                "schema_version": 2,
                "epoch_id": self.epoch.binding.access_epoch_id,
                "cluster_name": self.cluster_name,
                "original_ipv4": self.tls.original_ipv4,
                "network_subnet": str(self.network),
                "network_gateway": str(self.gateway),
                "network_id": NETWORK,
                "action_id": str(action.action_id),
                "execution_id": str(action.execution_id),
                "kind": action.kind.value,
                "container_id": identity,
                "image_id": ORIGINAL_IMAGE_ID,
                "manifest_digest": self.manifest_digest,
                "daemon_id": DAEMON,
                "volume_name": _VOLUME,
                "docker_started_at": state["StartedAt"],
                "created_at": utc_text(created),
                "observed_at": utc_text(observed_at),
                "network_mode": "none"
                if action.kind == CutoverActionKind.START_BOOTSTRAP
                else "original_bridge",
                "tls_public_hashes": dict(zip(_HASHES, self.tls_hashes, strict=True)),
                "public_security_profile": "project_http_tls_transport_mtls",
            }
            result = ObservedDeployment(
                action.action_id,
                action.execution_id,
                action.kind,
                identity,
                started,
                canonical_json(public),
            )
            self._observed.add(result)
            if predecessor is not None:
                self._predecessors[result] = predecessor
            return result
        except Exception:
            raise _denied() from None

    def decode_preservation(
        self,
        deployment: ObservedDeployment,
        cluster: bytes,
        cluster_state: bytes,
        nodes: bytes,
        indices: tuple[IndexObservation, ...],
        *,
        observed_at: datetime,
    ) -> PreservedDeployment:
        try:
            if (
                deployment not in self._observed
                or type(observed_at) is not datetime
                or observed_at.utcoffset() != timedelta(0)
            ):
                raise _denied()
            root, state, status = _json(cluster), _json(cluster_state), _json(nodes)
            if (
                root["cluster_uuid"] != self.epoch.original.cluster_uuid
                or root["cluster_name"] != self.cluster_name
                or root["version"]["number"] != "9.5.2"
                or status["cluster_name"] != self.cluster_name
                or status["_nodes"] != {"total": 1, "successful": 1, "failed": 0}
                or type(status["_nodes"]) is not dict
                or set(status["_nodes"]) != {"total", "successful", "failed"}
                or any(type(value) is not int for value in status["_nodes"].values())
                or set(status["nodes"]) != {self.epoch.original.stable_node_id}
                or state["cluster_uuid"] != self.epoch.original.cluster_uuid
                or state["master_node"] != self.epoch.original.stable_node_id
                or set(state["nodes"]) != {self.epoch.original.stable_node_id}
            ):
                raise _denied()
            node = status["nodes"][self.epoch.original.stable_node_id]
            ephemeral = state["nodes"][self.epoch.original.stable_node_id]["ephemeral_id"]
            milliseconds = node["jvm"]["start_time_in_millis"]
            if (
                type(ephemeral) is not str
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", ephemeral)
                or ephemeral == self.epoch.original.ephemeral_id
                or type(milliseconds) is not int
            ):
                raise _denied()
            started = datetime.fromtimestamp(milliseconds // 1000, UTC) + timedelta(
                milliseconds=milliseconds % 1000
            )
            if (
                not deployment.started_at <= started <= observed_at
                or observed_at.utcoffset() != timedelta(0)
            ):
                raise _denied()
            if deployment.kind == CutoverActionKind.START_SECURED:
                previous = self._preserved.get(self._predecessors[deployment])
                if (
                    previous is None
                    or previous.ephemeral_id == ephemeral
                    or started <= previous.jvm_started_at
                ):
                    raise _denied()
            validate_preservation(self.indices, indices)
            validate_preservation(indices, indices)
            public = {
                "container_id": deployment.container_id,
                "cluster_uuid": root["cluster_uuid"],
                "stable_node_id": self.epoch.original.stable_node_id,
                "ephemeral_id": ephemeral,
                "jvm_started_at": utc_text(started),
                "index_count": len(indices),
                "preserved_indices": [
                    {
                        "name": x.name,
                        "uuid": x.uuid,
                        "count": x.count,
                        "settings_sha256": x.settings_sha256,
                        "provenance_sha256": x.provenance_sha256,
                    }
                    for x in indices
                ],
            }
            result = PreservedDeployment(
                deployment,
                self.epoch.original.stable_node_id,
                ephemeral,
                started,
                canonical_json(public),
            )
            self._preserved[deployment] = result
            return result
        except Exception:
            raise _denied() from None
