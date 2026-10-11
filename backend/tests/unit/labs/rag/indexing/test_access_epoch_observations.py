"""Proof production requires every ingress and unchanged original index identities."""

from dataclasses import replace

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_observations import (
    IndexObservation,
    RouteObservation,
    validate_preservation,
    validate_routes,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError


def routes():
    return tuple(
        RouteObservation(
            name,
            "admitted" if name in {"host_http", "guest_http"} else "excluded",
            True,
            True,
            name == "transport",
            "a" * 64,
        )
        for name in (
            "host_http",
            "guest_http",
            "http_profiles",
            "transport",
            "remote_cluster",
            "relay",
            "anonymous",
        )
    )


def test_omitted_route_and_transport_without_client_certificate_cannot_verify():
    validate_routes(routes())
    with pytest.raises(AliasRecoveryError):
        validate_routes(routes()[:-1])
    observations = tuple(
        replace(r, disposition="admitted", client_certificate_required=False)
        if r.name == "transport"
        else r
        for r in routes()
    )
    with pytest.raises(AliasRecoveryError):
        validate_routes(observations)


def test_admitted_guest_direct_ip_requires_tls_and_authentication():
    for change in ({"tls_verified": False}, {"authentication_verified": False}):
        observations = tuple(
            replace(r, **change) if r.name == "guest_http" else r for r in routes()
        )
        with pytest.raises(AliasRecoveryError):
            validate_routes(observations)


def test_same_name_with_replaced_index_uuid_is_not_preservation():
    before = (IndexObservation("synthetic-index", "original-uuid", 7, "a" * 64, "b" * 64),)
    validate_preservation(before, before)
    for change in ({"uuid": "replaced"}, {"count": 8}, {"settings_sha256": "c" * 64}):
        with pytest.raises(AliasRecoveryError):
            validate_preservation(before, (replace(before[0], **change),))
