"""Fixed bootstrap grammar only; never executes Docker, curl, reset or issuance."""

import base64
import importlib
import json
from dataclasses import replace
from uuid import UUID

import pytest
from pydantic import SecretStr

from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import DOCKER_EXE

EPOCH = UUID("11111111-2222-4333-8444-555555555555")
EXECUTION = UUID("22222222-2222-4333-8444-555555555555")
ISSUANCE = UUID("33333333-2222-4333-8444-555555555555")
PASSWORD = SecretStr("synthetic_private_password_1234567890")
PIPE = "npipe:////./pipe/dockerDesktopLinuxEngine"


def module():
    name = "ai_workshop.labs.rag.indexing.access_epoch_bootstrap"
    assert importlib.util.find_spec(name) is not None, "fixed bootstrap builder missing"
    return importlib.import_module(name)


def case():
    permissions = AccessEpochPermissions("synthetic", ((EPOCH, None),))
    binding = module().BootstrapBinding(DOCKER_EXE, PIPE, "a" * 64, EPOCH, EXECUTION, True)
    return module().BootstrapCommands(binding, permissions), permissions


def response(value):
    return json.dumps(value).encode() + b"\n200"


def test_reset_command_registry_rejects_copies_foreign_and_consumed_commands():
    builder, _ = case()
    other, _ = case()
    command = builder.reset_password()
    for foreign in (replace(command), other.reset_password()):
        with pytest.raises(module().BootstrapError, match="bootstrap_command_denied"):
            builder.assert_reset_command(foreign)
    assert builder.assert_reset_command(command) is None
    builder.decode_reset(command, 0, b"Synthetic-tool-password")
    with pytest.raises(module().BootstrapError, match="bootstrap_command_denied"):
        builder.assert_reset_command(command)


@pytest.mark.parametrize(
    "purpose", ["authenticate", "users", "api_keys", "file_users", "file_roles"]
)
def test_readonly_audit_registry_is_exact_and_file_paths_are_fixed(purpose):
    builder, _ = case()
    command = builder.audit_command(PASSWORD, purpose)
    assert builder.assert_audit_command(command, purpose) is None
    with pytest.raises(module().BootstrapError):
        builder.assert_audit_command(replace(command), purpose)
    if purpose.startswith("file_"):
        filename = "users" if purpose == "file_users" else "users_roles"
        assert command.argv[-2:] == ("/usr/bin/cat", "/usr/share/elasticsearch/config/" + filename)
        assert command.private_stdin == b""


@pytest.mark.parametrize("body", [b"", b"\n", b"# comment\n  # metadata\n\n"])
def test_file_realm_without_any_valid_rows_is_observed_empty(body):
    assert module().BootstrapCommands.decode_file_realm_empty(0, body) is None


@pytest.mark.parametrize(
    "exit_code,body",
    [(1, b""), (0, b"user:private"), (0, b"role:user"), (0, b"x" * 65537)],
    ids=["exit", "user", "role", "oversized"],
)
def test_unknown_or_nonempty_file_realm_is_never_cleanup(exit_code, body):
    with pytest.raises(module().BootstrapError):
        module().BootstrapCommands.decode_file_realm_empty(exit_code, body)


def payload(command):
    # Test-owned synthetic config only, independently parse curl quoted-string syntax.
    lines = command.private_stdin.decode().splitlines()
    raw = next(line.split(" = ", 1)[1] for line in lines if line.startswith("data = "))
    return json.loads(json.loads(raw))


def test_reset_is_fixed_auto_batch_silent_and_has_no_locally_generated_password():
    builder, _ = case()
    command = builder.reset_password()
    assert command.argv == (
        DOCKER_EXE,
        "--host",
        PIPE,
        "exec",
        "-i",
        "--user",
        "elasticsearch",
        "a" * 64,
        "/usr/share/elasticsearch/bin/elasticsearch-reset-password",
        "--auto",
        "--batch",
        "--silent",
        "--username",
        "elastic",
        "--url",
        "https://localhost:9200",
    )
    assert command.private_stdin == b""
    assert not hasattr(command, "password")
    with pytest.raises(module().BootstrapError):
        builder.reset_password()


