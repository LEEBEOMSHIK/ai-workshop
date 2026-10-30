"""Coherent synthetic SQL rows for real committed HTTPS material producers."""

import json
from dataclasses import replace
from hashlib import sha256
from typing import Any
from uuid import UUID

from ai_workshop.labs.rag.indexing.access_epoch_auth_packets import finite_privilege_matrix
from ai_workshop.labs.rag.indexing.access_epoch_keys import KEY_ROLES
from ai_workshop.labs.rag.indexing.access_epoch_models import (
    AccessEpochEventRecord,
    AccessEpochKeyEventRecord,
)
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.access_epoch_types import CutoverActionKind, canonical_json
from ai_workshop.labs.rag.models.document_processing import (
    index_namespace_document_processing_profile_id,
)
from tests.unit.labs.rag.indexing.native_committed_tls_fixture_support import prepare_tls


def prepare_https(graph: Any, *, mismatched_role: str | None = None) -> Any:
    _, _, deps, c, _ = graph
    snapshot = c.claim.snapshot
    permissions = AccessEpochPermissions(
        deps.settings.elasticsearch_index_prefix,
        (
            (
                snapshot.indexing_profile_id,
                index_namespace_document_processing_profile_id(
                    snapshot.document_processing_profile_id
                ),
            ),
        ),
    )
    epoch = UUID(c.epoch.binding.access_epoch_id)
    descriptors = {role: permissions.descriptor(role) for role in KEY_ROLES}
    hashes = {
        role: sha256(canonical_json(value).encode()).hexdigest()
        for role, value in descriptors.items()
    }
    if mismatched_role is not None:
        hashes[mismatched_role] = "f" * 64
    for key, row in c.db.rows.items():
        if key[0] is AccessEpochKeyEventRecord:
            row.permissions_sha256 = hashes[row.role]
            if row.manifest_json is not None:
                raw = json.loads(row.manifest_json)
                raw["permissions_sha256"] = hashes[row.role]
                row.manifest_json = canonical_json(raw)
    parent = next(
        row
        for key, row in c.db.rows.items()
        if key[0] is AccessEpochEventRecord
        and row.kind == CutoverActionKind.ISSUE_ROLE_KEY.value
        and row.outcome == "settled"
    )
    group = json.loads(parent.manifest_json)
    group["permissions"] = hashes
    parent.manifest_json = canonical_json(group)
    policy = {
        "schema_version": 1,
        "epoch_id": str(epoch),
        "execution_id": c.epoch.binding.execution_id,
        "container_id": c.proof.new_container_id,
        "keys": group["keys"],
        "auth_policy": {
            "verification": "finite_privilege_checks_with_issuer_bound_exact_descriptors",
            "authentication_type": "api_key",
            "namespace_patterns": descriptors["writer"]["indices"][0]["names"],
            "descriptors": descriptors,
            "checked_privileges": {
                role: finite_privilege_matrix(epoch, permissions, role)[0] for role in KEY_ROLES
            },
            "writer_manage_includes_index_delete": True,
            "writer_write_includes_document_delete": True,
        },
    }
    manifests = dict(c.evidence.manifests) | {
        "auth_policy": canonical_json(policy),
        "credential_deployment": canonical_json(
            group
            | {
                "epoch_id": str(epoch),
                "ordinal": c.epoch.binding.ordinal,
            }
        ),
    }
    facts = json.loads(c.evidence.proof_facts_json)
    for name in ("auth_policy", "credential_deployment"):
        facts[name + "_sha256"] = sha256(manifests[name].encode()).hexdigest()
    c.evidence = replace(
        c.evidence, manifests=tuple(manifests.items()), proof_facts_json=canonical_json(facts)
    )
    return prepare_tls(graph), permissions
