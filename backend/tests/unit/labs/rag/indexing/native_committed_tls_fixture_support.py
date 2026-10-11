"""Ordinary TLS row/file recipe over real crypto and low native transport."""

import base64
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from ai_workshop.infrastructure.local.credential_store_windows import identity_json
from ai_workshop.infrastructure.local.tls_bundle import ProjectTlsBundle, ProjectTlsBundles
from ai_workshop.infrastructure.search.access_credentials import SecuredStoreIdentity
from ai_workshop.labs.rag.indexing.access_epoch_committed_snapshot import _actions
from ai_workshop.labs.rag.indexing.access_epoch_evidence_packets import _stored_control_manifest
from ai_workshop.labs.rag.indexing.access_epoch_models import (
    AccessEpochEventRecord,
    AccessEpochExecutionRecord,
    AccessEpochFloorRecord,
    AccessEpochRecord,
)
from ai_workshop.labs.rag.indexing.access_epoch_repository import AccessEpochReadback
from ai_workshop.labs.rag.indexing.access_epoch_tls_packets import _binding, decode_tls_packet
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    ReservedCutoverAction,
    canonical_json,
    decode_termination_proof,
)
from ai_workshop.labs.rag.indexing.alias_models import AliasRecoveryReceiptRecord
from ai_workshop.labs.rag.indexing.alias_recovery_types import digest, utc_text

FILES = tuple(
    f"{purpose}/{name}"
    for purpose in ("http", "transport")
    for name in ("node.key", "node.crt", "ca.crt")
)
HASHES = (
    "http_ca_sha256",
    "transport_ca_sha256",
    "http_ca_der_sha256",
    "transport_ca_der_sha256",
    "http_leaf_der_sha256",
    "transport_leaf_der_sha256",
)


@dataclass(frozen=True, slots=True, repr=False)
class TlsRecipe:
    graph: Any = field(repr=False)
    action: ReservedCutoverAction = field(repr=False)
    bundle: ProjectTlsBundle = field(repr=False)
    packet: bytes = field(repr=False)
    manifest_json: str = field(repr=False)
    fixed_paths: tuple[str, ...] = field(repr=False)