@pytest.mark.parametrize("ending", [b"", b"\n", b"\r\n"])
def test_reset_decodes_only_actual_private_capture_once(ending):
    builder, _ = case()
    command = builder.reset_password()
    captured = b'Synthetic-tool-pass!"\\'
    password = builder.decode_reset(command, 0, captured + ending)
    assert type(password) is SecretStr
    assert password.get_secret_value() == captured.decode()
    assert captured.decode() not in repr(password)
    config = builder.authenticate(password).private_stdin.decode().splitlines()[0]
    assert json.loads(config.split(" = ", 1)[1]) == "elastic:" + captured.decode()
    with pytest.raises(module().BootstrapError, match="bootstrap_response_unknown"):
        builder.decode_reset(command, 0, captured)


@pytest.mark.parametrize(
    ("exit_code", "captured"),
    [
        (1, b"Synthetic-tool-password"),
        (False, b"Synthetic-tool-password"),
        (0, b""),
        (0, b"short"),
        (0, b"x" * 129),
        (0, b"x" * 20 + b"\n\n"),
        (0, b"Password changed\nSynthetic-tool-password\n"),
        (0, b" Synthetic-tool-password"),
        (0, b"Synthetic-tool-password\x00"),
        (0, b"Synthetic-tool-password\xff"),
    ],
    ids=[
        "exit",
        "bool-exit",
        "empty",
        "short",
        "long",
        "extra-newline",
        "banner",
        "space",
        "nul",
        "utf8",
    ],
)
def test_unknown_reset_capture_is_consumed_without_repeating_reset(exit_code, captured):
    builder, _ = case()
    command = builder.reset_password()
    with pytest.raises(module().BootstrapError, match="^bootstrap_response_unknown$"):
        builder.decode_reset(command, exit_code, captured)
    with pytest.raises(module().BootstrapError):
        builder.decode_reset(command, 0, b"Synthetic-tool-password")
    with pytest.raises(module().BootstrapError):
        builder.reset_password()


def test_reset_decoder_rejects_foreign_or_copied_command():
    builder, _ = case()
    other, _ = case()
    command = builder.reset_password()
    for foreign in (replace(command), other.reset_password()):
        with pytest.raises(module().BootstrapError):
            builder.decode_reset(foreign, 0, b"Synthetic-tool-password")
    assert builder.decode_reset(command, 0, b"Synthetic-tool-password")


def test_reset_accepts_official_auto_generated_twenty_character_capture():
    builder, _ = case()
    captured = b"Synthetic20Character"
    assert len(captured) == 20
    decoded = builder.decode_reset(builder.reset_password(), 0, captured + b"\n")
    assert decoded.get_secret_value() == captured.decode()
    assert builder.authenticate(decoded).private_stdin


@pytest.mark.parametrize(
    ("method", "route"),
    [
        ("authenticate", "/_security/_authenticate"),
        ("audit_users", "/_security/user"),
        ("audit_api_keys", "/_security/api_key"),
    ],
)
def test_only_fixed_tls_routes_and_private_auth_config(method, route):
    builder, _ = case()
    command = getattr(builder, method)(PASSWORD)
    assert command.argv[:8] == (
        DOCKER_EXE,
        "--host",
        PIPE,
        "exec",
        "-i",
        "--user",
        "elasticsearch",
        "a" * 64,
    )
    assert command.argv[8:12] == ("/usr/bin/curl", "-q", "--config", "-")
    assert "--cacert" in command.argv
    assert "/usr/share/elasticsearch/config/access-epoch-tls/http/ca.crt" in command.argv
    assert not {"--insecure", "-k", "--location", "--retry", "--proxy"} & set(command.argv)
    assert b'url = "https://localhost:9200' + route.encode() + b'"\n' in command.private_stdin
    assert PASSWORD.get_secret_value().encode() in command.private_stdin
    assert PASSWORD.get_secret_value() not in repr(command)
    assert all(PASSWORD.get_secret_value() not in arg for arg in command.argv)


