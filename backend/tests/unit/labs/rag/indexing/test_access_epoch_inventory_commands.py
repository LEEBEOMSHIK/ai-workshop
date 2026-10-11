"""Inventory helper grammar; all identities and responses are synthetic."""

import base64
import importlib
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr

from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor


class Issuer:
    def __init__(self, binding: Any) -> None:
        self.binding = binding
        self.revoked = False

    def assert_issued(self, binding: Any) -> Any:
        if self.revoked or binding is not self.binding:
            raise ValueError("synthetic private detail")


@pytest.fixture(params=("original", "bootstrap", "final"))
def case(request: Any) -> Any:
    m = importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_inventory_commands")
    bindings = importlib.import_module(
        "ai_workshop.labs.rag.indexing.access_epoch_inventory_binding"
    )
    profile = uuid4()
    permissions = AccessEpochPermissions("rag", ((profile, None),))
    name = IndexDescriptor(1, "cosine").concrete_index_name("rag", profile, uuid4())
    secret = (
        None
        if request.param == "original"
        else SecretStr(base64.b64encode(b"synthetic-collector:synthetic-secret").decode())
    )
    binding = bindings.InventoryReadBinding(
        request.param, uuid4(), uuid4(), uuid4(), uuid4(), "a" * 64, permissions, secret
    )
    issuer = Issuer(binding)
    return SimpleNamespace(
        m=m, binding=binding, issuer=issuer, builder=m.InventoryCommands(binding, issuer), name=name
    )


def config(command: Any) -> Any:
    return command.private_stdin.decode()


def test_complete_global_metadata_route_includes_strict_system_field(case: Any) -> None:
    assert "metadata.indices.*.system" in config(case.builder.read_cluster("cluster_state"))
    assert "metadata.indices.*.system" not in config(case.builder.read_cluster("listing"))


def test_fixed_routes_and_tls_scope(case: Any) -> None:
    c = case
    for purpose in ("listing", "cluster_info", "cluster_state", "nodes_info", "nodes_docs"):
        command = c.builder.read_cluster(purpose)
        assert "--host" in command.argv
        assert "--proto" in command.argv
        assert c.binding.container_id in command.argv
        assert 'request = "GET"' in config(command)
        if c.binding.phase == "original":
            assert "http://localhost:9200" in config(command)
            assert "Authorization" not in config(command)
            assert "--cacert" not in command.argv
        else:
            assert "https://localhost:9200" in config(command)
            assert "Authorization: ApiKey" in config(command)
            assert "--cacert" in command.argv
            assert c.binding.collector_secret.get_secret_value() not in repr(command)
            assert c.binding.collector_secret.get_secret_value() not in repr(c.binding)
        assert not any("Authorization" in arg for arg in command.argv)


def test_rag_reads_require_physical_scope(case: Any) -> None:
    c = case
    metadata = c.builder.read_index(c.name, "metadata")
    count = c.builder.read_index(c.name, "count")
    assert c.name in config(metadata)
    assert "/_count" in config(count)
    assert "include_defaults=true" in config(metadata)
    alias = c.binding.permissions.aliases[0]
    for name in (alias, "foreign", "*", c.name + "/_delete_by_query", ".security"):
        with pytest.raises(ValueError, match="inventory_command_denied"):
            c.builder.read_index(name, "metadata")


@pytest.mark.parametrize("purpose", ("search", "refresh", "bulk", "http://other", ""))
def test_no_caller_endpoint_or_mutation(case: Any, purpose: Any) -> None:
    with pytest.raises(ValueError, match="inventory_command_denied"):
        case.builder.read_cluster(purpose)
    with pytest.raises(ValueError, match="inventory_command_denied"):
        case.builder.read_index(case.name, purpose)


def test_response_is_one_shot_private_and_status_checked(case: Any) -> None:
    c = case
    command = c.builder.read_cluster("cluster_info")
    result = c.builder.decode(command, c.m.InventoryResponse(0, b'{"synthetic":1}\n200'))
    assert result == b'{"synthetic":1}'
    with pytest.raises(ValueError, match="inventory_response_denied"):
        c.builder.decode(command, c.m.InventoryResponse(0, b"{}\n200"))
    other = c.m.InventoryCommands(c.binding, c.issuer)
    with pytest.raises(ValueError, match="inventory_response_denied"):
        other.decode(command, c.m.InventoryResponse(0, b"{}\n200"))


@pytest.mark.parametrize(
    "output,exit_code",
    (
        (b"{}\n403", 0),
        (b"{}\n200\n", 0),
        (b"{}\n200", 1),
        (b"{}\n200", False),
        (b"", 0),
        (b"{}\n200", -1),
        (b"x" * 262145 + b"\n200", 0),
    ),
    ids=("forbidden", "trailing", "failed", "bool", "empty", "negative", "overflow"),
)
def test_bounded_response_failures_are_body_free(case: Any, output: Any, exit_code: Any) -> None:
    c = case
    command = c.builder.read_cluster("listing")
    with pytest.raises(ValueError, match="^inventory_response_denied$"):
        c.builder.decode(command, c.m.InventoryResponse(exit_code, output))


def test_copied_or_revoked_binding_cannot_issue(case: Any) -> None:
    c = case
    with pytest.raises(ValueError, match="inventory_command_denied"):
        c.m.InventoryCommands(replace(c.binding), c.issuer)
    command = c.builder.read_cluster("listing")
    c.issuer.revoked = True
    with pytest.raises(ValueError, match="inventory_command_denied"):
        c.builder.read_cluster("listing")
    with pytest.raises(ValueError, match="inventory_response_denied"):
        c.builder.decode(command, c.m.InventoryResponse(0, b"{}\n200"))


@pytest.mark.parametrize(
    "phase,secret",
    (
        ("other", None),
        ("original", SecretStr("x")),
        ("bootstrap", None),
        ("final", SecretStr("not-base64")),
    ),
)
def test_bad_security_mode_never_falls_back(case: Any, phase: Any, secret: Any) -> None:
    c = case
    value = replace(c.binding, phase=phase, collector_secret=secret)
    with pytest.raises(ValueError, match="inventory_command_denied"):
        c.m.InventoryCommands(value, Issuer(value))


@pytest.mark.parametrize(
    "field,value", (("argv", ("foreign.exe",)), ("private_stdin", b"private altered input"))
)
def test_mutated_same_object_cannot_be_executed(case: Any, field: Any, value: Any) -> None:
    c = case
    command = c.builder.read_cluster("listing")
    object.__setattr__(command, field, value)
    with pytest.raises(ValueError, match="^inventory_command_denied$"):
        c.builder.assert_issued(command)
