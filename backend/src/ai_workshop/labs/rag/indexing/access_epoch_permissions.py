"""Scoped key descriptors derived from the same grammar as RAG index names."""

import re
from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID

from ai_workshop.infrastructure.search.access_credentials import AccessCredentialError, ServiceRole
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, canonical_recovery_targets

READ_METHODS = frozenset(
    {
        "info",
        "resolve_index",
        "get",
        "get_mapping",
        "get_alias",
        "get_settings",
        "search",
        "count",
        "open_point_in_time",
        "close_point_in_time",
        "health",
        "nodes_info",
        "nodes_stats",
        "cluster_state",
    }
)
WRITE_METHODS = READ_METHODS | {"create", "bulk", "refresh", "update_aliases"}
CLUSTER_METHODS = frozenset({"info", "health", "nodes_info", "nodes_stats", "cluster_state"})


class IndexPrivileges(TypedDict):
    names: list[str]
    privileges: list[str]
    allow_restricted_indices: bool


class RoleDescriptor(TypedDict):
    cluster: list[str]
    indices: list[IndexPrivileges]
    applications: list[object]
    run_as: list[str]
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class AccessEpochPermissions:
    prefix: str
    namespaces: tuple[tuple[UUID, UUID | None], ...]

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,90}", self.prefix) is None or not self.namespaces:
            raise AccessCredentialError("elasticsearch_capability_required")
        if len(set(self.namespaces)) != len(self.namespaces):
            raise AccessCredentialError("elasticsearch_capability_required")

    @property
    def aliases(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                IndexDescriptor(1, "cosine").active_alias(
                    self.prefix, profile, document_processing_profile_id=processing
                )
                for profile, processing in self.namespaces
            )
        )

    def authorize(self, role: ServiceRole, method: str, indices: tuple[str, ...]) -> None:
        allowed = WRITE_METHODS if role == "writer" else READ_METHODS
        if role not in {"reader", "writer", "collector"} or method not in allowed:
            raise AccessCredentialError("elasticsearch_capability_required")
        if not indices and method not in CLUSTER_METHODS | {"close_point_in_time"}:
            raise AccessCredentialError("elasticsearch_capability_required")
        for name in indices:
            if name in self.aliases:
                continue
            try:
                alias = name[:-36] + "active"
                if alias not in self.aliases:
                    raise ValueError("namespace")
                canonical_recovery_targets(alias, (name,))
            except ValueError:
                raise AccessCredentialError("elasticsearch_capability_required") from None

    def descriptor(self, role: ServiceRole) -> RoleDescriptor:
        if role not in {"reader", "writer", "collector"}:
            raise AccessCredentialError("elasticsearch_capability_required")
        return {
            "cluster": ["monitor"],
            "indices": [
                {
                    "names": [alias.removesuffix("active") + "*" for alias in self.aliases],
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
