"""Ordinary TLS packet data decoder; no source, trust or issuer authority.

It never reads files, decrypts/generates material, queries SQL, checks ownership or
imports an active source as a fallback. A caller may fabricate all input data;
successful decoding attests only the documented shape and byte correspondence.
"""

import base64
import json
import re
from ipaddress import IPv4Address
from typing import cast
from uuid import UUID

from ai_workshop.infrastructure.local.tls_bundle import ProjectTlsBundle, TlsLayer
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    ReservedCutoverAction,
    canonical_json,
)

_FIELDS = (
    "ca_certificate_pem",
    "leaf_certificate_pem",
    "leaf_private_key_pem",
    "ca_key_protected",
)
_EXPECTED_KEYS = {
    "schema_version",
    "submission_id",
    "scope_sha256",
    "target_sha256",
    "execution_id",
    "executor_generation",
    "kind",
    "preceding_sequence",
}
_BINDING_KEYS = {
    "schema_version",
    "preparation_kind",
    "epoch_id",
    "execution_id",
    "action_id",
    "executor_generation",
    "expected",
    "original_ipv4",
}
_MAX_PACKET = 131072
_MAX_FIELD = 16384  # Actual ProjectTlsBundles' _bounded limit.
_MAX_SEQUENCE = (1 << 63) - 1


def _invalid() -> ValueError:
    return ValueError("tls_packet_data_invalid")


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise _invalid()
        result[key] = value
    return result


def _noninteger(_value: str) -> None:
    raise _invalid()


def _json(raw: bytes) -> dict[str, object]:
    value: object = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_pairs,
        parse_constant=_noninteger,
        parse_float=_noninteger,
    )
    if type(value) is not dict or canonical_json(value).encode("utf-8") != raw:
        raise _invalid()
    return cast(dict[str, object], value)


def _uuid(value: UUID) -> None:
    if type(value) is not UUID or type(value.int) is not int or not 0 < value.int < 1 << 128:
        raise _invalid()


def _uuid_text(value: object) -> str:
    if type(value) is not str:
        raise _invalid()
    identifier = UUID(value)
    _uuid(identifier)
    if str(identifier) != value:
        raise _invalid()
    return value


def _binding(
    epoch_id: UUID,
    action: ReservedCutoverAction,
    original_ipv4: str,
) -> dict[str, object]:
    _uuid(epoch_id)
    if (
        type(action) is not ReservedCutoverAction
        or type(action.kind) is not CutoverActionKind
        or action.kind is not CutoverActionKind.PREPARE_TLS
        or type(action.expected) is not ControlExpectedIdentity
        or type(action.sequence) is not int
        or not 1 <= action.sequence <= _MAX_SEQUENCE
        or type(action.expected.preceding_sequence) is not int
        or action.expected.preceding_sequence != action.sequence - 1
        or type(action.expected.identity_json) is not str
        or not 0 < len(action.expected.identity_json.encode()) <= 8192
        or type(original_ipv4) is not str
    ):
        raise _invalid()
    _uuid(action.action_id)
    _uuid(action.execution_id)
    _uuid_text(action.executor_generation)
    address = IPv4Address(original_ipv4)
    if (
        str(address) != original_ipv4
        or address.is_loopback
        or address.is_multicast
        or address.is_link_local
        or address.is_unspecified
        or address.is_reserved
    ):
        raise _invalid()
    expected = _json(action.expected.identity_json.encode())
    if (
        set(expected) != _EXPECTED_KEYS
        or type(expected["schema_version"]) is not int
        or expected["schema_version"] != 1
        or type(expected["preceding_sequence"]) is not int
        or expected["preceding_sequence"] != action.expected.preceding_sequence
        or _uuid_text(expected["execution_id"]) != str(action.execution_id)
        or _uuid_text(expected["executor_generation"]) != action.executor_generation
        or type(expected["kind"]) is not str
        or expected["kind"] != action.kind.value
    ):
        raise _invalid()
    _uuid_text(expected["submission_id"])
    for name in ("scope_sha256", "target_sha256"):
        digest = expected[name]
        if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise _invalid()
    return {
        "schema_version": 1,
        "preparation_kind": "local_files",
        "epoch_id": str(epoch_id),
        "execution_id": str(action.execution_id),
        "action_id": str(action.action_id),
        "executor_generation": action.executor_generation,
        "expected": action.expected.identity_json,
        "original_ipv4": original_ipv4,
    }


def decode_tls_packet(
    raw: bytes,
    *,
    epoch_id: UUID,
    action: ReservedCutoverAction,
    original_ipv4: str,
) -> ProjectTlsBundle:
    """Decode data only. Caller expected values do not establish source ownership."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= _MAX_PACKET:
            raise _invalid()
        expected_binding = _binding(epoch_id, action, original_ipv4)
        value = _json(raw)
        if set(value) != {"binding", "layers"}:
            raise _invalid()
        binding, layers = value["binding"], value["layers"]
        if (
            type(binding) is not dict
            or set(binding) != _BINDING_KEYS
            or canonical_json(binding) != canonical_json(expected_binding)
            or type(layers) is not dict
            or set(layers) != {"http", "transport"}
        ):
            raise _invalid()
        parsed: list[TlsLayer] = []
        for purpose in ("http", "transport"):
            layer = layers[purpose]
            if type(layer) is not dict or set(layer) != set(_FIELDS):
                raise _invalid()
            material: list[bytes] = []
            for name in _FIELDS:
                encoded = layer[name]
                if type(encoded) is not str or not 0 < len(encoded) <= 4 * ((_MAX_FIELD + 2) // 3):
                    raise _invalid()
                decoded = base64.b64decode(encoded, validate=True)
                if (
                    not 0 < len(decoded) <= _MAX_FIELD
                    or base64.b64encode(decoded).decode("ascii") != encoded
                ):
                    raise _invalid()
                material.append(decoded)
            parsed.append(TlsLayer(*material))
        return ProjectTlsBundle(epoch_id, original_ipv4, parsed[0], parsed[1])
    except Exception:
        raise _invalid() from None
