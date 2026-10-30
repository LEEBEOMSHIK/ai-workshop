"""Synthetic server bytes only: no TLS, file, native, DB or network execution."""

import importlib
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

NODE = "synthetic-stable-node"
IP = "172.28.0.2"
START = datetime(2026, 10, 21, 0, 0, 1, tzinfo=UTC)
SAMPLED = START + timedelta(seconds=2)
MAX_BYTES = 2 * 1024 * 1024
ROLES = [
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
]
REQUIRED = {
    "xpack.security.enabled": "true",
    "xpack.security.http.ssl.enabled": "true",
    "xpack.security.transport.ssl.enabled": "true",
    "xpack.security.transport.ssl.client_authentication": "required",
    "remote_cluster_server.enabled": "false",
}


def module():
    name = "ai_workshop.labs.rag.indexing.access_epoch_server_packets"
    assert importlib.util.find_spec(name) is not None, "phase-neutral server packet decoder missing"
    return importlib.import_module(name)


def expected_values():
    return {
        "version": "9.5.2",
        "cluster_uuid": "synthetic-cluster-id",
        "cluster_name": "synthetic-cluster",
        "stable_node_id": NODE,
        "ephemeral_id": "synthetic-ephemeral",
        "jvm_start_at": START,
        "container_started_at": START - timedelta(seconds=1),
        "original_ipv4": IP,
    }


def packets():
    # Independent, finite server fixture; no product decoder builds the oracle.
    return {
        "info": {
            "name": "synthetic-node-name",
            "cluster_uuid": "synthetic-cluster-id",
            "cluster_name": "synthetic-cluster",
            "version": {"number": "9.5.2"},
        },
        "state": {
            "cluster_uuid": "synthetic-cluster-id",
            "master_node": NODE,
            "nodes": {NODE: {"ephemeral_id": "synthetic-ephemeral"}},
        },
        "nodes": {
            "_nodes": {"total": 1, "successful": 1, "failed": 0},
            "cluster_name": "synthetic-cluster",
            "nodes": {
                NODE: {
                    "jvm": {"start_time_in_millis": int(START.timestamp()) * 1000},
                    "roles": list(ROLES),
                    "settings": dict(REQUIRED),
                    "http": {
                        "bound_address": ["0.0.0.0:9200", "[::]:9200"],
                        "publish_address": IP + ":9200",
                    },
                    "transport": {
                        "bound_address": ["0.0.0.0:9300"],
                        "publish_address": "elasticsearch/" + IP + ":9300",
                        "profiles": {},
                    },
                },
            },
        },
    }


def encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def public_value():
    return {
        "schema_version": 1,
        "cluster_uuid": "synthetic-cluster-id",
        "cluster_name": "synthetic-cluster",
        "stable_node_id": NODE,
        "ephemeral_id": "synthetic-ephemeral",
        "jvm_start_at": "2026-10-21T00:00:01.000000+00:00",
        "version": "9.5.2",
        "original_ipv4": IP,
        "listener_profile": "single_secure_listener_profile",
    }


def validate(m, data, *, expected=None, sampled_at=SAMPLED):
    expected = m.ServerReadExpectation(**expected_values()) if expected is None else expected
    return m.validate_server_packets(
        expected, **{key: encode(value) for key, value in data.items()}, sampled_at=sampled_at
    )


def test_closed_canonical_public_projection_without_issuer_or_private_fields():
    m = module()
    data = packets()
    node = data["nodes"]["nodes"][NODE]
    node["settings"]["node.attr.synthetic_private"] = "private-response-sentinel"
    node["private_extension"] = {"value": "private-response-sentinel"}
    before = deepcopy(data)
    actual = validate(m, data)
    assert type(actual) is str
    assert actual == encode(public_value()).decode()
    assert data == before
    assert "private-response-sentinel" not in actual
    assert not ({"source_binding", "authority", "settings", "nodes"} & json.loads(actual).keys())


@pytest.mark.parametrize("variant", ["ipv4", "ipv6", "both", "hostname", "roles_order", "explicit"])
def test_valid_listener_variants_and_explicit_safe_settings(variant):
    m = module()
    data = packets()
    node = data["nodes"]["nodes"][NODE]
    for key, port in (("http", 9200), ("transport", 9300)):
        if variant in {"ipv4", "ipv6", "both"}:
            addresses = [f"0.0.0.0:{port}", f"[::]:{port}"]
            node[key]["bound_address"] = (
                addresses if variant == "both" else [addresses[variant == "ipv6"]]
            )
        if variant == "hostname":
            node[key]["publish_address"] = f"elasticsearch/{IP}:{port}"
    if variant == "roles_order":
        node["roles"].reverse()
    if variant == "explicit":
        node["settings"].update(
            {
                "xpack.security.authc.anonymous.roles": [],
                "xpack.security.http.ssl.verification_mode": "full",
                "xpack.security.transport.ssl.verification_mode": "full",
            }
        )
    assert validate(m, data) == encode(public_value()).decode()