@pytest.mark.parametrize("role", ["reader", "writer", "collector"])
def test_issue_scope_only_comes_from_existing_permissions_and_consumes_uuid(role):
    builder, permissions = case()
    command = builder.issue_key(PASSWORD, role, ISSUANCE)
    body = payload(command)
    assert body["role_descriptors"] == {role: permissions.descriptor(role)}
    assert body["metadata"] == {
        "ai_workshop_epoch": str(EPOCH),
        "ai_workshop_role": role,
        "ai_workshop_issuance": str(ISSUANCE),
    }
    assert body["name"] == command.key_name
    with pytest.raises(module().BootstrapError):
        builder.issue_key(PASSWORD, role, ISSUANCE)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("docker_executable", "docker.exe"),
        ("docker_endpoint", "tcp://remote:2375"),
        ("container_id", "a" * 12),
        ("container_id", "a" * 64 + " --privileged"),
        ("original_security_absent", False),
        ("original_security_absent", 1),
    ],
)
def test_unverified_binding_shapes_never_build_commands(field, value):
    builder, permissions = case()
    with pytest.raises(module().BootstrapError, match="bootstrap_command_denied"):
        module().BootstrapCommands(replace(builder.binding, **{field: value}), permissions)


@pytest.mark.parametrize(
    "password", ["short", "A" * 32 + '"\nurl="https://remote/', "A" * 32 + " ", "x" * 129]
)
def test_password_controls_and_config_injection_rejected(password):
    builder, _ = case()
    with pytest.raises(module().BootstrapError, match="bootstrap_command_denied"):
        builder.authenticate(SecretStr(password))


def issue_response(command, **changes):
    value = {
        "id": "public-synthetic-id",
        "name": command.key_name,
        "api_key": "synthetic-key-value",
        "encoded": base64.b64encode(b"public-synthetic-id:synthetic-key-value").decode(),
    }
    value.update(changes)
    return response(value)


def test_issue_decode_binds_id_name_and_encoded_without_secret_repr():
    builder, _ = case()
    command = builder.issue_key(PASSWORD, "reader", ISSUANCE)
    issued = builder.decode_issued(command, 0, issue_response(command))
    assert issued.key_id == "public-synthetic-id" and issued.role == "reader"
    assert (
        issued.encoded.get_secret_value()
        == base64.b64encode(b"public-synthetic-id:synthetic-key-value").decode()
    )
    assert "synthetic-key-value" not in repr(issued)
    with pytest.raises(module().BootstrapError):
        builder.decode_issued(command, 0, issue_response(command))


@pytest.mark.parametrize(
    "changes",
    [
        {"id": 3},
        {"name": "other"},
        {"api_key": True},
        {"encoded": "YWJj"},
        {"type": "cross_cluster"},
        {"unknown": "extra"},
        {"expiration": True},
    ],
)
def test_ambiguous_issue_response_is_unknown_and_never_reissued(changes):
    builder, _ = case()
    command = builder.issue_key(PASSWORD, "reader", ISSUANCE)
    with pytest.raises(module().BootstrapError, match="bootstrap_response_unknown"):
        builder.decode_issued(command, 0, issue_response(command, **changes))
    with pytest.raises(module().BootstrapError):
        builder.issue_key(PASSWORD, "reader", ISSUANCE)


@pytest.mark.parametrize(
    "raw",
    [
        b"{}\n201",
        b"{}\n401",
        b'{"api_keys":[],"api_keys":[]}\n200',
        b'{"api_keys":NaN}\n200',
        b"{}junk\n200",
        b"\xff\n200",
        b"x" * 262145,
    ],
    ids=["created", "unauthorized", "duplicate", "nan", "trailing", "utf8", "oversized"],
)
def test_response_framing_duplicate_nonfinite_and_oversized_data_fail_closed(raw):
    builder, _ = case()
    with pytest.raises(module().BootstrapError, match="bootstrap_response_unknown"):
        builder.decode_api_keys(0, raw)


