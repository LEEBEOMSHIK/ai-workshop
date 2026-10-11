"""Actual route grammar; external runtime probes are synthetic."""

import importlib
from types import SimpleNamespace

import pytest

from tests.unit.labs.rag.indexing.test_access_epoch_control_native import assembly as _assembly
from tests.unit.labs.rag.indexing.test_access_epoch_control_native import (
    source_case as _source_case,
)

assembly = _assembly
source_case = _source_case


def module():
    return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_route_commands")


def test_fixed_route_catalog_contains_exact_twenty_seven_purposes():
    m = module()
    assert len(m.RouteProbeKind) == 27
    names = {x.value for x in m.RouteProbeKind}
    paired = {
        "daemon_id",
        "container",
        "image",
        "volume",
        "network",
        "all_ids",
        "security_config",
        "nodes_info",
        "identity_state",
    }
    assert names == {f"{x}_{side}" for x in paired for side in ("before", "after")} | {
        "host_auth",
        "host_anonymous",
        "host_wrong_ca",
        "guest_dns_auth",
        "guest_ip_auth",
        "guest_dns_anonymous",
        "guest_ip_anonymous",
        "transport_certificate",
        "transport_no_certificate",
    }


async def test_static_constructor_does_not_require_late_epoch_or_final_cap(assembly):
    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext

    context = NativeControlContext(**assembly.args)
    commands = module().NativeRouteCommands(context)
    assert commands.context is context
    assert context.epoch is None and context.final is None
    assert assembly.db.statements == []


def test_caller_context_shape_is_not_a_route_source():
    with pytest.raises(ValueError, match="^native_route_unverified$"):
        module().NativeRouteCommands(SimpleNamespace())


@pytest.mark.parametrize("purpose", ["host_auth", True, None, {}, []])
async def test_runtime_route_kind_rejects_untyped_selector_before_io(assembly, purpose):
    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext

    commands = module().NativeRouteCommands(NativeControlContext(**assembly.args))
    with pytest.raises(ValueError, match="^native_route_unverified$"):
        commands.command(purpose)
    assert assembly.db.statements == []


async def test_missing_original_runtime_receipt_fails_static_support(assembly):
    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext

    commands = module().NativeRouteCommands(NativeControlContext(**assembly.args))
    with pytest.raises(ValueError, match="^native_route_unsupported$"):
        commands.assert_supported()
    assert assembly.db.statements == []


async def support_commands(assembly, monkeypatch, packet=None):
    import json

    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext

    m = module()
    commands = m.NativeRouteCommands(NativeControlContext(**assembly.args))
    calls = []
    monkeypatch.setattr(m, "_binary_sha", lambda: "a" * 64)
    monkeypatch.setattr(m, "_python_sha", lambda: "b" * 64)
    packet = (
        packet
        if packet is not None
        else {"schema_version": 1, "java_feature": 25, "source_level": 21, "compiler_present": True}
    )

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(packet).encode(), stderr=b"")

    monkeypatch.setattr(m.subprocess, "run", run)
    return m, commands, calls


async def test_actual_support_producer_issues_only_after_fixed_bounded_probe(assembly, monkeypatch):
    m, commands, calls = await support_commands(assembly, monkeypatch)
    assert await commands.observe_support() is None
    assert commands.assert_supported() is None
    assert len(calls) == 1
    argv, options = calls[0]
    assert argv[-3:] == ("--source", "21", "/dev/stdin")
    assert m.CONTAINER in argv and m._JAVA in argv
    offset = argv.index("/usr/bin/env")
    assert argv[offset : offset + len(m._JAVA_PREFIX)] == m._JAVA_PREFIX
    assert options["shell"] is False and options["input"] is m._SUPPORT_SOURCE
    assert options["timeout"] == 30 and "PATH" not in options["env"]
    assert commands.context.epoch is None and commands.context.journal is None
    assert assembly.db.statements == []
    with pytest.raises(ValueError, match="^native_route_unsupported$"):
        await commands.observe_support()
    assert len(calls) == 1