@pytest.mark.parametrize(
    "change",
    [
        "info_version",
        "info_cluster",
        "info_name",
        "nodes_name",
        "state_cluster",
        "master",
        "stable",
        "state_extra",
        "nodes_extra",
        "ephemeral",
        "counts_missing",
        "counts_extra",
        "count_bool",
        "count_float",
        "count_text",
        "count_failed",
        "jvm_bool",
        "jvm_float",
        "jvm_text",
        "jvm_zero",
        "jvm_overflow",
        "jvm_changed",
        "role_missing",
        "role_duplicate",
        "role_remote",
        "role_type",
        "remote_field",
        "profiles_missing",
        "profiles_extra",
        "http_profile",
        "transport_profile",
    ],
)
def test_server_identity_topology_and_single_listener_fail_closed(change):
    m = module()
    data = packets()
    node = data["nodes"]["nodes"][NODE]
    if change in {"info_version", "info_cluster", "info_name", "nodes_name", "state_cluster"}:
        target, key = {
            "info_version": (data["info"]["version"], "number"),
            "info_cluster": (data["info"], "cluster_uuid"),
            "info_name": (data["info"], "cluster_name"),
            "nodes_name": (data["nodes"], "cluster_name"),
            "state_cluster": (data["state"], "cluster_uuid"),
        }[change]
        target[key] = "other"
    elif change == "master":
        data["state"]["master_node"] = "other"
    elif change == "stable":
        data["nodes"]["nodes"] = {"other": node}
    elif change in {"state_extra", "nodes_extra"}:
        data[change.split("_")[0]]["nodes"]["extra"] = {}
    elif change == "ephemeral":
        data["state"]["nodes"][NODE]["ephemeral_id"] = "other"
    elif change == "counts_missing":
        del data["nodes"]["_nodes"]["failed"]
    elif change == "counts_extra":
        data["nodes"]["_nodes"]["extra"] = 0
    elif change.startswith("count_"):
        name = "failed" if change == "count_failed" else "total"
        data["nodes"]["_nodes"][name] = {
            "count_bool": True,
            "count_float": 1.0,
            "count_text": "1",
            "count_failed": 1,
        }[change]
    elif change.startswith("jvm_"):
        node["jvm"]["start_time_in_millis"] = {
            "jvm_bool": True,
            "jvm_float": float(int(START.timestamp()) * 1000),
            "jvm_text": str(int(START.timestamp()) * 1000),
            "jvm_zero": 0,
            "jvm_overflow": 253402300800000,
            "jvm_changed": int(START.timestamp()) * 1000 + 1,
        }[change]
    elif change == "role_missing":
        node["roles"].remove("master")
    elif change == "role_duplicate":
        node["roles"].append("master")
    elif change == "role_remote":
        node["roles"].append("remote_cluster_client")
    elif change == "role_type":
        node["roles"][0] = True
    elif change == "remote_field":
        node["remote_cluster_server"] = {}
    elif change == "profiles_missing":
        del node["transport"]["profiles"]
    elif change == "profiles_extra":
        node["transport"]["profiles"] = {"secondary": {}}
    else:
        node["settings"][change.replace("_profile", ".profiles.extra.port")] = "9400"
    with pytest.raises(ValueError):
        validate(m, data)


@pytest.mark.parametrize(
    "name", list(REQUIRED), ids=["security", "http_tls", "transport_tls", "mtls", "remote"]
)
@pytest.mark.parametrize("change", ["missing", "bool", "wrong"])
def test_required_security_settings_are_present_exact_strings(name, change):
    m = module()
    data = packets()
    settings = data["nodes"]["nodes"][NODE]["settings"]
    if change == "missing":
        del settings[name]
    else:
        settings[name] = True if change == "bool" else "unexpected"
    with pytest.raises(ValueError):
        validate(m, data)


@pytest.mark.parametrize(
    "change", ["anonymous", "anonymous_text", "http_verify", "transport_verify"]
)
def test_visible_security_settings_cannot_contradict_secured_configuration(change):
    m = module()
    data = packets()
    key, value = {
        "anonymous": ("xpack.security.authc.anonymous.roles", ["superuser"]),
        "anonymous_text": ("xpack.security.authc.anonymous.roles", "superuser"),
        "http_verify": ("xpack.security.http.ssl.verification_mode", "none"),
        "transport_verify": ("xpack.security.transport.ssl.verification_mode", "certificate"),
    }[change]
    data["nodes"]["nodes"][NODE]["settings"][key] = value
    with pytest.raises(ValueError):
        validate(m, data)


