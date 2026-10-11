"""Hand-built public observations, without running Docker or a model."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

from ai_workshop.labs.rag.indexing.alias_recovery_types import (
    AliasOperationSnapshot,
    FrozenAliasClaim,
)


def case():
    claim = FrozenAliasClaim(
        AliasOperationSnapshot(
            UUID(int=1),
            "rag",
            "cluster",
            "synthetic-active",
            UUID(int=2),
            UUID(int=3),
            ("synthetic-index",),
            datetime(2026, 1, 1, tzinfo=UTC),
            "legacy_unknown",
        ),
        UUID(int=4),
        UUID(int=5),
        1,
    )
    facts = {
        "request_id": str(claim.request_id),
        "operation_id": str(claim.snapshot.operation_id),
        "actor_id": str(claim.actor_id),
        "access_epoch_id": str(UUID(int=6)),
        "execution_id": str(UUID(int=7)),
        "gate_revision": 1,
        "minimum_access_epoch": 1,
        "schema_version": 2,
        "proof_kind": "local_single_node_access_epoch",
        "store_id": "rag",
        "cluster_uuid": "cluster",
        "stable_node_id": "stable",
        "old_ephemeral_id": "old",
        "new_ephemeral_id": "new",
        "snapshot_sha256": claim.snapshot.sha256,
        "old_container_id": "a" * 64,
        "new_container_id": "b" * 64,
        "old_jvm_start_at": "2025-12-31T00:00:00.000000+00:00",
        "old_server_stopped_at": "2026-01-02T00:00:00.000000+00:00",
        "old_container_retired_at": "2026-01-02T00:00:00.000000+00:00",
        "new_server_started_at": "2026-01-02T00:01:00.000000+00:00",
        "new_jvm_start_at": "2026-01-02T00:01:01.000000+00:00",
        "access_verified_at": "2026-01-02T00:02:00.000000+00:00",
        "verified_at": "2026-01-02T00:03:00.000000+00:00",
    }
    names = (
        "daemon_identity",
        "original_volume_identity",
        "protected_mount",
        "protected_image",
        "old_config",
        "new_config",
        "old_deployment",
        "new_deployment",
        "route_policy",
        "tls_public_ca",
        "auth_policy",
        "credential_deployment",
        "deployment_history",
        "control_settlement",
    )
    # Each immutable synthetic observation has independently computed canonical bytes.
    manifests = tuple((name, '{"generation":"synthetic"}') for name in names)
    for name, payload in manifests:
        facts[name + "_sha256"] = sha256(payload.encode()).hexdigest()
    return SimpleNamespace(
        claim=claim,
        facts=facts,
        manifests=manifests,
        facts_json=json.dumps(facts, sort_keys=True, separators=(",", ":")),
        now=datetime(2026, 1, 3, tzinfo=UTC),
    )