@pytest.mark.parametrize("alert", ["handshake_failure", "timeout", "eof", ""])
def test_structural_transport_negative_requires_exact_client_certificate_alert(alert):
    import json

    m = module()
    packet = {
        "schema_version": 1,
        "purpose": "transport_no_certificate",
        "code": "client_certificate_rejected",
        "protocol": "TLSv1.2",
        "chain_verified": True,
        "leaf_der_sha256": "a" * 64,
        "fatal_alert": alert,
    }
    with pytest.raises(ValueError, match="^native_route_unverified$"):
        m._decode_wire(
            m.RouteProbeKind.TRANSPORT_NO_CERTIFICATE,
            json.dumps(packet).encode(),
            "a" * 64,
            "key-id",
            "key-name",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("java_feature", True),
        ("java_feature", 20),
        ("source_level", "21"),
        ("compiler_present", False),
        ("extra", "unknown"),
    ],
)
async def test_actual_support_closed_wire_refuses_missing_or_coerced_facts(
    assembly, monkeypatch, field, value
):
    packet = {
        "schema_version": 1,
        "java_feature": 25,
        "source_level": 21,
        "compiler_present": True,
        field: value,
    }
    _, commands, calls = await support_commands(assembly, monkeypatch, packet)
    with pytest.raises(ValueError, match="^native_route_unsupported$"):
        await commands.observe_support()
    with pytest.raises(ValueError, match="^native_route_unsupported$"):
        commands.assert_supported()
    assert len(calls) == 1 and commands.context.epoch is None


async def test_support_receipt_binary_changes_refuse_before_runtime_command(assembly, monkeypatch):
    m, commands, calls = await support_commands(assembly, monkeypatch)
    await commands.observe_support()
    monkeypatch.setattr(m, "_python_sha", lambda: "c" * 64)
    with pytest.raises(ValueError, match="^native_route_unsupported$"):
        commands.assert_supported()
    assert len(calls) == 1


async def test_copied_support_receipt_is_not_an_original_issued_object(assembly, monkeypatch):
    from dataclasses import replace

    _, commands, _ = await support_commands(assembly, monkeypatch)
    await commands.observe_support()
    commands._support = replace(commands._support)
    with pytest.raises(ValueError, match="^native_route_unsupported$"):
        commands.assert_supported()


async def test_support_cannot_move_to_a_new_context_with_same_original_caps(assembly, monkeypatch):
    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext

    _, commands, _ = await support_commands(assembly, monkeypatch)
    await commands.observe_support()
    commands._context = NativeControlContext(**assembly.args)
    with pytest.raises(ValueError, match="^native_route_unsupported$"):
        commands.assert_supported()


@pytest.mark.parametrize("failure", ["digest", "exception", "cancel"])
async def test_last_support_check_failure_never_publishes_or_recovers_receipt(
    assembly, monkeypatch, failure
):
    import asyncio

    m, commands, _ = await support_commands(assembly, monkeypatch)
    reads = 0

    def digest():
        nonlocal reads
        reads += 1
        if reads == 3:
            if failure == "exception":
                raise OSError("must-not-leak")
            if failure == "cancel":
                raise asyncio.CancelledError()
            return "c" * 64
        return "a" * 64

    monkeypatch.setattr(m, "_binary_sha", digest)
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError):
        await commands.observe_support()
    with pytest.raises(ValueError, match="^native_route_unsupported$"):
        commands.assert_supported()
    assert commands._support is None and not commands._support_issued
    assert commands._support_signature is None
    with pytest.raises(ValueError, match="^native_route_unsupported$"):
        await commands.observe_support()
    assert reads == 3 and assembly.db.statements == []


@pytest.mark.parametrize("failure", ["stderr", "exit", "timeout", "duplicate", "cancel"])
async def test_support_failure_never_issues_cap_or_retries(assembly, monkeypatch, failure):
    import asyncio
    import subprocess

    m, commands, calls = await support_commands(assembly, monkeypatch)

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if failure == "timeout":
            raise subprocess.TimeoutExpired("public-runtime-probe", 30)
        if failure == "cancel":
            raise asyncio.CancelledError()
        return SimpleNamespace(
            returncode=1 if failure == "exit" else 0,
            stdout=b'{"schema_version":1,"schema_version":1}' if failure == "duplicate" else b"{}",
            stderr=b"option notice" if failure == "stderr" else b"",
        )

    monkeypatch.setattr(m.subprocess, "run", run)
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else ValueError):
        await commands.observe_support()
    with pytest.raises(ValueError, match="^native_route_unsupported$"):
        commands.assert_supported()
    with pytest.raises(ValueError, match="^native_route_unsupported$"):
        await commands.observe_support()
    assert len(calls) == 1 and commands.context.epoch is None and assembly.db.statements == []


