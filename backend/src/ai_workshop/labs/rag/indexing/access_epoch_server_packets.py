"""Pure selected server facts, without source authority or raw settings exposure.

Expected values must come from the caller's guarded phase/material. These three
packets do not replace TLS validation, the fixed secured YAML, full preservation
or the complete cutover route matrix.
"""

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from typing import Any, cast

from ai_workshop.labs.rag.indexing.access_epoch_types import canonical_json
from ai_workshop.labs.rag.indexing.alias_recovery_types import utc_text

_LIMIT = 2 * 1024 * 1024
_ROLES = {
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
}
_REQUIRED = {
    "xpack.security.enabled": "true",
    "xpack.security.http.ssl.enabled": "true",
    "xpack.security.transport.ssl.enabled": "true",
    "xpack.security.transport.ssl.client_authentication": "required",
    "remote_cluster_server.enabled": "false",
}


def _denied() -> ValueError:
    return ValueError("secured_server_packet_denied")


@dataclass(frozen=True, slots=True)
class ServerReadExpectation:
    version: str
    cluster_uuid: str
    cluster_name: str
    stable_node_id: str
    ephemeral_id: str
    jvm_start_at: datetime
    container_started_at: datetime
    original_ipv4: str


def _object(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise _denied()
    return cast(dict[str, Any], value)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _denied()
        value[key] = item
    return value


def _constant(value: str) -> None:
    raise _denied()


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise _denied()
    return result


def _json(body: bytes) -> dict[str, Any]:
    if type(body) is not bytes or not 0 < len(body) <= _LIMIT:
        raise _denied()
    return _object(
        json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs,
            parse_constant=_constant,
            parse_float=_float,
        )
    )


def _expected(value: ServerReadExpectation, sampled_at: datetime) -> None:
    if type(value) is not ServerReadExpectation:
        raise _denied()
    for name in ("cluster_uuid", "cluster_name", "stable_node_id", "ephemeral_id"):
        text = getattr(value, name)
        if type(text) is not str or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", text) is None:
            raise _denied()
    if (
        type(value.version) is not str
        or re.fullmatch(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", value.version) is None
    ):
        raise _denied()
    if type(value.original_ipv4) is not str:
        raise _denied()
    address = IPv4Address(value.original_ipv4)
    if (
        str(address) != value.original_ipv4
        or address.is_loopback
        or address.is_multicast
        or address.is_link_local
        or address.is_unspecified
        or address.is_reserved
    ):
        raise _denied()
    if (
        any(
            type(at) is not datetime or at.tzinfo is not UTC
            for at in (
                value.jvm_start_at,
                value.container_started_at,
                sampled_at,
            )
        )
        or not value.container_started_at <= value.jvm_start_at <= sampled_at
    ):
        raise _denied()


def validate_server_packets(
    expected: ServerReadExpectation,
    *,
    info: bytes,
    state: bytes,
    nodes: bytes,
    sampled_at: datetime,
) -> str:
    """Return a closed public projection; decoding never issues observed evidence."""
    try:
        _expected(expected, sampled_at)
        cluster, current, details = _json(info), _json(state), _json(nodes)
        counts = _object(details["_nodes"])
        members, state_members = _object(details["nodes"]), _object(current["nodes"])
        if (
            cluster["cluster_uuid"] != expected.cluster_uuid
            or cluster["cluster_name"] != expected.cluster_name
            or _object(cluster["version"])["number"] != expected.version
            or details["cluster_name"] != expected.cluster_name
            or current["cluster_uuid"] != expected.cluster_uuid
            or current["master_node"] != expected.stable_node_id
            or set(members) != {expected.stable_node_id}
            or set(state_members) != {expected.stable_node_id}
            or set(counts) != {"total", "successful", "failed"}
            or any(
                type(counts[key]) is not int or counts[key] != value
                for key, value in (
                    ("total", 1),
                    ("successful", 1),
                    ("failed", 0),
                )
            )
        ):
            raise _denied()
        node = _object(members[expected.stable_node_id])
        state_node = _object(state_members[expected.stable_node_id])
        millis = _object(node["jvm"])["start_time_in_millis"]
        if (
            state_node["ephemeral_id"] != expected.ephemeral_id
            or type(millis) is not int
            or not 0 < millis <= 253402300799999
            or datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=millis)
            != expected.jvm_start_at
        ):
            raise _denied()
        settings, http, transport = (
            _object(node[key]) for key in ("settings", "http", "transport")
        )
        roles = node["roles"]
        if (
            type(roles) is not list
            or any(type(role) is not str for role in roles)
            or len(roles) != len(set(roles))
            or set(roles) != _ROLES
            or "remote_cluster_server" in node
            or type(transport.get("profiles")) is not dict
            or transport["profiles"] != {}
            or any(key.startswith(("http.profiles.", "transport.profiles.")) for key in settings)
            or any(settings.get(key) != value for key, value in _REQUIRED.items())
        ):
            raise _denied()
        if (
            "xpack.security.authc.anonymous.roles" in settings
            and settings["xpack.security.authc.anonymous.roles"] != []
        ):
            raise _denied()
        for layer in ("http", "transport"):
            key = f"xpack.security.{layer}.ssl.verification_mode"
            if key in settings and settings[key] != "full":
                raise _denied()
        for listener, port in ((http, 9200), (transport, 9300)):
            addresses = listener.get("bound_address")
            if (
                type(addresses) is not list
                or not addresses
                or any(type(address) is not str for address in addresses)
                or len(addresses) != len(set(addresses))
                or not set(addresses) <= {f"0.0.0.0:{port}", f"[::]:{port}"}
                or listener.get("publish_address")
                not in {
                    f"{expected.original_ipv4}:{port}",
                    f"elasticsearch/{expected.original_ipv4}:{port}",
                }
            ):
                raise _denied()
        return canonical_json(
            {
                "schema_version": 1,
                "cluster_uuid": expected.cluster_uuid,
                "cluster_name": expected.cluster_name,
                "stable_node_id": expected.stable_node_id,
                "ephemeral_id": expected.ephemeral_id,
                "jvm_start_at": utc_text(expected.jvm_start_at),
                "version": expected.version,
                "original_ipv4": expected.original_ipv4,
                "listener_profile": "single_secure_listener_profile",
            }
        )
    except Exception:
        raise _denied() from None
