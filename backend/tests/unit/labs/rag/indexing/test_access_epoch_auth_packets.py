"""Synthetic finite-policy packets; no server, credentials or execution authority."""

import importlib
import json
from uuid import UUID

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions

EPOCH = UUID("00000000-0000-4000-8000-000000000001")
PROFILE = UUID("00000000-0000-4000-8000-000000000002")
PROCESSING = UUID("00000000-0000-4000-8000-000000000003")
PATTERNS = [f"rag-{PROFILE}-*", f"rag-{PROCESSING}-{PROFILE}-*"]
OUTSIDE = ["*", ".security", "access-epoch-outside-" + EPOCH.hex]
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
KEY_ID = "synthetic-reader-id"
KEY_NAME = f"ai-workshop-{EPOCH}-reader-00000000-0000-4000-8000-000000000004"


def module():
    return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_auth_packets")


def permissions():
    return AccessEpochPermissions("rag", ((PROFILE, PROCESSING), (PROFILE, None)))


def expected_policy(role):
    # Independent policy oracle: no product descriptor/query is used to grant privileges.
    required = {"read", "write", "manage"} if role == "writer" else {"read", "view_index_metadata"}
    inside = ["all", "manage", "read", "write"] if role == "writer" else ALL_INDEX
    query = {
        "cluster": CLUSTER,
        "index": [
            {"names": sorted(PATTERNS), "privileges": inside, "allow_restricted_indices": False},
            {"names": OUTSIDE, "privileges": ALL_INDEX, "allow_restricted_indices": False},
        ],
        "application": [],
    }
    expected = {
        "username": "elastic",
        "has_all_requested": False,
        "cluster": {name: name == "monitor" for name in CLUSTER},
        "index": {
            **{
                name: {privilege: privilege in required for privilege in inside}
                for name in PATTERNS
            },
            **{name: {privilege: False for privilege in ALL_INDEX} for name in OUTSIDE},
        },
        "application": {},
    }
    return query, expected


def auth_value():
    return {
        "username": "elastic",
        "roles": [],
        "full_name": None,
        "email": None,
        "metadata": {},
        "enabled": True,
        "authentication_realm": {"name": "_es_api_key", "type": "_es_api_key"},
        "lookup_realm": {"name": "_es_api_key", "type": "_es_api_key"},
        "authentication_type": "api_key",
        "api_key": {"id": KEY_ID, "name": KEY_NAME, "managed_by": "elasticsearch"},
    }


def encode(value):
    return json.dumps(value, separators=(",", ":")).encode()


def validate_auth(body, **kwargs):
    return module().validate_authenticated_body(
        body, key_id=kwargs.get("key_id", KEY_ID), key_name=kwargs.get("key_name", KEY_NAME)
    )


@pytest.mark.parametrize("role", ["reader", "writer", "collector"])
def test_fixed_queries_and_response_policy_for_each_role(role):
    m = module()
    query, expected = expected_policy(role)
    actual_query, actual_expected = m.finite_privilege_matrix(EPOCH, permissions(), role)
    assert encode(actual_query) == encode(query)
    # Object key order in server JSON is irrelevant, boolean values are not.
    assert actual_expected == expected
    assert (
        m.validate_privileges_body(
            encode(expected), epoch_id=EPOCH, permissions=permissions(), role=role
        )
        is None
    )
    actual_query["index"][0]["names"].append("*")
    actual_expected["cluster"]["manage_security"] = True
    again = m.finite_privilege_matrix(EPOCH, permissions(), role)
    assert again == (query, expected)


@pytest.mark.parametrize("role", ["reader", "writer", "collector"])
@pytest.mark.parametrize(
    "change",
    [
        "security",
        "outside",
        "restricted",
        "missing",
        "extra",
        "int",
        "float",
        "flag",
        "application",
    ],
)
def test_finite_privilege_results_reject_policy_drift(role, change):
    value = expected_policy(role)[1]
    if change == "security":
        value["cluster"]["manage_security"] = True
    elif change == "outside":
        value["index"]["*"]["read"] = True
    elif change == "restricted":
        value["index"][".security"]["read"] = True
    elif change == "missing":
        del value["index"][PATTERNS[0]]["read"]
    elif change == "extra":
        value["index"][PATTERNS[0]]["unrequested"] = False
    elif change == "int":
        value["cluster"]["monitor"] = 1
    elif change == "float":
        value["cluster"]["monitor"] = 1.0
    elif change == "flag":
        value["has_all_requested"] = True
    else:
        value["application"] = {"unrequested": {}}
    with pytest.raises(ValueError, match="^auth_packet_denied$"):
        module().validate_privileges_body(
            encode(value), epoch_id=EPOCH, permissions=permissions(), role=role
        )


@pytest.mark.parametrize("realm", ["_es_api_key", "another-nonempty-realm"])
def test_authentication_accepts_exact_public_identity_and_returns_no_private_metadata(realm):
    value = auth_value()
    value["authentication_realm"] = {"name": realm, "type": realm}
    value["lookup_realm"] = dict(value["authentication_realm"])
    value["metadata"] = {"synthetic_private_owner_note": ["private-note", 1.5]}
    assert validate_auth(encode(value)) is None


