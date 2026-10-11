"""Rejecting a forged, ambiguous, or unbound proof is observable behavior."""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_types import (
    AccessEpochBinding,
    VerifiedAccessEpoch,
    decode_termination_proof,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError
from tests.unit.labs.rag.indexing.access_epoch_fixtures import case
from tests.unit.labs.rag.indexing.test_alias_recovery import proof_for


def verified(c):
    return VerifiedAccessEpoch(
        AccessEpochBinding(c.claim, c.facts["access_epoch_id"], c.facts["execution_id"], 1),
        previous_floor=0,
        proof_facts_json=c.facts_json,
        manifests=c.manifests,
        stopped_action_sequence=3,
        retired_action_sequence=4,
    )


def test_v2_canonical_exact_link_and_equal_stop_retirement():
    c = case()
    proof = decode_termination_proof(c.facts)
    proof.validate(c.claim, verified(c), now=c.now)
    assert proof.facts() == c.facts
    assert proof.sha256 == sha256(c.facts_json.encode()).hexdigest()
    assert proof.old_container_id != proof.new_container_id


def test_v1_facts_digest_and_union_remain_unchanged():
    c = case()
    v1 = proof_for(c.claim)
    assert decode_termination_proof(v1.facts()) == v1
    assert decode_termination_proof(v1.facts()).sha256 == v1.sha256


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2.0),
        ("schema_version", "2"),
        ("schema_version", 3),
        ("proof_kind", "local_single_node_controlled_restart"),
        ("gate_revision", True),
        ("minimum_access_epoch", 0),
        ("minimum_access_epoch", "1"),
        ("actor_id", 5),
        ("actor_id", "invalid"),
        ("new_container_id", "B" * 64),
        ("new_container_id", "a" * 64),
        ("new_ephemeral_id", "old"),
        ("stable_node_id", "bad space"),
        ("store_id", "bad/space"),
        ("verified_at", "2026-01-02T00:03:00"),
        ("verified_at", "2026-01-02T09:03:00.000000+09:00"),
        ("new_server_started_at", "2026-01-02T00:00:00.000000+00:00"),
        ("access_verified_at", "2026-01-02T00:00:00.000000+00:00"),
    ],
)
def test_malformed_or_noncausal_v2_is_rejected(field, value):
    c = case()
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        proof = decode_termination_proof(c.facts | {field: value})
        proof.validate(c.claim, verified(c), now=c.now)


def test_every_missing_or_extra_field_is_rejected():
    c = case()
    for field in c.facts:
        facts = dict(c.facts)
        del facts[field]
        with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
            decode_termination_proof(facts)
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        decode_termination_proof(c.facts | {"client_inventory_sha256": "c" * 64})


@pytest.mark.parametrize("change", ["actor", "claim", "floor", "manifest", "sequence", "future"])
def test_linked_epoch_and_live_claim_are_required(change):
    c = case()
    proof = decode_termination_proof(c.facts)
    epoch = verified(c)
    claim, now = c.claim, c.now
    if change == "actor":
        claim = replace(claim, actor_id=claim.request_id)
    elif change == "claim":
        epoch = replace(epoch, binding=replace(epoch.binding, ordinal=2))
    elif change == "floor":
        epoch = replace(epoch, previous_floor=1)
    elif change == "manifest":
        epoch = replace(epoch, manifests=(("daemon_identity", "{}"), *epoch.manifests[1:]))
    elif change == "sequence":
        epoch = replace(epoch, retired_action_sequence=3)
    else:
        now = c.now - timedelta(days=2)
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        proof.validate(claim, epoch, now=now)


@pytest.mark.parametrize("store_id", ["RAG", "rag-store", "0rag", "rag.store"])
def test_store_identifier_uses_existing_binding_grammar(store_id):
    c = case()
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        decode_termination_proof(c.facts | {"store_id": store_id})