def wire(purpose, *, body=None, status=200, **changes):
    import base64
    import json

    value = {
        "schema_version": 1,
        "purpose": purpose.value,
        "code": "https",
        "protocol": "TLSv1.3",
        "chain_verified": True,
        "leaf_der_sha256": "a" * 64,
        "status": status,
        "body_b64": base64.b64encode(
            json.dumps(
                body
                if body is not None
                else {
                    "authentication_type": "api_key",
                    "enabled": True,
                    "username": "elastic",
                    "api_key": {"id": "key-id", "name": "key-name", "managed_by": "elasticsearch"},
                }
            ).encode()
        ).decode(),
    }
    value.update(changes)
    return json.dumps(value).encode()


@pytest.mark.parametrize("kind", ["HOST_AUTH", "GUEST_DNS_AUTH", "GUEST_IP_AUTH"])
def test_https_structural_success_binds_exact_collector_and_redacts_private_body(kind):
    import json

    m = module()
    purpose = m.RouteProbeKind[kind]
    body, public = m._decode_wire(purpose, wire(purpose), "a" * 64, "key-id", "key-name")
    assert json.loads(body)["api_key"]["id"] == "key-id"
    assert "body_b64" not in public and "key-id" not in json.dumps(public)


@pytest.mark.parametrize(
    "change",
    [
        {"chain_verified": 1},
        {"leaf_der_sha256": "b" * 64},
        {"protocol": "TLSv1.1"},
        {"status": True},
        {"body_b64": "e30=\n"},
        {"extra": True},
    ],
)
def test_https_wire_cannot_coerce_or_substitute_tls_identity(change):
    m = module()
    purpose = m.RouteProbeKind.HOST_AUTH
    with pytest.raises(ValueError, match="^native_route_unverified$"):
        m._decode_wire(purpose, wire(purpose, **change), "a" * 64, "key-id", "key-name")


@pytest.mark.parametrize("kind", ["HOST_ANONYMOUS", "GUEST_DNS_ANONYMOUS", "GUEST_IP_ANONYMOUS"])
def test_anonymous_route_requires_exact_401_security_error(kind):
    m = module()
    purpose = m.RouteProbeKind[kind]
    body = {"status": 401, "error": {"type": "security_exception"}}
    assert (
        m._decode_wire(
            purpose, wire(purpose, body=body, status=401), "a" * 64, "key-id", "key-name"
        )[1]["status"]
        == 401
    )
    with pytest.raises(ValueError):
        m._decode_wire(purpose, wire(purpose, body=body), "a" * 64, "key-id", "key-name")


@pytest.mark.parametrize("alert", ["bad_certificate", "certificate_required"])
def test_transport_negative_is_tls12_and_verified_before_exact_alert(alert):
    import json

    m = module()
    purpose = m.RouteProbeKind.TRANSPORT_NO_CERTIFICATE
    packet = {
        "schema_version": 1,
        "purpose": purpose.value,
        "code": "client_certificate_rejected",
        "protocol": "TLSv1.2",
        "chain_verified": True,
        "leaf_der_sha256": "a" * 64,
        "fatal_alert": alert,
    }
    assert (
        m._decode_wire(purpose, json.dumps(packet).encode(), "a" * 64, "k", "n")[1]["fatal_alert"]
        == alert
    )
    for field, value in [("chain_verified", False), ("protocol", "TLSv1.3")]:
        with pytest.raises(ValueError):
            m._decode_wire(
                purpose, json.dumps({**packet, field: value}).encode(), "a" * 64, "k", "n"
            )


