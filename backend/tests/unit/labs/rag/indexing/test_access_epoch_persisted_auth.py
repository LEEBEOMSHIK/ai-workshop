"""Synthetic committed auth manifests; no profile rows, credentials or I/O."""

import importlib
import json
import socket
import subprocess
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions

EPOCH = UUID("00000000-0000-4000-8000-000000000001")
EXECUTION = UUID("00000000-0000-4000-8000-000000000002")
PROFILE = UUID("12345678-1234-4234-8234-123456789abc")
PROCESSING = UUID("23456789-2345-4345-8345-23456789abcd")
LEGACY = "00000000-0000-0000-0000-000000000207"
CONTAINER = "a" * 64
ROLES = ("reader", "writer", "collector")
KEY_IDS = tuple((role, f"synthetic-{role}-id") for role in ROLES)
LIMIT = 262144
CLUSTER = ["all", "manage", "manage_api_key", "manage_own_api_key", "manage_security", "monitor"]
ALL_INDEX = [
    "all",
    "create",
    "create_doc",
    "create_index",
    "delete",
    "delete_index",
    "index",
    "maintenance",
    "manage",
    "read",
    "view_index_metadata",
    "write",
]


def module():
    name = "ai_workshop.labs.rag.indexing.access_epoch_persisted_auth"
    assert importlib.util.find_spec(name) is not None, "committed auth policy decoder missing"
    return importlib.import_module(name)


def patterns(prefix="rag"):
    return [f"{prefix}-{PROFILE}-*", f"{prefix}-{PROCESSING}-{PROFILE}-*"]


def descriptor(role, names):
    # Literal contract oracle; do not call AccessEpochPermissions.descriptor here.
    return {
        "cluster": ["monitor"],
        "indices": [
            {
                "names": list(names),
                "privileges": ["read", "write", "manage"]
                if role == "writer"
                else ["read", "view_index_metadata"],
                "allow_restricted_indices": False,
            }
        ],
        "applications": [],
        "run_as": [],
        "metadata": {},
    }


def checked_query(role, names, epoch=EPOCH):
    # The persisted packet contains the finite query, not its response booleans.
    return {
        "cluster": list(CLUSTER),
        "index": [
            {
                "names": list(names),
                "privileges": ["all", "manage", "read", "write"]
                if role == "writer"
                else list(ALL_INDEX),
                "allow_restricted_indices": False,
            },
            {
                "names": ["*", ".security", "access-epoch-outside-" + epoch.hex],
                "privileges": list(ALL_INDEX),
                "allow_restricted_indices": False,
            },
        ],
        "application": [],
    }


def manifest(names=None, *, prefix="rag", epoch=EPOCH):
    names = patterns(prefix) if names is None else names
    return {
        "schema_version": 1,
        "epoch_id": str(epoch),
        "execution_id": str(EXECUTION),
        "container_id": CONTAINER,
        "keys": dict(KEY_IDS),
        "auth_policy": {
            "verification": "finite_privilege_checks_with_issuer_bound_exact_descriptors",
            "authentication_type": "api_key",
            "namespace_patterns": deepcopy(names),
            "descriptors": {role: descriptor(role, names) for role in ROLES},
            "checked_privileges": {role: checked_query(role, names, epoch) for role in ROLES},
            "writer_manage_includes_index_delete": True,
            "writer_write_includes_document_delete": True,
        },
    }


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def decode(m, body, **changes):
    kwargs = {
        "prefix": "rag",
        "epoch_id": EPOCH,
        "execution_id": EXECUTION,
        "container_id": CONTAINER,
        "key_ids": KEY_IDS,
    } | changes
    return m.decode_committed_auth_policy(body, **kwargs)


@pytest.mark.parametrize("prefix", ["rag", "rag-team.v2_01", "rag-"])
def test_full_manifest_recovers_both_namespace_grammars_as_ordinary_permissions(prefix):
    m = module()
    data = manifest(prefix=prefix)
    before = deepcopy(data)
    result = decode(m, encode(data), prefix=prefix)
    assert type(result) is AccessEpochPermissions
    assert result.prefix == prefix
    assert set(result.namespaces) == {(PROFILE, None), (PROFILE, PROCESSING)}
    for role in ROLES:
        assert result.descriptor(role) == descriptor(role, patterns(prefix))
    assert data == before
    assert not hasattr(result, "source_binding") and not hasattr(result, "authority")


@pytest.mark.parametrize("grammar", ["profile", "processing"])
def test_single_namespace_requires_no_profile_database_lookup(grammar, monkeypatch):
    m = module()
    name = patterns()[grammar == "processing"]

    def deny_io(*args, **kwargs):
        raise AssertionError("pure committed policy validation attempted I/O")

    with monkeypatch.context() as blocked:
        blocked.setattr(socket.socket, "connect", deny_io)
        blocked.setattr(socket, "create_connection", deny_io)
        blocked.setattr(subprocess, "Popen", deny_io)
        blocked.setattr(Path, "read_bytes", deny_io)
        result = decode(m, encode(manifest([name])))
    assert result.namespaces == ((PROFILE, PROCESSING if grammar == "processing" else None),)