@pytest.mark.parametrize("listener", ["http", "transport"])
@pytest.mark.parametrize(
    "change",
    ["empty", "duplicate", "loopback", "other_port", "scalar", "item_type", "publish", "host_only"],
)
def test_listener_addresses_cannot_hide_extra_or_unexpected_endpoints(listener, change):
    m = module()
    data = packets()
    slot = data["nodes"]["nodes"][NODE][listener]
    port = 9200 if listener == "http" else 9300
    if change in {"publish", "host_only"}:
        slot["publish_address"] = (
            f"172.28.0.9:{port}" if change == "publish" else f"elasticsearch:{port}"
        )
    else:
        slot["bound_address"] = {
            "empty": [],
            "duplicate": [f"0.0.0.0:{port}"] * 2,
            "loopback": [f"127.0.0.1:{port}"],
            "other_port": ["0.0.0.0:9400"],
            "scalar": f"0.0.0.0:{port}",
            "item_type": [True],
        }[change]
    with pytest.raises(ValueError):
        validate(m, data)


@pytest.mark.parametrize(
    "change",
    [
        "container_late",
        "sample_early",
        "jvm_naive",
        "container_naive",
        "sample_naive",
        "jvm_text",
        "sample_text",
    ],
)
def test_chronology_and_datetime_types_are_not_coerced(change):
    m = module()
    values = expected_values()
    at: Any = SAMPLED
    if change == "container_late":
        values["container_started_at"] = START + timedelta(microseconds=1)
    elif change == "sample_early":
        at = START - timedelta(microseconds=1)
    elif change in {"jvm_naive", "container_naive"}:
        values["jvm_start_at" if change == "jvm_naive" else "container_started_at"] = START.replace(
            tzinfo=None
        )
    elif change == "sample_naive":
        at = SAMPLED.replace(tzinfo=None)
    elif change == "jvm_text":
        values["jvm_start_at"] = START.isoformat()
    else:
        at = SAMPLED.isoformat()
    with pytest.raises(ValueError):
        validate(m, packets(), expected=m.ServerReadExpectation(**values), sampled_at=at)


def test_chronology_accepts_exact_equal_boundaries():
    m = module()
    values = expected_values() | {"container_started_at": START}
    assert (
        validate(m, packets(), expected=m.ServerReadExpectation(**values), sampled_at=START)
        == encode(public_value()).decode()
    )


@pytest.mark.parametrize("target", ["info", "state", "nodes"])
@pytest.mark.parametrize(
    "change",
    [
        "empty",
        "utf8",
        "duplicate",
        "nan",
        "infinity",
        "overflow",
        "list",
        "bool",
        "oversize",
        "text",
        "bytearray",
    ],
)
def test_each_wire_body_is_bounded_exact_utf8_object_without_ambiguous_numbers(target, change):
    m = module()
    values = {key: encode(value) for key, value in packets().items()}
    valid = values[target]
    values[target] = {
        "empty": b"",
        "utf8": b"\xff",
        "duplicate": b'{"same":1,"same":2,' + valid[1:],
        "nan": b'{"private":NaN,' + valid[1:],
        "infinity": b'{"private":Infinity,' + valid[1:],
        "overflow": b'{"private":1e999,' + valid[1:],
        "list": b"[]",
        "bool": b"true",
        "oversize": b" " * (MAX_BYTES + 1),
        "text": values[target].decode(),
        "bytearray": bytearray(values[target]),
    }[change]
    with pytest.raises(ValueError):
        m.validate_server_packets(
            m.ServerReadExpectation(**expected_values()), **values, sampled_at=SAMPLED
        )


@pytest.mark.parametrize("target", ["info", "state", "nodes"])
def test_each_wire_body_accepts_exact_byte_limit_and_rejects_one_byte_more(target):
    m = module()
    values = {key: encode(value) for key, value in packets().items()}
    values[target] += b" " * (MAX_BYTES - len(values[target]))
    expected = m.ServerReadExpectation(**expected_values())
    assert (
        m.validate_server_packets(expected, **values, sampled_at=SAMPLED)
        == encode(public_value()).decode()
    )
    values[target] += b" "
    with pytest.raises(ValueError):
        m.validate_server_packets(expected, **values, sampled_at=SAMPLED)


def test_expectation_is_frozen_ordinary_data_and_public_failures_do_not_echo_body():
    m = module()
    expected = m.ServerReadExpectation(**expected_values())
    with pytest.raises(FrozenInstanceError):
        expected.cluster_uuid = "changed"
    data = packets()
    data["state"]["nodes"][NODE]["ephemeral_id"] = "private-response-sentinel"
    with pytest.raises(ValueError) as error:
        validate(m, data, expected=expected)
    assert "private-response-sentinel" not in str(error.value)
