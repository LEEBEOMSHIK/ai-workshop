"""Rebuild the exact finite policy from persisted public facts, without I/O.

The source must separately bind these bytes to evidence, floor and actual key
ledger. Matching ordinary data never grants source or launch authority.
"""

import re
from uuid import UUID

from ai_workshop.infrastructure.search.access_credentials import ServiceRole
from ai_workshop.labs.rag.indexing.access_epoch_auth_packets import _decode, finite_privilege_matrix
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.access_epoch_types import canonical_json
from ai_workshop.labs.rag.models.document_processing import (
    index_namespace_document_processing_profile_id,
)

_ROLES: tuple[ServiceRole, ...] = ("reader", "writer", "collector")


def _denied() -> ValueError:
    return ValueError("persisted_auth_policy_denied")


def _uuid(text: str) -> UUID:
    value = UUID(text)
    if value.int == 0 or str(value) != text:
        raise _denied()
    return value


def decode_committed_auth_policy(
    body: bytes,
    *,
    prefix: str,
    epoch_id: UUID,
    execution_id: UUID,
    container_id: str,
    key_ids: tuple[tuple[ServiceRole, str], ...],
) -> AccessEpochPermissions:
    try:
        if (
            any(type(value) is not UUID or value.int == 0 for value in (epoch_id, execution_id))
            or type(prefix) is not str
            or re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,90}", prefix) is None
            or type(container_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", container_id) is None
            or type(key_ids) is not tuple
            or len(key_ids) != 3
        ):
            raise _denied()
        for pair in key_ids:
            if (
                type(pair) is not tuple
                or len(pair) != 2
                or type(pair[0]) is not str
                or pair[0] not in _ROLES
                or type(pair[1]) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", pair[1]) is None
            ):
                raise _denied()
        if {pair[0] for pair in key_ids} != set(_ROLES) or len({pair[1] for pair in key_ids}) != 3:
            raise _denied()
        value = _decode(body)
        names = value["auth_policy"]["namespace_patterns"]
        if type(names) is not list or not names:
            raise _denied()
        namespaces: list[tuple[UUID, UUID | None]] = []
        for name in names:
            if (
                type(name) is not str
                or not name.startswith(prefix + "-")
                or not name.endswith("-*")
            ):
                raise _denied()
            text = name[len(prefix) + 1 : -2]
            if len(text) == 36:
                namespaces.append((_uuid(text), None))
            elif len(text) == 73 and text[36] == "-":
                processing, profile = _uuid(text[:36]), _uuid(text[37:])
                if index_namespace_document_processing_profile_id(processing) != processing:
                    raise _denied()
                namespaces.append((profile, processing))
            else:
                raise _denied()
        permissions = AccessEpochPermissions(prefix, tuple(namespaces))
        descriptors = {role: permissions.descriptor(role) for role in _ROLES}
        expected: dict[str, object] = {
            "schema_version": 1,
            "epoch_id": str(epoch_id),
            "execution_id": str(execution_id),
            "container_id": container_id,
            "keys": dict(key_ids),
            "auth_policy": {
                "verification": "finite_privilege_checks_with_issuer_bound_exact_descriptors",
                "authentication_type": "api_key",
                "namespace_patterns": descriptors["writer"]["indices"][0]["names"],
                "descriptors": descriptors,
                "checked_privileges": {
                    role: finite_privilege_matrix(epoch_id, permissions, role)[0] for role in _ROLES
                },
                "writer_manage_includes_index_delete": True,
                "writer_write_includes_document_delete": True,
            },
        }
        if canonical_json(value) != canonical_json(expected):
            raise _denied()
        return permissions
    except Exception:
        raise _denied() from None