def test_absent_security_path_requires_empty_api_keys_and_only_reserved_builtin_users():
    builder, _ = case()
    assert builder.decode_api_keys(0, response({"api_keys": []})) is None
    user = {
        "username": "elastic",
        "roles": ["superuser"],
        "full_name": None,
        "email": None,
        "metadata": {"_reserved": True},
        "enabled": True,
    }
    assert builder.decode_users(0, response({"elastic": user})) == ("elastic",)
    with pytest.raises(module().BootstrapError):
        builder.decode_api_keys(0, response({"api_keys": [{"id": "historical", "type": "rest"}]}))
    with pytest.raises(module().BootstrapError):
        builder.decode_users(0, response({"elastic": user, "unexpected": user}))


def test_authentication_requires_enabled_reserved_elastic_superuser():
    builder, _ = case()
    value = {
        "username": "elastic",
        "roles": ["superuser"],
        "enabled": True,
        "full_name": None,
        "email": None,
        "metadata": {"_reserved": True},
        "authentication_type": "realm",
        "authentication_realm": {"name": "reserved", "type": "reserved"},
        "lookup_realm": {"name": "reserved", "type": "reserved"},
    }
    assert builder.decode_authenticated(0, response(value)) is None
    with pytest.raises(module().BootstrapError):
        builder.decode_authenticated(0, response({**value, "authentication_type": "api_key"}))


@pytest.mark.parametrize("exit_code", [1, -1, False, None])
def test_nonexact_local_success_never_trusts_valid_response(exit_code):
    builder, _ = case()
    with pytest.raises(module().BootstrapError, match="bootstrap_response_unknown"):
        builder.decode_api_keys(exit_code, response({"api_keys": []}))


def test_forged_or_other_builder_issue_command_cannot_decode_credentials():
    builder, _ = case()
    command = builder.issue_key(PASSWORD, "reader", ISSUANCE)
    other, _ = case()
    for verifier, candidate in ((builder, replace(command)), (other, command)):
        with pytest.raises(module().BootstrapError, match="bootstrap_response_unknown"):
            verifier.decode_issued(candidate, 0, issue_response(command))


def test_lost_issuance_response_consumes_decode_and_builder_never_retries():
    builder, _ = case()
    command = builder.issue_key(PASSWORD, "reader", ISSUANCE)
    with pytest.raises(module().BootstrapError, match="bootstrap_response_unknown"):
        builder.decode_issued(command, 0, b"")
    with pytest.raises(module().BootstrapError):
        builder.decode_issued(command, 0, issue_response(command))
    with pytest.raises(module().BootstrapError):
        builder.issue_key(PASSWORD, "reader", ISSUANCE)


@pytest.mark.parametrize(
    "change",
    [
        {"enabled": False},
        {"enabled": 1},
        {"roles": ["superuser", "superuser"]},
        {"roles": []},
        {"username": "other"},
        {"metadata": {"_reserved": False}},
        {"metadata": {"_reserved": True, "unreviewed": True}},
        {"email": "synthetic@example.invalid"},
    ],
)
def test_absent_security_audit_does_not_accept_altered_reserved_user(change):
    builder, _ = case()
    user = {
        "username": "elastic",
        "roles": ["superuser"],
        "full_name": None,
        "email": None,
        "metadata": {"_reserved": True},
        "enabled": True,
    }
    with pytest.raises(module().BootstrapError, match="bootstrap_response_unknown"):
        builder.decode_users(0, response({"elastic": {**user, **change}}))


def test_unexpected_response_private_text_never_reaches_error_or_credential_repr():
    builder, _ = case()
    raw = b'{"error":"synthetic-secret-never-log"}\n200'
    with pytest.raises(module().BootstrapError) as error:
        builder.decode_users(0, raw)
    assert str(error.value) == "bootstrap_response_unknown"
    assert "synthetic-secret-never-log" not in repr(error.value)


def test_unsupported_role_and_nil_issuance_never_return_issue_command():
    builder, _ = case()
    with pytest.raises(module().BootstrapError, match="bootstrap_command_denied"):
        builder.issue_key(PASSWORD, "superuser", ISSUANCE)
    with pytest.raises(module().BootstrapError, match="bootstrap_command_denied"):
        builder.issue_key(PASSWORD, "reader", UUID(int=0))