@pytest.mark.parametrize(
    "change",
    [
        "wrong_prefix",
        "wild_prefix",
        "profile_zero",
        "processing_zero",
        "uppercase",
        "hex",
        "braces",
        "urn",
        "extra_uuid",
        "active_suffix",
        "missing_star",
        "extra_star",
        "legacy_processing",
        "duplicate",
        "reversed",
        "empty",
        "not_string",
        "scalar",
    ],
)
def test_namespace_grammar_is_canonical_ordered_nonzero_and_not_legacy_processing(change):
    m = module()
    names = patterns()
    bad = {
        "wrong_prefix": f"other-{PROFILE}-*",
        "wild_prefix": f"rag*-{PROFILE}-*",
        "profile_zero": f"rag-{UUID(int=0)}-*",
        "processing_zero": f"rag-{UUID(int=0)}-{PROFILE}-*",
        "uppercase": f"rag-{str(PROFILE).upper()}-*",
        "hex": f"rag-{PROFILE.hex}-*",
        "braces": f"rag-{{{PROFILE}}}-*",
        "urn": f"rag-urn:uuid:{PROFILE}-*",
        "extra_uuid": f"rag-{PROCESSING}-{PROFILE}-{EPOCH}-*",
        "active_suffix": f"rag-{PROFILE}-active",
        "missing_star": f"rag-{PROFILE}-",
        "extra_star": f"rag-{PROFILE}-**",
        "legacy_processing": f"rag-{LEGACY}-{PROFILE}-*",
    }
    if change in bad:
        names = [bad[change]]
    elif change == "duplicate":
        names = [names[0], names[0]]
    elif change == "reversed":
        names.reverse()
    elif change == "empty":
        names = []
    elif change == "not_string":
        names = [True]
    data = manifest(names)
    if change == "scalar":
        data["auth_policy"]["namespace_patterns"] = names[0]
    with pytest.raises(ValueError):
        decode(m, encode(data))


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "missing",
        "schema_bool",
        "schema_float",
        "schema_version",
        "epoch",
        "execution",
        "container",
        "keys_missing",
        "keys_extra",
        "key_wrong",
        "key_bool",
    ],
)
def test_full_outer_manifest_is_closed_and_matches_supplied_identity(change):
    m = module()
    data = manifest()
    if change == "extra":
        data["caller_approved"] = True
    elif change == "missing":
        del data["execution_id"]
    elif change.startswith("schema_"):
        data["schema_version"] = {"schema_bool": True, "schema_float": 1.0, "schema_version": 2}[
            change
        ]
    elif change in {"epoch", "execution", "container"}:
        data[change + "_id"] = "b" * 64 if change == "container" else str(UUID(int=999))
    elif change == "keys_missing":
        del data["keys"]["reader"]
    elif change == "keys_extra":
        data["keys"]["admin"] = "unexpected"
    else:
        data["keys"]["reader"] = True if change == "key_bool" else "other-key"
    with pytest.raises(ValueError):
        decode(m, encode(data))


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "missing",
        "verification",
        "authentication",
        "manage_false",
        "manage_int",
        "write_float",
        "descriptor_role",
        "query_role",
    ],
)
def test_inner_contract_flags_and_role_sets_are_exact_not_python_coercive_equality(change):
    m = module()
    data = manifest()
    policy = data["auth_policy"]
    if change == "extra":
        policy["source_authority"] = True
    elif change == "missing":
        del policy["writer_write_includes_document_delete"]
    elif change == "verification":
        policy["verification"] = "universal_grant_absence"
    elif change == "authentication":
        policy["authentication_type"] = "realm"
    elif change in {"manage_false", "manage_int"}:
        policy["writer_manage_includes_index_delete"] = False if change == "manage_false" else 1
    elif change == "write_float":
        policy["writer_write_includes_document_delete"] = 1.0
    elif change == "descriptor_role":
        policy["descriptors"]["admin"] = descriptor("writer", patterns())
    else:
        del policy["checked_privileges"]["collector"]
    with pytest.raises(ValueError):
        decode(m, encode(data))


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(
    "change",
    ["names", "cluster", "privileges", "restricted_bool", "restricted_int", "run_as", "metadata"],
)
def test_every_persisted_descriptor_matches_the_rebuilt_finite_policy(role, change):
    m = module()
    data = manifest()
    value = data["auth_policy"]["descriptors"][role]
    if change == "names":
        value["indices"][0]["names"] = ["*"]
    elif change == "cluster":
        value["cluster"] = ["all"]
    elif change == "privileges":
        value["indices"][0]["privileges"] = ["all"]
    elif change in {"restricted_bool", "restricted_int"}:
        value["indices"][0]["allow_restricted_indices"] = True if change == "restricted_bool" else 0
    elif change == "run_as":
        value["run_as"] = ["*"]
    else:
        value["metadata"] = {"synthetic-private-marker": "not-approved"}
    with pytest.raises(ValueError) as error:
        decode(m, encode(data))
    assert "synthetic-private-marker" not in str(error.value)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(
    "change",
    [
        "cluster",
        "inside",
        "outside",
        "sentinel",
        "privileges",
        "restricted_int",
        "application",
        "order",
    ],
)
def test_every_checked_query_preserves_inside_and_outside_coverage(role, change):
    m = module()
    data = manifest()
    value = data["auth_policy"]["checked_privileges"][role]
    if change == "cluster":
        value["cluster"].remove("manage_security")
    elif change == "inside":
        value["index"][0]["names"] = ["*"]
    elif change == "outside":
        value["index"][1]["names"].remove(".security")
    elif change == "sentinel":
        value["index"][1]["names"][-1] = "access-epoch-outside-" + UUID(int=999).hex
    elif change == "privileges":
        value["index"][1]["privileges"].remove("delete")
    elif change == "restricted_int":
        value["index"][1]["allow_restricted_indices"] = 0
    elif change == "application":
        value["application"] = [{"application": "*"}]
    else:
        value["index"].reverse()
    with pytest.raises(ValueError):
        decode(m, encode(data))


