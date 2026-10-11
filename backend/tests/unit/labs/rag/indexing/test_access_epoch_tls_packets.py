"""Pure synthetic-byte decoder tests; no TLS generation, file/DPAPI/SQL/native I/O."""

import base64
import importlib
import json
from dataclasses import replace
from types import ModuleType
from typing import Any
from uuid import UUID, uuid4

import pytest

from ai_workshop.infrastructure.local.tls_bundle import ProjectTlsBundle, TlsLayer
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    ReservedCutoverAction,
    canonical_json,
)


def module() -> ModuleType:
    name = "ai_workshop.labs.rag.indexing.access_epoch_tls_packets"
    assert importlib.util.find_spec(name) is not None, "phase-neutral decoder missing"
    return importlib.import_module(name)


def sample() -> tuple[UUID, ReservedCutoverAction, str, dict[str, Any]]:
    epoch, execution, generation = uuid4(), uuid4(), str(uuid4())
    expected = {
        "schema_version": 1,
        "submission_id": str(uuid4()),
        "scope_sha256": "a" * 64,
        "target_sha256": "b" * 64,
        "execution_id": str(execution),
        "executor_generation": generation,
        "kind": "prepare_tls",
        "preceding_sequence": 6,
    }
    action = ReservedCutoverAction(
        uuid4(),
        execution,
        7,
        CutoverActionKind.PREPARE_TLS,
        ControlExpectedIdentity(canonical_json(expected), 6),
        generation,
    )
    ipv4 = "172.28.0.2"
    data = {
        "binding": {
            "schema_version": 1,
            "preparation_kind": "local_files",
            "epoch_id": str(epoch),
            "execution_id": str(execution),
            "action_id": str(action.action_id),
            "executor_generation": generation,
            "expected": action.expected.identity_json,
            "original_ipv4": ipv4,
        },
        "layers": {
            purpose: {
                name: base64.b64encode((purpose + ":" + name).encode()).decode()
                for name in (
                    "ca_certificate_pem",
                    "leaf_certificate_pem",
                    "leaf_private_key_pem",
                    "ca_key_protected",
                )
            }
            for purpose in ("http", "transport")
        },
    }
    return epoch, action, ipv4, data