@pytest.mark.parametrize(
    "change",
    [
        "id",
        "name",
        "managed_by",
        "key_extra",
        "missing",
        "extra",
        "username",
        "type",
        "enabled",
        "roles_type",
        "roles_member",
        "roles_duplicate",
        "metadata",
        "full_name",
        "email",
        "realm_empty",
        "realm_extra",
        "realm_nonstring",
        "realm_lookup",
    ],
)
def test_authentication_rejects_ambiguous_identity_or_schema(change):
    value = auth_value()
    if change in {"id", "name", "managed_by"}:
        value["api_key"][change] = "other"
    elif change == "key_extra":
        value["api_key"]["private"] = "private-note"
    elif change == "missing":
        del value["email"]
    elif change == "extra":
        value["private"] = "private-note"
    elif change == "username":
        value["username"] = "other"
    elif change == "type":
        value["authentication_type"] = "realm"
    elif change == "enabled":
        value["enabled"] = 1
    elif change == "roles_type":
        value["roles"] = {}
    elif change == "roles_member":
        value["roles"] = [1]
    elif change == "roles_duplicate":
        value["roles"] = ["one", "one"]
    elif change == "metadata":
        value["metadata"] = []
    elif change in {"full_name", "email"}:
        value[change] = 1
    elif change == "realm_empty":
        value["authentication_realm"]["name"] = ""
        value["lookup_realm"]["name"] = ""
    elif change == "realm_extra":
        value["authentication_realm"]["extra"] = "other"
        value["lookup_realm"]["extra"] = "other"
    elif change == "realm_nonstring":
        value["authentication_realm"]["type"] = 1
        value["lookup_realm"]["type"] = 1
    else:
        value["lookup_realm"]["name"] = "other"
    with pytest.raises(ValueError, match="^auth_packet_denied$") as exc:
        validate_auth(encode(value))
    assert "private-note" not in str(exc.value)


@pytest.mark.parametrize(
    "fragment",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b'{"x":1e400}',
        b'{"x":-1e400}',
        b'{"x":"\xff"}',
    ],
)
def test_malformed_private_metadata_is_rejected_even_when_not_published(fragment):
    body = encode(auth_value()).replace(b'"metadata":{}', b'"metadata":' + fragment)
    with pytest.raises(ValueError, match="^auth_packet_denied$"):
        validate_auth(body)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"[]",
        b"null",
        b"true",
        b"{}\n200",
        b"{}{}",
        b'{"x":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}",
        b" " * 262145,
        bytearray(b"{}"),
        "{}",
    ],
    ids=[
        "empty",
        "array",
        "null",
        "bool",
        "wire",
        "trailing",
        "deep",
        "oversize",
        "bytearray",
        "str",
    ],
)
def test_body_only_decoder_rejects_invalid_types_framing_depth_and_bounds(body):
    with pytest.raises(ValueError, match="^auth_packet_denied$"):
        validate_auth(body)


def test_exact_body_limit_is_accepted_but_not_extended():
    body = encode(auth_value())
    assert validate_auth(body + b" " * (262144 - len(body))) is None
    with pytest.raises(ValueError, match="^auth_packet_denied$"):
        validate_auth(body + b" " * (262145 - len(body)))


class StringSubclass(str):
    pass


@pytest.mark.parametrize(
    "change",
    [
        "epoch_zero",
        "epoch_string",
        "role_unknown",
        "role_subclass",
        "permissions_duck",
        "prefix_subclass",
        "prefix_wildcard",
        "namespaces_list",
        "namespace_list",
        "profile_string",
        "profile_zero",
        "processing_string",
        "duplicate",
    ],
)
def test_public_policy_inputs_are_exact_values_not_arbitrary_descriptors(change):
    epoch, policy, role = EPOCH, permissions(), "reader"
    if change == "epoch_zero":
        epoch = UUID(int=0)
    elif change == "epoch_string":
        epoch = str(EPOCH)
    elif change == "role_unknown":
        role = "administrator"
    elif change == "role_subclass":
        role = StringSubclass(role)
    elif change == "permissions_duck":
        policy = {"indices": [{"names": ["*"]}]}
    elif change == "prefix_subclass":
        object.__setattr__(policy, "prefix", StringSubclass("rag"))
    elif change == "prefix_wildcard":
        object.__setattr__(policy, "prefix", "*")
    else:
        namespaces = {
            "namespaces_list": [(PROFILE, None)],
            "namespace_list": ([PROFILE, None],),
            "profile_string": ((str(PROFILE), None),),
            "profile_zero": ((UUID(int=0), None),),
            "processing_string": ((PROFILE, str(PROCESSING)),),
            "duplicate": ((PROFILE, None), (PROFILE, None)),
        }[change]
        object.__setattr__(policy, "namespaces", namespaces)
    with pytest.raises(ValueError, match="^auth_packet_denied$"):
        module().finite_privilege_matrix(epoch, policy, role)


@pytest.mark.parametrize(
    "field,value",
    [
        ("key_id", ""),
        ("key_id", StringSubclass(KEY_ID)),
        ("key_id", 1),
        ("key_name", ""),
        ("key_name", StringSubclass(KEY_NAME)),
        ("key_name", None),
    ],
)
def test_expected_public_identity_is_not_coerced(field, value):
    with pytest.raises(ValueError, match="^auth_packet_denied$"):
        validate_auth(encode(auth_value()), **{field: value})