@pytest.mark.parametrize(
    "change",
    [
        "epoch_zero",
        "epoch_text",
        "execution_zero",
        "execution_text",
        "prefix_empty",
        "prefix_wildcard",
        "container_text",
        "container_upper",
        "keys_list",
        "pair_list",
        "role_duplicate",
        "key_duplicate",
        "role_unknown",
        "key_empty",
    ],
)
def test_expected_inputs_are_typed_and_cannot_gain_authority_from_matching_bad_data(change):
    m = module()
    data = manifest()
    kwargs = {}
    if change in {"epoch_zero", "epoch_text"}:
        value = UUID(int=0) if change == "epoch_zero" else str(EPOCH)
        kwargs["epoch_id"] = value
        if change == "epoch_zero":
            data = manifest(epoch=value)
    elif change in {"execution_zero", "execution_text"}:
        value = UUID(int=0) if change == "execution_zero" else str(EXECUTION)
        kwargs["execution_id"] = value
        data["execution_id"] = str(value)
    elif change in {"prefix_empty", "prefix_wildcard"}:
        kwargs["prefix"] = "" if change == "prefix_empty" else "rag*"
        data = manifest(prefix=kwargs["prefix"])
    elif change.startswith("container_"):
        kwargs["container_id"] = (
            "not-a-container" if change == "container_text" else CONTAINER.upper()
        )
        data["container_id"] = kwargs["container_id"]
    elif change == "keys_list":
        kwargs["key_ids"] = list(KEY_IDS)
    elif change == "pair_list":
        kwargs["key_ids"] = tuple(list(pair) for pair in KEY_IDS)
    else:
        pairs = list(KEY_IDS)
        if change == "role_duplicate":
            pairs[1] = pairs[0]
        elif change == "key_duplicate":
            pairs[1] = ("writer", pairs[0][1])
        elif change == "role_unknown":
            pairs[0] = ("admin", pairs[0][1])
        else:
            pairs[0] = ("reader", "")
        kwargs["key_ids"] = tuple(pairs)
        data["keys"] = dict(pairs)
    with pytest.raises(ValueError):
        decode(m, encode(data), **kwargs)


@pytest.mark.parametrize(
    "change",
    [
        "empty",
        "utf8",
        "duplicate_outer",
        "duplicate_nested",
        "nan",
        "infinity",
        "overflow",
        "list",
        "text",
        "bytearray",
    ],
)
def test_raw_manifest_rejects_ambiguous_json_and_wire_coercion(change):
    m = module()
    valid = encode(manifest())
    if change == "duplicate_outer":
        body = b'{"schema_version":1,' + valid[1:]
    elif change == "duplicate_nested":
        body = valid.replace(
            b'"authentication_type":"api_key"',
            b'"authentication_type":"api_key","authentication_type":"api_key"',
            1,
        )
    elif change in {"nan", "infinity", "overflow"}:
        token = {"nan": b"NaN", "infinity": b"Infinity", "overflow": b"1e999"}[change]
        body = valid.replace(b'"schema_version":1', b'"schema_version":' + token)
    else:
        body = {
            "empty": b"",
            "utf8": b"\xff",
            "list": b"[]",
            "text": valid.decode(),
            "bytearray": bytearray(valid),
        }[change]
    with pytest.raises(ValueError):
        decode(m, body)


def test_json_object_order_and_whitespace_do_not_change_policy_but_size_is_bounded():
    m = module()
    data = dict(reversed(tuple(manifest().items())))
    raw = json.dumps(data, indent=2).encode()
    assert decode(m, raw).descriptor("writer") == descriptor("writer", patterns())
    raw += b" " * (LIMIT - len(raw))
    assert decode(m, raw).descriptor("reader") == descriptor("reader", patterns())
    with pytest.raises(ValueError):
        decode(m, raw + b" ")