@pytest.mark.parametrize(
    "raw", [b'{"schema_version":1,"schema_version":1}', b'{"schema_version":NaN}', b"[]", b"\xff"]
)
def test_private_wire_rejects_duplicate_nonfinite_or_nonobject_json(raw):
    m = module()
    with pytest.raises(ValueError, match="^native_route_unverified$"):
        m._decode_wire(m.RouteProbeKind.HOST_AUTH, raw, "a" * 64, "k", "n")


@pytest.mark.parametrize("wrong_ca", [False, True])
def test_actual_host_fixed_source_uses_only_project_ca_and_no_auth_before_tls(
    monkeypatch, wrong_ca
):
    """Execute fixed Python helper with external HTTP/SSL/stdio ports replaced."""
    import base64
    import http.client
    import io
    import json
    import ssl
    import sys

    m = module()
    events = []
    packet = {
        "purpose": "host_wrong_ca" if wrong_ca else "host_auth",
        "ca": base64.b64encode(b"synthetic public certificate").decode(),
        "leaf": __import__("hashlib").sha256(b"synthetic peer").hexdigest(),
        "authorization": "" if wrong_ca else "synthetic-private-token",
        "wrong_ca": wrong_ca,
    }

    class Context:
        def __init__(self, protocol):
            events.append(("context", protocol))

        def load_verify_locations(self, **kwargs):
            events.append(("ca", kwargs))

    class Socket:
        def getpeercert(self, **kwargs):
            return b"synthetic peer"

        def version(self):
            return "TLSv1.3"

    class Connection:
        sock = Socket()

        def __init__(self, host, port, **kwargs):
            events.append(("host", host, port))

        def connect(self):
            events.append(("tls",))
            if wrong_ca:
                raise ssl.SSLCertVerificationError("synthetic wrong CA")

        def request(self, method, path, *, headers):
            events.append(("request", method, path, headers))

        def getresponse(self):
            return SimpleNamespace(
                status=200, getheader=lambda _: None, read=lambda _: b'{"synthetic":true}'
            )

        def close(self):
            events.append(("close",))

    monkeypatch.setattr(ssl, "SSLContext", Context)
    monkeypatch.setattr(http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(
        sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(packet).encode()))
    )
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    if wrong_ca:
        with pytest.raises(SystemExit) as stopped:
            exec(compile(m._HOST_SOURCE, "<fixed-native-route-helper>", "exec"), {})
        assert stopped.value.code == 0
        assert not any(event[0] == "request" for event in events)
        assert json.loads(output.getvalue())["code"] == "ca_rejected"
    else:
        exec(compile(m._HOST_SOURCE, "<fixed-native-route-helper>", "exec"), {})
        request = next(event for event in events if event[0] == "request")
        assert events.index(("tls",)) < events.index(request)
        assert request[1:3] == ("GET", "/_security/_authenticate")
        assert request[3]["Authorization"] == "ApiKey synthetic-private-token"
        assert "synthetic-private-token" not in output.getvalue()
    assert events[0] == ("context", ssl.PROTOCOL_TLS_CLIENT)
    assert events[1] == ("ca", {"cadata": "synthetic public certificate"})


async def test_commands_do_not_accept_runtime_authority_from_support_alone(assembly, monkeypatch):
    _, commands, _ = await support_commands(assembly, monkeypatch)
    await commands.observe_support()
    with pytest.raises(ValueError, match="^native_route_unverified$"):
        commands.command(module().RouteProbeKind.HOST_AUTH)
    assert assembly.db.statements == []


def test_closed_route_projection_uses_actual_six_field_route_contract():
    from ai_workshop.labs.rag.indexing.access_epoch_observations import ROUTES, validate_routes

    rows = module()._route_observations({name: {"synthetic": "public"} for name in ROUTES})
    assert validate_routes(rows) is None and len(rows) == 7
    assert next(row for row in rows if row.name == "transport").client_certificate_required is True
    assert next(row for row in rows if row.name == "anonymous").disposition == "excluded"


def test_nonfinite_exponent_is_not_valid_private_json():
    with pytest.raises(ValueError, match="^native_route_unverified$"):
        module()._load(b'{"value":1e999}')