def lookup_response(command, permissions, **changes):
    value = {
        "id": "public-key-id",
        "name": command.key_name,
        "type": "rest",
        "creation": 1791446400000,
        "invalidated": False,
        "username": "elastic",
        "realm": "reserved",
        "realm_type": "reserved",
        "metadata": {
            "ai_workshop_epoch": str(EPOCH),
            "ai_workshop_role": "reader",
            "ai_workshop_issuance": str(ISSUANCE),
        },
        "role_descriptors": {"reader": permissions.descriptor("reader")},
    }
    value.update(changes)
    return response({"api_keys": [value]})


def lookup_case():
    builder, permissions = case()
    command = builder.lookup_key(PASSWORD, "reader", ISSUANCE)
    observed = builder.decode_lookup(command, 0, lookup_response(command, permissions))
    return builder, permissions, command, observed


def test_unknown_issuance_lookup_is_exact_name_private_get_and_does_not_reissue_post():
    builder, permissions = case()
    issued = builder.issue_key(PASSWORD, "reader", ISSUANCE)
    with pytest.raises(module().BootstrapError):
        builder.decode_issued(issued, 0, b"")
    command = builder.lookup_key(PASSWORD, "reader", ISSUANCE)
    assert (
        f'url = "https://localhost:9200/_security/api_key?name={issued.key_name}"'
        in command.private_stdin.decode()
    )
    assert b'request = "GET"' in command.private_stdin
    observed = builder.decode_lookup(command, 0, lookup_response(command, permissions))
    assert observed.key_id == "public-key-id" and observed.issuance_id == ISSUANCE
    assert observed.role == "reader" and observed.invalidated is False
    assert not hasattr(observed, "encoded")
    with pytest.raises(module().BootstrapError):
        builder.issue_key(PASSWORD, "reader", ISSUANCE)


def test_lookup_empty_is_explicit_absence_and_inaccessible_is_unknown():
    builder, _ = case()
    command = builder.lookup_key(PASSWORD, "reader", ISSUANCE)
    assert builder.decode_lookup(command, 0, response({"api_keys": []})) is None
    command = builder.lookup_key(PASSWORD, "reader", ISSUANCE)
    with pytest.raises(module().BootstrapError, match="bootstrap_response_unknown"):
        builder.decode_lookup(command, 22, b'{"error":"inaccessible"}\n403')


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "wrong-name"},
        {"type": "cross_cluster"},
        {"id": "id:secret"},
        {"creation": True},
        {"invalidated": 0},
        {"username": "other"},
        {"realm": "native1"},
        {"metadata": {}},
        {"role_descriptors": {}},
        {"expiration": True},
        {"api_key": "private-unexpected"},
        {"realm_type": "file"},
    ],
)
def test_lookup_rejects_wrong_metadata_owner_scope_types_or_secret_fields(changes):
    builder, permissions = case()
    command = builder.lookup_key(PASSWORD, "reader", ISSUANCE)
    with pytest.raises(module().BootstrapError, match="bootstrap_response_unknown"):
        builder.decode_lookup(command, 0, lookup_response(command, permissions, **changes))


def test_lookup_rejects_multiple_matches_and_forged_request_objects():
    builder, permissions = case()
    command = builder.lookup_key(PASSWORD, "reader", ISSUANCE)
    item = json.loads(lookup_response(command, permissions).rsplit(b"\n", 1)[0])["api_keys"][0]
    with pytest.raises(module().BootstrapError):
        builder.decode_lookup(command, 0, response({"api_keys": [item, item]}))
    with pytest.raises(module().BootstrapError):
        builder.decode_lookup(replace(command), 0, lookup_response(command, permissions))


def test_lookup_descriptor_allows_only_documented_enabled_transient_metadata():
    builder, permissions = case()
    descriptor = permissions.descriptor("reader")
    descriptor["transient_metadata"] = {"enabled": True}
    command = builder.lookup_key(PASSWORD, "reader", ISSUANCE)
    observed = builder.decode_lookup(
        command, 0, lookup_response(command, permissions, role_descriptors={"reader": descriptor})
    )
    assert observed is not None
    descriptor["cluster"] = ["all"]
    command = builder.lookup_key(PASSWORD, "reader", ISSUANCE)
    with pytest.raises(module().BootstrapError):
        builder.decode_lookup(
            command,
            0,
            lookup_response(command, permissions, role_descriptors={"reader": descriptor}),
        )


