"""Nonsecret observations checked before constructing linked epoch evidence."""

import re
from dataclasses import dataclass
from typing import Literal

from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError

ROUTES = frozenset(
    {
        "host_http",
        "guest_http",
        "http_profiles",
        "transport",
        "remote_cluster",
        "relay",
        "anonymous",
    }
)


@dataclass(frozen=True, slots=True)
class RouteObservation:
    name: str
    disposition: Literal["admitted", "excluded"]
    tls_verified: bool
    authentication_verified: bool
    client_certificate_required: bool
    evidence_sha256: str


@dataclass(frozen=True, slots=True)
class IndexObservation:
    name: str
    uuid: str
    count: int
    settings_sha256: str
    provenance_sha256: str


def validate_routes(observations: tuple[RouteObservation, ...]) -> None:
    if len(observations) != len(ROUTES) or {r.name for r in observations} != ROUTES:
        raise AliasRecoveryError("rag_alias_proof_invalid")
    for route in observations:
        if (
            route.disposition not in {"admitted", "excluded"}
            or re.fullmatch(r"[0-9a-f]{64}", route.evidence_sha256) is None
            or route.disposition == "admitted"
            and (
                not route.tls_verified
                or not route.authentication_verified
                or route.name == "transport"
                and not route.client_certificate_required
                or route.name in {"remote_cluster", "relay", "anonymous"}
            )
        ):
            raise AliasRecoveryError("rag_alias_proof_invalid")


def validate_preservation(
    before: tuple[IndexObservation, ...], after: tuple[IndexObservation, ...]
) -> None:
    if (
        len({index.name for index in before}) != len(before)
        or len({index.name for index in after}) != len(after)
        or {index.name: index for index in before} != {index.name: index for index in after}
    ):
        raise AliasRecoveryError("rag_alias_proof_invalid")
    for index in before:
        if (
            not index.name
            or not index.uuid
            or type(index.count) is not int
            or index.count < 0
            or any(
                re.fullmatch(r"[0-9a-f]{64}", value) is None
                for value in (index.settings_sha256, index.provenance_sha256)
            )
        ):
            raise AliasRecoveryError("rag_alias_proof_invalid")