async def test_runtime_uses_once_validated_locals_and_refuses_late_collector_switch(
    monkeypatch, tmp_path
):
    import inspect
    from copy import copy

    from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext
    from tests.unit.labs.rag.indexing.access_epoch_native_fixture import build_native_fixture

    fixture = await build_native_fixture(monkeypatch, tmp_path)
    try:
        await fixture.prepare_history_and_apps(monkeypatch)
        await fixture.capture_original()
        await fixture.retire_original_and_prepare_tls()
        await fixture.start_bootstrap()
        await fixture.prepare_bootstrap_security_and_keys()
        await fixture.capture_bootstrap()
        await fixture.complete_bootstrap()
        await fixture.retire_bootstrap()
        await fixture.start_final()
        await fixture.prepare_final_auth()
        await fixture.capture_final()
        await fixture.complete_final()
        c = fixture.context
        commands = c.route_commands
        names = (
            "repository",
            "journal",
            "native",
            "store",
            "keys",
            "bootstrap_factory",
            "bootstrap_commands",
            "tls",
            "deployment",
            "final_auth_factory",
            "final_authentication",
            "final",
            "final_auth",
            "tls_assets",
            "app_retirement",
            "final_inventory",
            "final_inventory_issuer",
            "final_preservation",
        )
        calls = dict.fromkeys(names, 0)
        for name in names:
            prop = getattr(NativeControlContext, name)
            getter = prop.fget

            def read(self, getter=getter, name=name):
                caller = inspect.currentframe().f_back
                if self is c and caller.f_code.co_name == "_runtime":
                    calls[name] += 1
                return getter(self)

            monkeypatch.setattr(NativeControlContext, name, property(read))
        assert commands._runtime() is c._final_authentication.binding
        first_calls = dict(calls)
        created = fixture.kernel.created
        collector = c._collectors["final"]
        original = collector.assert_issued

        fault = "collector"
        nested = {
            "factory_repository": (c._final_auth_factory, "repository"),
            "factory_journal": (c._final_auth_factory, "journal"),
            "factory_deployment": (c._final_auth_factory, "deployment"),
            "factory_tls": (c._final_auth_factory, "tls"),
            "factory_store": (c._final_auth_factory, "store"),
            "factory_keys": (c._final_auth_factory, "keys"),
            "factory_bootstrap_factory": (c._final_auth_factory, "bootstrap_factory"),
            "factory_bootstrap": (c._final_auth_factory, "bootstrap"),
            "auth_factory": (c._final_authentication, "factory"),
            "auth_final": (c._final_authentication, "final"),
            "auth_repository": (c._final_authentication, "repository"),
            "auth_journal": (c._final_authentication, "journal"),
            "auth_native": (c._final_authentication, "native"),
            "auth_binding": (c._final_authentication, "binding"),
            "key_parent": (c._keys, "parent"),
            "bootstrap_factory_repository": (c._bootstrap_factory, "repository"),
            "bootstrap_factory_journal": (c._bootstrap_factory, "journal"),
            "bootstrap_factory_deployment": (c._bootstrap_factory, "deployment"),
        }

        def checked_then_switch(cap):
            original(cap)
            caller = inspect.currentframe().f_back
            if caller.f_code.co_name == "_runtime":
                if fault == "collector":
                    c._collectors["final"] = copy(collector)
                elif fault in nested:
                    receiver, member = nested[fault]
                    setattr(receiver, member, copy(getattr(receiver, member)))
                else:
                    c._caps[fault] = copy(c._caps[fault])

        monkeypatch.setattr(collector, "assert_issued", checked_then_switch)
        for fault in ("collector", "final_auth", "tls_assets", *nested):
            if fault in nested:
                receiver, member = nested[fault]
                retained = getattr(receiver, member)
            else:
                retained = None if fault == "collector" else c._caps[fault]
            with pytest.raises(ValueError, match="^native_route_unverified$"):
                commands._runtime()
            if fault == "collector":
                c._collectors["final"] = collector
            elif fault in nested:
                receiver, member = nested[fault]
                setattr(receiver, member, retained)
            else:
                c._caps[fault] = retained
        assert fixture.kernel.created == created
        assert first_calls == dict.fromkeys(names, 1)
    finally:
        fixture.close()
