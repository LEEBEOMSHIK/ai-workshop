"""Fixed final-auth requests and strict synthetic response decoding, no I/O."""

import base64
import importlib
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr

from ai_workshop.labs.rag.indexing.access_epoch_bootstrap import BootstrapIssuedKey
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions


def module():
    return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_final_auth")


class Issuer:
    def __init__(self, binding):
        self.binding = binding
        self.revoked = False

    def assert_issued(self, binding):
        if self.revoked or binding is not self.binding:
            raise ValueError("private issuer detail")


@pytest.fixture
def case():
    m = module()
    epoch = uuid4()
    keys = []
    for role in ("reader", "writer", "collector"):
        issuance = uuid4()
        key_id = "synthetic-id-" + role
        encoded = base64.b64encode((key_id + ":synthetic-private-" + role).encode()).decode()
        keys.append(
            BootstrapIssuedKey(
                key_id,
                f"ai-workshop-{epoch}-{role}-{issuance}",
                epoch,
                issuance,
                role,
                SecretStr(encoded),
            )
        )
    binding = m.FinalAuthBinding(
        uuid4(),
        epoch,
        uuid4(),
        "a" * 64,
        AccessEpochPermissions("rag", ((uuid4(), None),)),
        tuple(keys),
    )
    issuer = Issuer(binding)
    return SimpleNamespace(
        m=m, binding=binding, issuer=issuer, builder=m.FinalAuthCommands(binding, issuer)
    )


def response(c, value, *, exit_code=0, status=200):
    return c.m.FinalAuthResponse(
        exit_code, json.dumps(value).encode() + b"\n" + str(status).encode()
    )


def auth_value(c, role):
    key = next(key for key in c.binding.keys if key.role == role)
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
        "api_key": {"id": key.key_id, "name": key.name, "managed_by": "elasticsearch"},
    }


def config(command):
    return dict(
        (line.split(" = ", 1)[0], json.loads(line.split(" = ", 1)[1]))
        for line in command.private_stdin.decode().splitlines()
        if line.startswith(("url =", "request =", "data ="))
    )


def privilege_value(c, command):
    query = json.loads(config(command)["data"])
    granted = set(c.binding.permissions.descriptor(command.role)["indices"][0]["names"])
    required = set(c.binding.permissions.descriptor(command.role)["indices"][0]["privileges"])
    return {
        "username": "elastic",
        "has_all_requested": False,
        "cluster": {name: name == "monitor" for name in query["cluster"]},
        "index": {
            name: {
                privilege: name in granted and privilege in required
                for privilege in item["privileges"]
            }
            for item in query["index"]
            for name in item["names"]
        },
        "application": {},
    }


def authenticate(c, role):
    command = c.builder.authenticate(role)
    return c.builder.decode_authenticated(command, response(c, auth_value(c, role)))


def test_three_roles_fixed_requests_and_precise_public_manifest(case):
    c = case
    observations = []
    for role in ("reader", "writer", "collector"):
        auth = authenticate(c, role)
        command = c.builder.privileges(auth)
        assert c.builder.assert_command(command) is None
        wire = config(command)
        assert (
            wire["request"] == "POST"
            and wire["url"] == "https://localhost:9200/_security/user/_has_privileges"
        )
        query = json.loads(wire["data"])
        assert set(query) == {"cluster", "index", "application"}
        assert {"monitor", "manage_security", "manage_api_key", "all"} <= set(query["cluster"])
        assert all(item["allow_restricted_indices"] is False for item in query["index"])
        assert c.binding.container_id in command.argv
        assert (
            "--host" in command.argv and "npipe:////./pipe/dockerDesktopLinuxEngine" in command.argv
        )
        assert command.argv[8:12] == ("/usr/bin/curl", "-q", "--config", "-")
        assert "--cacert" in command.argv and "--insecure" not in command.argv
        assert "--location" not in command.argv and "--retry" not in command.argv
        key = next(key for key in c.binding.keys if key.role == role)
        assert key.encoded.get_secret_value() not in repr(command)
        assert key.encoded.get_secret_value() not in " ".join(command.argv)
        result = c.builder.decode_privileges(command, response(c, privilege_value(c, command)))
        observations.append(result)
    result = c.builder.complete(tuple(observations))
    assert c.builder.assert_observed(result) is None
    manifest = json.loads(result.manifest_json)
    policy = manifest["auth_policy"]
    assert policy["verification"] == "finite_privilege_checks_with_issuer_bound_exact_descriptors"
    assert policy["writer_manage_includes_index_delete"] is True
    assert policy["writer_write_includes_document_delete"] is True
    assert (
        policy["namespace_patterns"]
        == c.binding.permissions.descriptor("writer")["indices"][0]["names"]
    )
    assert set(manifest["keys"]) == {"reader", "writer", "collector"}
    for key in c.binding.keys:
        assert key.encoded.get_secret_value() not in result.manifest_json
    assert "Authorization" not in result.manifest_json and "stdout" not in result.manifest_json


