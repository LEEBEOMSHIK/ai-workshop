"""Pure finite auth policy and packet checks, without execution or issuer authority.

Callers must guard the provenance and freshness of expected public identity and
permissions themselves. Successful validation is not an observed capability and
does not establish absence of every unqueried outside grant. No secrets or raw
response metadata are returned.
"""

import json
import math
import re
from fnmatch import fnmatchcase
from typing import Any
from uuid import UUID

from ai_workshop.infrastructure.search.access_credentials import ServiceRole
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.access_epoch_types import canonical_json

_ROLES = ("reader", "writer", "collector")
_CLUSTER_DENIED = ("all", "manage", "manage_security", "manage_api_key", "manage_own_api_key")
_MUTATIONS = (
    "write",
    "manage",
    "delete",
    "delete_index",
    "create_index",
    "index",
    "create",
    "create_doc",
    "maintenance",
)
_BODY_LIMIT = 262144


def _denied() -> ValueError:
    return ValueError("auth_packet_denied")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _constant(value: str) -> None:
    raise ValueError


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError
    return number


def _decode(body: bytes) -> dict[str, Any]:
    if type(body) is not bytes or not 0 < len(body) <= _BODY_LIMIT:
        raise ValueError
    decoded = json.loads(
        body.decode("utf-8", errors="strict"),
        object_pairs_hook=_object,
        parse_constant=_constant,
        parse_float=_finite_float,
    )
    if type(decoded) is not dict:
        raise ValueError
    return decoded


def _policy_inputs(epoch_id: UUID, permissions: AccessEpochPermissions, role: ServiceRole) -> None:
    if (
        type(epoch_id) is not UUID
        or epoch_id.int == 0
        or type(role) is not str
        or role not in _ROLES
        or type(permissions) is not AccessEpochPermissions
        or type(permissions.prefix) is not str
        or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,90}", permissions.prefix) is None
        or type(permissions.namespaces) is not tuple
        or not permissions.namespaces
    ):
        raise ValueError
    for namespace in permissions.namespaces:
        if type(namespace) is not tuple or len(namespace) != 2:
            raise ValueError
        profile, processing = namespace
        if type(profile) is not UUID or profile.int == 0:
            raise ValueError
        if processing is not None and (type(processing) is not UUID or processing.int == 0):
            raise ValueError
    if len(set(permissions.namespaces)) != len(permissions.namespaces):
        raise ValueError


def finite_privilege_matrix(
    epoch_id: UUID, permissions: AccessEpochPermissions, role: ServiceRole
) -> tuple[dict[str, object], dict[str, Any]]:
    """Return fresh ordinary query/expected data for the fixed three-role policy."""
    try:
        _policy_inputs(epoch_id, permissions, role)
        descriptor = permissions.descriptor(role)
        index = descriptor["indices"][0]
        names, required = index["names"], index["privileges"]
        outside = "access-epoch-outside-" + epoch_id.hex
        if any(fnmatchcase(outside, name) for name in names):
            raise ValueError
        denied = ("all",) if role == "writer" else ("all", *_MUTATIONS)
        privileges = sorted(set(required) | set(denied))
        outside_privileges = sorted({"all", "read", "view_index_metadata", *_MUTATIONS})
        # Explicit .security includes restricted indices; .security* would exclude them.
        outside_names = ["*", ".security", outside]
        query: dict[str, object] = {
            "cluster": sorted(set(descriptor["cluster"]) | set(_CLUSTER_DENIED)),
            "index": [
                {"names": names, "privileges": privileges, "allow_restricted_indices": False},
                {
                    "names": outside_names,
                    "privileges": outside_privileges,
                    "allow_restricted_indices": False,
                },
            ],
            "application": [],
        }
        expected = {
            "username": "elastic",
            "has_all_requested": False,
            "cluster": {
                name: name in descriptor["cluster"]
                for name in sorted(set(descriptor["cluster"]) | set(_CLUSTER_DENIED))
            },
            "index": {
                **{name: {p: p in required for p in privileges} for name in names},
                **{name: {p: False for p in outside_privileges} for name in outside_names},
            },
            "application": {},
        }
        return query, expected
    except Exception:
        raise _denied() from None


def validate_authenticated_body(body: bytes, *, key_id: str, key_name: str) -> None:
    """Check a body against already guarded public key identity; retain no data."""
    try:
        if (
            type(key_id) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", key_id) is None
            or type(key_name) is not str
            or not 0 < len(key_name) <= 512
        ):
            raise ValueError
        value = _decode(body)
        if (
            set(value)
            != {
                "username",
                "roles",
                "full_name",
                "email",
                "metadata",
                "enabled",
                "authentication_realm",
                "lookup_realm",
                "authentication_type",
                "api_key",
            }
            or value["username"] != "elastic"
            or value["enabled"] is not True
            or value["authentication_type"] != "api_key"
            or type(value["roles"]) is not list
            or any(type(role) is not str for role in value["roles"])
            or len(value["roles"]) != len(set(value["roles"]))
            or type(value["metadata"]) is not dict
            or any(
                value[name] is not None and type(value[name]) is not str
                for name in ("full_name", "email")
            )
            or value["api_key"] != {"id": key_id, "name": key_name, "managed_by": "elasticsearch"}
        ):
            raise ValueError
        realm = value["authentication_realm"]
        if (
            type(realm) is not dict
            or set(realm) != {"name", "type"}
            or any(type(x) is not str or not x for x in realm.values())
            or realm != value["lookup_realm"]
        ):
            raise ValueError
    except Exception:
        raise _denied() from None


def validate_privileges_body(
    body: bytes, *, epoch_id: UUID, permissions: AccessEpochPermissions, role: ServiceRole
) -> None:
    """Check only the finite matrix; caller-owned evidence supplies provenance."""
    try:
        value = _decode(body)
        expected = finite_privilege_matrix(epoch_id, permissions, role)[1]
        # Canonical equality preserves exact booleans versus integers and floats.
        if canonical_json(value) != canonical_json(expected):
            raise ValueError
    except Exception:
        raise _denied() from None