def raw(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def test_decodes_actual_closed_packet_shape_as_ordinary_data() -> None:
    epoch, action, ipv4, data = sample()
    bundle = module().decode_tls_packet(
        raw(data), epoch_id=epoch, action=action, original_ipv4=ipv4
    )
    assert type(bundle) is ProjectTlsBundle and type(bundle.http) is TlsLayer
    assert bundle.epoch_id is epoch and bundle.original_ipv4 == ipv4
    assert bundle.http.leaf_private_key_pem == b"http:leaf_private_key_pem"
    assert bundle.transport.ca_key_protected == b"transport:ca_key_protected"
    assert "private_key" not in repr(bundle)
    assert "secret" not in repr(bundle)


@pytest.mark.parametrize(
    "change",
    [
        "top_extra",
        "top_missing",
        "binding_extra",
        "binding_missing",
        "binding_schema_bool",
        "binding_schema_float",
        "preparation_kind",
        "epoch",
        "execution",
        "action",
        "generation",
        "address",
        "expected",
        "time_field",
        "layer_missing",
        "layer_extra",
        "layer_not_object",
        "field_missing",
        "field_extra",
        "field_number",
        "field_bool",
        "base64_invalid",
        "base64_noncanonical",
        "field_empty",
        "field_oversize",
        "expected_duplicate",
        "expected_noncanonical",
        "expected_schema_bool",
        "expected_sequence_bool",
        "expected_foreign_execution",
        "expected_foreign_generation",
        "expected_wrong_kind",
        "expected_uuid_noncanonical",
        "expected_hash_uppercase",
        "expected_extra_time",
    ],
)
def test_closed_schema_and_canonical_bytes_deny(change: str) -> None:
    epoch, action, ipv4, data = sample()
    binding, layers = data["binding"], data["layers"]
    field = layers["http"]
    if change == "top_extra":
        data["extra"] = None
    elif change == "top_missing":
        del data["binding"]
    elif change == "binding_extra":
        binding["extra"] = 0
    elif change == "binding_missing":
        del binding["action_id"]
    elif change == "binding_schema_bool":
        binding["schema_version"] = True
    elif change == "binding_schema_float":
        binding["schema_version"] = 1.0
    elif change == "preparation_kind":
        binding["preparation_kind"] = "remote"
    elif change in {"epoch", "execution", "action"}:
        binding[change + "_id"] = str(uuid4())
    elif change == "generation":
        binding["executor_generation"] = str(uuid4())
    elif change == "address":
        binding["original_ipv4"] = "172.28.0.3"
    elif change == "expected":
        binding["expected"] = "{}"
    elif change == "time_field":
        binding["observed_at"] = "2026-10-09T00:00:00Z"
    elif change == "layer_missing":
        del layers["transport"]
    elif change == "layer_extra":
        layers["other"] = field
    elif change == "layer_not_object":
        layers["http"] = []
    elif change == "field_missing":
        del field["ca_key_protected"]
    elif change == "field_extra":
        field["other"] = "AA=="
    elif change == "field_number":
        field["ca_key_protected"] = 1
    elif change == "field_bool":
        field["ca_key_protected"] = True
    elif change == "base64_invalid":
        field["ca_key_protected"] = "?"
    elif change == "base64_noncanonical":
        field["ca_key_protected"] = "Zh=="
    elif change == "field_empty":
        field["ca_key_protected"] = ""
    elif change == "field_oversize":
        field["ca_key_protected"] = base64.b64encode(b"x" * 16385).decode()
    else:
        expected = json.loads(action.expected.identity_json)
        if change == "expected_duplicate":
            encoded = action.expected.identity_json[:-1] + ',"schema_version":1}'
        elif change == "expected_noncanonical":
            encoded = json.dumps(expected)
        else:
            if change == "expected_schema_bool":
                expected["schema_version"] = True
            elif change == "expected_sequence_bool":
                expected["preceding_sequence"] = True
            elif change == "expected_foreign_execution":
                expected["execution_id"] = str(uuid4())
            elif change == "expected_foreign_generation":
                expected["executor_generation"] = str(uuid4())
            elif change == "expected_wrong_kind":
                expected["kind"] = "start_secured"
            elif change == "expected_uuid_noncanonical":
                expected["submission_id"] = "{" + expected["submission_id"] + "}"
            elif change == "expected_hash_uppercase":
                expected["target_sha256"] = "A" * 64
            elif change == "expected_extra_time":
                expected["created_at"] = "2026-10-09T00:00:00Z"
            encoded = canonical_json(expected)
        action = replace(action, expected=replace(action.expected, identity_json=encoded))
        binding["expected"] = encoded
    with pytest.raises(ValueError, match="^tls_packet_data_invalid$"):
        module().decode_tls_packet(raw(data), epoch_id=epoch, action=action, original_ipv4=ipv4)


@pytest.mark.parametrize(
    "change",
    [
        "whitespace",
        "bom",
        "invalid_utf8",
        "trailing",
        "duplicate",
        "nan",
        "infinity",
        "float",
        "empty",
        "oversize",
    ],
)
def test_wire_is_exact_bounded_utf8(change: str) -> None:
    epoch, action, ipv4, data = sample()
    packet = raw(data)
    if change == "whitespace":
        packet += b" "
    elif change == "bom":
        packet = b"\xef\xbb\xbf" + packet
    elif change == "invalid_utf8":
        packet = b"\xff"
    elif change == "trailing":
        packet += b"{}"
    elif change == "duplicate":
        packet = packet[:-1] + b',"layers":' + raw(data["layers"]) + b"}"
    elif change == "nan":
        packet = packet.replace(b'"schema_version":1', b'"schema_version":NaN')
    elif change == "infinity":
        packet = packet.replace(b'"schema_version":1', b'"schema_version":Infinity')
    elif change == "float":
        packet = packet.replace(b'"schema_version":1', b'"schema_version":1e0')
    elif change == "empty":
        packet = b""
    elif change == "oversize":
        packet = b"x" * 131073
    with pytest.raises(ValueError, match="^tls_packet_data_invalid$"):
        module().decode_tls_packet(packet, epoch_id=epoch, action=action, original_ipv4=ipv4)


class Text(str):
    pass


class Bytes(bytes):
    pass


@pytest.mark.parametrize(
    "change",
    [
        "raw_subclass",
        "address_subclass",
        "address_loopback",
        "address_multicast",
        "address_linklocal",
        "address_unspecified",
        "epoch_zero",
        "epoch_bool",
        "execution_bool",
        "action_zero",
        "sequence_bool",
        "preceding_bool",
        "sequence_mismatch",
        "generation_subclass",
        "expected_subclass",
        "expected_sequence_negative",
        "kind_string",
        "wrong_kind",
    ],
)
def test_expected_inputs_have_exact_types_and_consistent_data(change: str) -> None:
    epoch, action, ipv4, data = sample()
    packet = raw(data)
    if change == "raw_subclass":
        packet = Bytes(packet)
    elif change == "address_subclass":
        ipv4 = Text(ipv4)
    elif change == "address_loopback":
        ipv4 = "127.0.0.1"
    elif change == "address_multicast":
        ipv4 = "224.0.0.1"
    elif change == "address_linklocal":
        ipv4 = "169.254.1.2"
    elif change == "address_unspecified":
        ipv4 = "0.0.0.0"
    elif change == "epoch_zero":
        epoch = UUID(int=0)
    elif change == "epoch_bool":
        object.__setattr__(epoch, "int", True)
    elif change == "execution_bool":
        object.__setattr__(action.execution_id, "int", True)
    elif change == "action_zero":
        action = replace(action, action_id=UUID(int=0))
    elif change == "sequence_bool":
        action = replace(action, sequence=True)
    elif change == "preceding_bool":
        action = replace(action, expected=replace(action.expected, preceding_sequence=True))
    elif change == "sequence_mismatch":
        action = replace(action, sequence=8)
    elif change == "generation_subclass":
        action = replace(action, executor_generation=Text(action.executor_generation))
    elif change == "expected_subclass":
        action = replace(
            action,
            expected=replace(action.expected, identity_json=Text(action.expected.identity_json)),
        )
    elif change == "expected_sequence_negative":
        action = replace(action, expected=replace(action.expected, preceding_sequence=-1))
    elif change == "kind_string":
        action = replace(action, kind="prepare_tls")  # type: ignore[arg-type]
    elif change == "wrong_kind":
        action = replace(action, kind=CutoverActionKind.START_SECURED)
    with pytest.raises(ValueError, match="^tls_packet_data_invalid$"):
        module().decode_tls_packet(packet, epoch_id=epoch, action=action, original_ipv4=ipv4)


def test_per_field_limit_accepts_exact_boundary_without_crypto_authority() -> None:
    epoch, action, ipv4, data = sample()
    data["layers"]["http"]["ca_key_protected"] = base64.b64encode(b"x" * 16384).decode()
    value = module().decode_tls_packet(raw(data), epoch_id=epoch, action=action, original_ipv4=ipv4)
    assert len(value.http.ca_key_protected) == 16384
    # Bytes are deliberately not a real certificate or DPAPI packet.
    assert not hasattr(value, "assert_issued")