@pytest.mark.parametrize(
    "change",
    [
        "copy",
        "duplicate_id",
        "duplicate_role",
        "wrong_epoch",
        "admin_role",
        "wrong_encoded_id",
        "bad_encoded",
        "wrong_name",
        "wrong_container",
        "not_secret",
    ],
)
def test_binding_is_issued_three_independent_epoch_bound_keys(case, change):
    c = case
    keys = list(c.binding.keys)
    binding = c.binding
    if change == "copy":
        binding = replace(binding)
    elif change == "duplicate_id":
        keys[1] = replace(keys[1], key_id=keys[0].key_id)
    elif change == "duplicate_role":
        keys[1] = replace(keys[1], role="reader")
    elif change == "wrong_epoch":
        keys[1] = replace(keys[1], epoch_id=uuid4())
    elif change == "admin_role":
        keys[1] = replace(keys[1], role="administrator")
    elif change == "wrong_encoded_id":
        keys[1] = replace(keys[1], encoded=keys[0].encoded)
    elif change == "bad_encoded":
        keys[1] = replace(keys[1], encoded=SecretStr("injected\nheader"))
    elif change == "wrong_name":
        keys[1] = replace(keys[1], name="unbound-name")
    elif change == "wrong_container":
        binding = replace(binding, container_id="not-a-container")
    elif change == "not_secret":
        keys[1] = replace(keys[1], encoded="private")
    if change != "copy":
        binding = replace(binding, keys=tuple(keys))
        c.issuer.binding = binding
    with pytest.raises(ValueError, match="final_auth_denied"):
        c.m.FinalAuthCommands(binding, c.issuer)


@pytest.mark.parametrize(
    "change",
    [
        "basic",
        "wrong_id",
        "wrong_name",
        "disabled",
        "int_enabled",
        "missing_key",
        "unknown",
        "token",
        "cloud",
        "metadata_in_key",
        "missing_managed_by",
        "wrong_username",
        "realm_mismatch",
    ],
)
def test_authenticate_rejects_wrong_identity_and_ambiguous_schema(case, change):
    c = case
    command = c.builder.authenticate("reader")
    value = auth_value(c, "reader")
    if change == "basic":
        value["authentication_type"] = "realm"
    elif change == "wrong_id":
        value["api_key"]["id"] = "other"
    elif change == "wrong_name":
        value["api_key"]["name"] = "other"
    elif change == "disabled":
        value["enabled"] = False
    elif change == "int_enabled":
        value["enabled"] = 1
    elif change == "missing_key":
        del value["api_key"]
    elif change == "unknown":
        value["unrecognized"] = {}
    elif change == "token":
        value["token"] = {"name": "ambiguous"}
    elif change == "cloud":
        value["api_key"]["managed_by"] = "cloud"
    elif change == "metadata_in_key":
        value["api_key"]["metadata"] = {"ai_workshop_role": "reader"}
    elif change == "missing_managed_by":
        del value["api_key"]["managed_by"]
    elif change == "wrong_username":
        value["username"] = "other"
    elif change == "realm_mismatch":
        value["lookup_realm"]["type"] = "file"
    with pytest.raises(ValueError, match="final_auth_response_denied"):
        c.builder.decode_authenticated(command, response(c, value))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}\n200',
        b'{"x":NaN}\n200',
        b"[]\n200",
        b"{}\n201",
        b"{}\n401",
        b"{}\n200\n",
        b"\xff\n200",
        b"{}",
        b"x" * 262145,
    ],
    ids=["duplicate", "nan", "array", "201", "401", "trailing", "utf8", "no_status", "over_limit"],
)
def test_private_response_strict_json_http_and_bounds(case, raw):
    c = case
    private = c.m.FinalAuthResponse(0, raw)
    assert repr(raw) not in repr(private)
    with pytest.raises(ValueError, match="final_auth_response_denied"):
        c.builder.decode_authenticated(c.builder.authenticate("reader"), private)


