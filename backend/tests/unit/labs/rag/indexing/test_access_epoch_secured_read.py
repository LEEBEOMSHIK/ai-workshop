"""Actual phase repositories/store; only SQL and private transport are fake."""

import base64
import importlib
import json
from copy import copy, deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import SecretStr

from ai_workshop.config import Settings
from ai_workshop.infrastructure.local.credential_store_windows import WindowsCredentialStore
from ai_workshop.infrastructure.search.access_credentials import (
    CredentialEnvelope,
    SecuredStoreIdentity,
)
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from ai_workshop.labs.rag.indexing.access_epoch_evidence_packets import _stored_control_manifest
from ai_workshop.labs.rag.indexing.access_epoch_keys import KEY_ROLES, SqlAlchemyEpochKeyRepository
from ai_workshop.labs.rag.indexing.access_epoch_models import (
    AccessEpochEventRecord,
    AccessEpochFloorRecord,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    canonical_json,
    decode_termination_proof,
)
from ai_workshop.platform.identity.models import UserRecord
from tests.unit.labs.rag.indexing.test_access_epoch_repository import closure_case


class Memory:
    """External DPAPI/file boundary; fixed paths are keys, never host I/O."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.writes = 0

    def protect(self, data: bytes) -> bytes:
        return b"synthetic:" + bytes(x ^ 0xA5 for x in data)

    def unprotect(self, data: bytes) -> bytes:
        assert data.startswith(b"synthetic:")
        return bytes(x ^ 0xA5 for x in data[10:])

    def write(self, path: str, data: bytes) -> None:
        self.files[path] = data
        self.writes += 1

    def read(self, path: str) -> bytes | None:
        return self.files.get(path)

    def remove(self, path: str) -> None:
        self.files.pop(path, None)


def module() -> Any:
    name = "ai_workshop.labs.rag.indexing.access_epoch_secured_read"
    assert importlib.util.find_spec(name) is not None, "secured phase binding missing"
    return importlib.import_module(name)


async def case() -> Any:
    from types import SimpleNamespace

    db, repository, claim, epoch, evidence, _proof = await cast(Any, closure_case)()
    state = await repository.readback(claim)
    settlement = _stored_control_manifest(epoch, state)
    parent = next(x for x in state.actions if x.action.kind == CutoverActionKind.ISSUE_ROLE_KEY)
    credential = json.loads(parent.manifest_json) | {
        "epoch_id": epoch.binding.access_epoch_id,
        "ordinal": epoch.binding.ordinal,
    }
    payload = canonical_json(credential)
    facts = json.loads(evidence.proof_facts_json)
    facts["credential_deployment_sha256"] = sha256(payload.encode()).hexdigest()
    facts["control_settlement_sha256"] = sha256(settlement.encode()).hexdigest()
    manifests = dict(evidence.manifests) | {
        "credential_deployment": payload,
        "control_settlement": settlement,
    }
    evidence = replace(
        evidence, proof_facts_json=canonical_json(facts), manifests=tuple(manifests.items())
    )
    proof = decode_termination_proof(facts)
    floor = repository.floor_from_verified(evidence)
    await repository.mark_verified(epoch, evidence, anchor=floor)
    memory = Memory()
    store = WindowsCredentialStore(PROJECT_ROOT, memory, memory)
    anchor = SecuredStoreIdentity(
        floor.store_id,
        floor.cluster_uuid,
        floor.ordinal,
        UUID(floor.access_epoch_id),
        floor.container_id,
        floor.stable_node_id,
        floor.route_sha256,
        floor.auth_sha256,
        floor.config_sha256,
        floor.ca_sha256,
    )
    store.advance_floor_anchor(anchor)
    for role in KEY_ROLES:
        key_id = credential["keys"][role]
        encoded = base64.b64encode(f"{key_id}:synthetic-{role}".encode()).decode()
        store.put(
            CredentialEnvelope(anchor.epoch_id, anchor.ordinal, role, key_id, SecretStr(encoded))
        )
    settings = cast(Any, Settings)(
        _env_file=None,
        secret_key="synthetic-secret-value-00000000000000",
        rag_index_store_id="rag",
        rag_index_cluster_uuid="cluster",
    )
    keys = SqlAlchemyEpochKeyRepository(repository)
    source = module().NativeSecuredReadSource(settings, repository, store, keys)
    return SimpleNamespace(
        db=db,
        repository=repository,
        claim=claim,
        epoch=epoch,
        evidence=evidence,
        proof=proof,
        memory=memory,
        store=store,
        settings=settings,
        keys=keys,
        source=source,
    )

async def test_verified_binding_reads_committed_material_without_mutation() -> None:
    c = await case()
    before = deepcopy(c.db.rows)
    writes = c.memory.writes
    bound = await c.source.bind_verified(c.claim)
    assert bound.phase == "verified" and bound.ordinal == c.epoch.binding.ordinal
    assert c.source.assert_bound(bound) is None
    await c.source.revalidate(bound)
    assert {
        k: {name: value for name, value in vars(v).items() if name != "_sa_instance_state"}
        for k, v in c.db.rows.items()
    } == {
        k: {name: value for name, value in vars(v).items() if name != "_sa_instance_state"}
        for k, v in before.items()
    }
    assert c.memory.writes == writes
    assert "synthetic-reader" not in repr(bound)


async def test_exact_verified_to_receipted_transition_and_fresh_replay() -> None:
    c = await case()
    bound = await c.source.bind_verified(c.claim)
    await c.repository.close_access_epoch(c.claim, c.proof)
    await c.source.revalidate(bound)
    source = module().NativeSecuredReadSource(c.settings, c.repository, c.store, c.keys)
    assert (await source.bind_verified(c.claim)).phase == "receipted"


@pytest.mark.parametrize(
    "change", ["anchor_missing", "floor", "secret", "key", "settings", "owner"]
)
async def test_current_guard_drift_denies(change: str) -> None:
    c = await case()
    bound = await c.source.bind_verified(c.claim)
    if change == "anchor_missing":
        c.memory.remove(c.store._path("floor.dpapi"))
    elif change == "floor":
        row = next(v for (kind, _), v in c.db.rows.items() if kind is AccessEpochFloorRecord)
        row.identity = row.identity | {"ordinal": row.identity["ordinal"] + 1}
    elif change in {"secret", "key"}:
        path = c.store._path(f"{bound.epoch_id}/reader.dpapi")
        raw = json.loads(c.memory.unprotect(c.memory.files[path]))
        if change == "secret":
            raw["secret"] = base64.b64encode(b"key-reader:different-synthetic").decode()
        else:
            raw["key_id"] = "another-key"
        c.memory.write(path, c.memory.protect(json.dumps(raw).encode()))
    elif change == "settings":
        c.settings.elasticsearch_index_prefix = "foreign"
    else:
        c.db.rows[UserRecord, c.db.actor].role = "member"
    with pytest.raises(ValueError, match="^secured_read_binding_denied$"):
        await c.source.revalidate(bound)


@pytest.mark.parametrize("change", ["copy", "nonce", "foreign", "repository", "ports"])
async def test_exact_issuance_and_input_identity_required(change: str) -> None:
    c = await case()
    bound = await c.source.bind_verified(c.claim)
    if change == "copy":
        bound = copy(bound)
    elif change == "nonce":
        object.__setattr__(bound.nonce, "int", 123)
    elif change == "foreign":
        c.source = module().NativeSecuredReadSource(c.settings, c.repository, c.store, c.keys)
    elif change == "repository":
        c.keys.parent = copy(c.repository)
    else:
        c.store.protection = copy(c.memory)
    with pytest.raises(ValueError, match="^secured_read_binding_denied$"):
        c.source.assert_bound(bound)


@pytest.mark.parametrize("change", ["ordinal_bool", "phase_subclass", "claim_revision_bool"])
async def test_equal_primitive_type_substitution_is_denied(change: str) -> None:
    c = await case()
    bound = await c.source.bind_verified(c.claim)
    if change == "ordinal_bool":
        object.__setattr__(bound, "ordinal", True)
    elif change == "phase_subclass":

        class PhaseCopy(str):
            pass

        object.__setattr__(bound, "phase", PhaseCopy(bound.phase))
    else:
        object.__setattr__(c.claim, "revision", True)
    with pytest.raises(ValueError, match="^secured_read_binding_denied$"):
        c.source.assert_bound(bound)


@pytest.mark.parametrize("operation", ["publication", "revalidation"])
async def test_late_external_read_claim_type_mutation_denies(operation: str) -> None:
    c = await case()
    bound = await c.source.bind_verified(c.claim) if operation == "revalidation" else None
    read = c.memory.read
    changed = False

    def mutate_read(path: str) -> bytes | None:
        nonlocal changed
        result: bytes | None = read(path)
        if not changed:
            changed = True
            object.__setattr__(c.claim, "revision", True)
        return result

    c.memory.read = mutate_read
    with pytest.raises(ValueError, match="^secured_read_binding_denied$"):
        if bound is None:
            await c.source.bind_verified(c.claim)
        else:
            await c.source.revalidate(bound)
    assert changed


@pytest.mark.parametrize("change", ["stored_time", "stored_other_action_body"])
async def test_fresh_control_packet_must_match_committed_packet(change: str) -> None:
    c = await case()
    kind = (
        CutoverActionKind.STOP_OLD if change == "stored_time" else CutoverActionKind.START_BOOTSTRAP
    )
    rows = [
        row
        for (model, _), row in c.db.rows.items()
        if model is AccessEpochEventRecord and row.kind == kind.value and row.outcome == "settled"
    ]
    row = max(rows, key=lambda item: item.sequence)
    if change == "stored_time":
        row.observed_at = datetime.now(UTC) + timedelta(days=1)
    else:
        row.manifest_json = canonical_json({"generation": "changed-synthetic"})
    with pytest.raises(ValueError, match="^secured_read_binding_denied$"):
        await c.source.bind_verified(c.claim)