def test_exact_invalidation_is_ids_only_delete_after_matching_observation():
    builder, _, _, observed = lookup_case()
    command = builder.invalidate_key(PASSWORD, observed)
    assert b'request = "DELETE"' in command.private_stdin
    assert payload(command) == {"ids": ["public-key-id"]}
    assert b'url = "https://localhost:9200/_security/api_key"' in command.private_stdin
    with pytest.raises(module().BootstrapError):
        builder.invalidate_key(PASSWORD, observed)
    confirmed = builder.decode_invalidated(
        command,
        0,
        response(
            {
                "invalidated_api_keys": ["public-key-id"],
                "previously_invalidated_api_keys": [],
                "error_count": 0,
            }
        ),
    )
    assert confirmed == "public-key-id"


@pytest.mark.parametrize(
    "value",
    [
        {
            "invalidated_api_keys": ["other"],
            "previously_invalidated_api_keys": [],
            "error_count": 0,
        },
        {"invalidated_api_keys": [], "previously_invalidated_api_keys": [], "error_count": 0},
        {
            "invalidated_api_keys": ["public-key-id"],
            "previously_invalidated_api_keys": ["public-key-id"],
            "error_count": 0,
        },
        {
            "invalidated_api_keys": ["public-key-id"],
            "previously_invalidated_api_keys": [],
            "error_count": 1,
        },
        {
            "invalidated_api_keys": ["public-key-id"],
            "previously_invalidated_api_keys": [],
            "error_count": False,
        },
    ],
)
def test_invalidation_ambiguous_ack_never_confirms_or_retries(value):
    builder, _, _, observed = lookup_case()
    command = builder.invalidate_key(PASSWORD, observed)
    with pytest.raises(module().BootstrapError, match="bootstrap_response_unknown"):
        builder.decode_invalidated(command, 0, response(value))
    with pytest.raises(module().BootstrapError):
        builder.invalidate_key(PASSWORD, observed)


def test_previously_invalidated_exact_id_is_a_valid_idempotent_server_ack():
    builder, _, _, observed = lookup_case()
    command = builder.invalidate_key(PASSWORD, observed)
    assert (
        builder.decode_invalidated(
            command,
            0,
            response(
                {
                    "invalidated_api_keys": [],
                    "previously_invalidated_api_keys": ["public-key-id"],
                    "error_count": 0,
                    "error_details": [],
                }
            ),
        )
        == "public-key-id"
    )


def test_foreign_or_forged_observation_cannot_authorize_invalidation():
    builder, _, _, observed = lookup_case()
    other, _ = case()
    for owner, value in ((builder, replace(observed)), (other, observed)):
        with pytest.raises(module().BootstrapError, match="bootstrap_command_denied"):
            owner.invalidate_key(PASSWORD, value)


def test_lost_invalidation_ack_reconciles_only_exact_invalidated_get_record():
    builder, permissions, _, observed = lookup_case()
    delete = builder.invalidate_key(PASSWORD, observed)
    with pytest.raises(module().BootstrapError):
        builder.decode_invalidated(delete, 0, b"")
    lookup = builder.lookup_key(PASSWORD, "reader", ISSUANCE)
    confirmed = builder.decode_lookup(
        lookup,
        0,
        lookup_response(lookup, permissions, invalidated=True, invalidation=1791446400001),
    )
    assert confirmed.key_id == observed.key_id and confirmed.invalidated is True
    with pytest.raises(module().BootstrapError):
        builder.invalidate_key(PASSWORD, confirmed)


def test_lookup_scope_does_not_coerce_numeric_zero_into_false_privilege_flag():
    builder, permissions = case()
    descriptor = permissions.descriptor("reader")
    descriptor["indices"][0]["allow_restricted_indices"] = 0
    lookup = builder.lookup_key(PASSWORD, "reader", ISSUANCE)
    with pytest.raises(module().BootstrapError):
        builder.decode_lookup(
            lookup, 0, lookup_response(lookup, permissions, role_descriptors={"reader": descriptor})
        )