@pytest.mark.parametrize(
    "change",
    [
        "security_granted",
        "outside_granted",
        "reader_write",
        "reader_manage",
        "collector_delete",
        "required_denied",
        "all_flag",
        "int_bool",
        "missing_slot",
        "extra_slot",
        "application",
        "wrong_user",
    ],
)
def test_privilege_matrix_rejects_extra_missing_coerced_or_forbidden_grants(case, change):
    c = case
    role = "collector" if change == "collector_delete" else "reader"
    command = c.builder.privileges(authenticate(c, role))
    value = privilege_value(c, command)
    name = c.binding.permissions.descriptor(role)["indices"][0]["names"][0]
    if change == "security_granted":
        value["cluster"]["manage_security"] = True
    elif change == "outside_granted":
        value["index"]["*"]["read"] = True
    elif change == "reader_write":
        value["index"][name]["write"] = True
    elif change == "reader_manage":
        value["index"][name]["manage"] = True
    elif change == "collector_delete":
        value["index"][name]["delete_index"] = True
    elif change == "required_denied":
        value["index"][name]["read"] = False
    elif change == "all_flag":
        value["has_all_requested"] = True
    elif change == "int_bool":
        value["cluster"]["monitor"] = 1
    elif change == "missing_slot":
        del value["index"][name]["read"]
    elif change == "extra_slot":
        value["index"][name]["unrequested"] = False
    elif change == "application":
        value["application"] = {"unexpected": {}}
    elif change == "wrong_user":
        value["username"] = "other"
    with pytest.raises(ValueError, match="final_auth_response_denied"):
        c.builder.decode_privileges(command, response(c, value))


def test_command_and_observation_copies_cross_role_and_replays_rejected(case):
    c = case
    command = c.builder.authenticate("reader")
    with pytest.raises(ValueError):
        c.builder.assert_command(replace(command))
    with pytest.raises(ValueError):
        c.builder.decode_authenticated(command, response(c, auth_value(c, "writer")))
    with pytest.raises(ValueError):
        c.builder.decode_authenticated(command, response(c, auth_value(c, "reader")))
    auth = authenticate(c, "writer")
    with pytest.raises(ValueError):
        c.builder.privileges(replace(auth))
    check = c.builder.privileges(auth)
    observed = c.builder.decode_privileges(check, response(c, privilege_value(c, check)))
    with pytest.raises(ValueError):
        c.builder.decode_privileges(check, response(c, privilege_value(c, check)))
    with pytest.raises(ValueError):
        c.builder.complete((observed, observed, observed))
    other = c.m.FinalAuthCommands(c.binding, c.issuer)
    with pytest.raises(ValueError):
        other.complete((observed,))
    c.issuer.revoked = True
    with pytest.raises(ValueError):
        c.builder.authenticate("collector")


@pytest.mark.parametrize("exit_code", [True, 0.0, 1])
def test_exit_status_never_coerced(case, exit_code):
    c = case
    with pytest.raises(ValueError):
        c.builder.decode_authenticated(
            c.builder.authenticate("reader"),
            response(c, auth_value(c, "reader"), exit_code=exit_code),
        )


def test_restricted_probe_is_explicit_name_not_wildcard_excluding_restricted_indices(case):
    c = case
    command = c.builder.privileges(authenticate(c, "reader"))
    query = json.loads(config(command)["data"])
    names = {name for index in query["index"] for name in index["names"]}
    assert ".security" in names and ".security*" not in names


@pytest.mark.parametrize("change", ["same_secret", "same_issuance", "partial_roles"])
def test_independent_issuance_and_private_material_required(case, change):
    c = case
    keys = list(c.binding.keys)
    if change == "same_secret":
        first_secret = base64.b64decode(keys[0].encoded.get_secret_value()).split(b":", 1)[1]
        encoded = base64.b64encode(keys[1].key_id.encode() + b":" + first_secret).decode()
        keys[1] = replace(keys[1], encoded=SecretStr(encoded))
    elif change == "same_issuance":
        keys[1] = replace(
            keys[1],
            issuance_id=keys[0].issuance_id,
            name=f"ai-workshop-{c.binding.epoch_id}-writer-{keys[0].issuance_id}",
        )
    else:
        keys.pop()
    binding = replace(c.binding, keys=tuple(keys))
    c.issuer.binding = binding
    with pytest.raises(ValueError, match="final_auth_denied"):
        c.m.FinalAuthCommands(binding, c.issuer)


def test_owner_metadata_is_not_mistaken_for_api_key_metadata_or_published(case):
    c = case
    value = auth_value(c, "reader")
    value["metadata"] = {"_reserved": True, "synthetic_private_owner_note": "private-note"}
    command = c.builder.authenticate("reader")
    authenticated = c.builder.decode_authenticated(command, response(c, value))
    assert "private-note" not in repr(authenticated)
    assert c.builder.privileges(authenticated).role == "reader"