def prepare_tls(graph: Any, *, fault: str | None = None) -> TlsRecipe:
    store, _, deps, c, material = graph
    epoch_id = UUID(c.epoch.binding.access_epoch_id)
    ipv4 = "172.18.0.2"
    events = sorted(
        (row for key, row in c.db.rows.items() if key[0] is AccessEpochEventRecord),
        key=lambda row: row.sequence,
    )
    tls_pending = next(
        row
        for row in events
        if row.kind == CutoverActionKind.PREPARE_TLS.value and row.outcome == "pending"
    )
    target = sha256(
        canonical_json(
            {
                "preparation_kind": "local_files",
                "schema_version": 1,
                "epoch_id": str(epoch_id),
                "execution_id": c.epoch.binding.execution_id,
                "original_ipv4": ipv4,
                "files": list(FILES),
                "original_deployment_sha256": c.epoch.original.deployment_sha256,
            }
        ).encode()
    ).hexdigest()
    if fault == "wrong_target":
        target = "a" * 64
    scope = sha256(json.dumps([c.epoch.original.daemon_sha256, "ai-workshop"]).encode()).hexdigest()
    if fault == "wrong_scope":
        scope = "b" * 64
    assert fault in (
        None,
        "wrong_target",
        "wrong_scope",
        "pem_der_swapped",
        "row_evidence_mismatch",
    )
    expected = canonical_json(
        {
            "schema_version": 1,
            "submission_id": str(uuid4()),
            "scope_sha256": scope,
            "target_sha256": target,
            "execution_id": str(tls_pending.execution_id),
            "executor_generation": tls_pending.executor_generation,
            "kind": tls_pending.kind,
            "preceding_sequence": tls_pending.action_sequence - 1,
        }
    )
    for event in events:
        if event.action_id == tls_pending.action_id:
            event.expected_json = expected
    execution = next(row for key, row in c.db.rows.items() if key[0] is AccessEpochExecutionRecord)
    action = next(
        row.action
        for row in _actions(events, execution)
        if row.action.kind is CutoverActionKind.PREPARE_TLS
    )
    bundles = ProjectTlsBundles(deps.private)
    now = datetime.now(UTC)
    bundle = bundles.generate(epoch_id, ipv4, now)
    projection = bundles.validate(bundle, epoch_id, ipv4, now)
    materialized = bundles.materialize(bundle, epoch_id, ipv4, now)
    binding = _binding(epoch_id, action, ipv4)
    layers = {
        purpose: {
            name: base64.b64encode(getattr(layer, name)).decode("ascii")
            for name in (
                "ca_certificate_pem",
                "leaf_certificate_pem",
                "leaf_private_key_pem",
                "ca_key_protected",
            )
        }
        for purpose, layer in (("http", bundle.http), ("transport", bundle.transport))
    }
    packet = canonical_json({"binding": binding, "layers": layers}).encode()
    parsed = decode_tls_packet(packet, epoch_id=epoch_id, action=action, original_ipv4=ipv4)
    assert bundles.validate(parsed, epoch_id, ipv4, now) == projection
    public = binding | {
        "http_ca_sha256": projection.http_ca_pem_sha256,
        "transport_ca_sha256": projection.transport_ca_pem_sha256,
        "http_ca_der_sha256": projection.http_ca_der_sha256,
        "transport_ca_der_sha256": projection.transport_ca_der_sha256,
        "http_leaf_der_sha256": projection.http_leaf_der_sha256,
        "transport_leaf_der_sha256": projection.transport_leaf_der_sha256,
        "not_valid_after": utc_text(projection.not_valid_after),
        "dns_sans": ["localhost", "elasticsearch"],
        "ip_sans": ["127.0.0.1", ipv4],
    }
    if fault == "pem_der_swapped":
        public["http_ca_sha256"], public["http_ca_der_sha256"] = (
            public["http_ca_der_sha256"],
            public["http_ca_sha256"],
        )
    manifest_json = canonical_json(public)
    deployment_json = canonical_json(
        {
            "schema_version": 2,
            "kind": "start_secured",
            "epoch_id": str(epoch_id),
            "execution_id": c.epoch.binding.execution_id,
            "original_ipv4": ipv4,
            "tls_public_hashes": {name: public[name] for name in HASHES},
        }
    )
    for event in events:
        if event.outcome == "settled" and event.kind == CutoverActionKind.PREPARE_TLS.value:
            event.manifest_json = manifest_json
        if event.outcome == "settled" and event.kind == CutoverActionKind.START_SECURED.value:
            event.manifest_json = (
                canonical_json(json.loads(deployment_json) | {"observed_at": utc_text(now)})
                if fault == "row_evidence_mismatch"
                else deployment_json
            )
    actions = _actions(events, execution)
    phase = next(row for key, row in c.db.rows.items() if key[0] is AccessEpochRecord).phase
    state = AccessEpochReadback(
        c.epoch,
        phase,
        actions,
        "open" if phase == "verified" else "closed",
        "frozen",
        None,
        c.proof.old_server_stopped_at,
        execution.executor_generation,
    )
    manifests = dict(c.evidence.manifests) | {
        "tls_public_ca": manifest_json,
        "new_deployment": deployment_json,
        "control_settlement": _stored_control_manifest(c.epoch, state),
    }
    facts = json.loads(c.evidence.proof_facts_json)
    for name in ("tls_public_ca", "new_deployment", "control_settlement"):
        facts[name + "_sha256"] = sha256(manifests[name].encode()).hexdigest()
    c.evidence = replace(
        c.evidence, proof_facts_json=canonical_json(facts), manifests=tuple(manifests.items())
    )
    c.proof = decode_termination_proof(facts)
    floor = c.repository.floor_from_verified(c.evidence)
    for key, row in c.db.rows.items():
        if key[0] is AccessEpochRecord:
            row.verified, row.manifests = facts, manifests
        elif key[0] is AccessEpochFloorRecord:
            row.identity = asdict(floor)
        elif key[0] is AliasRecoveryReceiptRecord:
            row.proof, row.proof_sha256 = facts, digest(facts)
    for rows in store.tables.values():
        rows.clear()
    for row in c.db.rows.values():
        store.seed(row)
    anchor = SecuredStoreIdentity(
        floor.store_id,
        floor.cluster_uuid,
        floor.ordinal,
        epoch_id,
        floor.container_id,
        floor.stable_node_id,
        floor.route_sha256,
        floor.auth_sha256,
        floor.config_sha256,
        floor.ca_sha256,
    )
    material.seed(
        str(material.private / "floor.dpapi"), deps.private.protect(identity_json(anchor))
    )
    base = material.private / "tls" / str(epoch_id)
    paths = [str(base / "bundle.dpapi")]
    material.seed(paths[0], deps.private.protect(packet))
    assert tuple(item.relative_path for item in materialized.files) == FILES
    for item in materialized.files:
        path = str(base / "bind" / item.relative_path)
        material.seed(path, item.content)
        paths.append(path)
    assert len(paths) == 7 and not material.retained
    return TlsRecipe(graph, action, bundle, packet, manifest_json, tuple(paths))
