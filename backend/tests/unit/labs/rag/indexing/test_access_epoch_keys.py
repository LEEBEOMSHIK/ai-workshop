"""Role-specific durable key reservations over the existing fake SQL transport."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    ControlSettlement,
    CutoverActionKind,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError, utc_text
from tests.unit.labs.rag.indexing.test_access_epoch_repository import setup


async def group():
    from ai_workshop.labs.rag.indexing.access_epoch_keys import SqlAlchemyEpochKeyRepository

    db, parent_repo, claim, original = await setup()
    epoch = await parent_repo.acquire(claim, original)
    for kind in CutoverActionKind:
        if kind == CutoverActionKind.START_REGISTERED_APPS:
            continue
        before = await parent_repo.readback(claim)
        sequence = before.actions[-1].event_sequence if before.actions else 0
        parent = await parent_repo.reserve_action(
            epoch, kind, ControlExpectedIdentity("{}", sequence)
        )
        if kind == CutoverActionKind.ISSUE_ROLE_KEY:
            break
        now = datetime.now(UTC)
        manifest = {"container_id": original.container_id}
        if kind == CutoverActionKind.STOP_OLD:
            manifest["finished_at"] = utc_text(now)
        if kind == CutoverActionKind.RETIRE_OLD:
            manifest["retired_at"] = utc_text(now)
        await parent_repo.settle_action(
            parent,
            ControlSettlement(
                parent.action_id,
                parent.execution_id,
                parent.executor_generation,
                "settled",
                canonical_json(manifest),
                now,
            ),
        )
    return db, parent_repo, SqlAlchemyEpochKeyRepository(parent_repo), epoch, parent


async def settle(keys, epoch, action, result="issued"):
    from ai_workshop.labs.rag.indexing.access_epoch_keys import KeyResult

    await keys.settle(
        epoch,
        action,
        KeyResult(
            result,
            f"key-{action.issuance_id.hex}",
            action.role,
            action.issuance_id,
            action.permissions_sha256,
            datetime.now(UTC),
        ),
    )


async def test_completed_keys_can_be_read_for_later_final_auth_without_new_reservations():
    db, parent_repo, keys, epoch, parent = await group()
    for role in ("reader", "writer", "collector"):
        action = await keys.reserve_issue(epoch, parent, role, "c" * 64)
        await settle(keys, epoch, action)
    with pytest.raises(AliasRecoveryError):
        await keys.read_completed(epoch, parent)
    manifest = await keys.complete_manifest(epoch, parent)
    await parent_repo.settle_action(
        parent,
        ControlSettlement(
            parent.action_id,
            parent.execution_id,
            parent.executor_generation,
            "settled",
            canonical_json(manifest),
            datetime.now(UTC),
        ),
    )
    before = await parent_repo.readback(epoch.binding.claim)
    rows = await keys.read_completed(epoch, parent)
    assert {row.action.role for row in rows} == {"reader", "writer", "collector"}
    assert all(row.outcome == "settled" and row.result.result == "issued" for row in rows)
    assert await parent_repo.readback(epoch.binding.claim) == before
    with pytest.raises(AliasRecoveryError):
        await keys.read_completed(epoch, replace(parent, action_id=uuid4()))
    with pytest.raises(AliasRecoveryError):
        await keys.reserve_issue(epoch, parent, "reader", "c" * 64)


async def test_three_roles_have_three_distinct_committed_reservations_before_completion():
    db, parent_repo, keys, epoch, parent = await group()
    assert await keys.complete_manifest(epoch, parent) is None
    for role in ("reader", "writer", "collector"):
        action = await keys.reserve_issue(epoch, parent, role, "c" * 64)
        before = await keys.readback(epoch, parent)
        assert before[-1].action == action and before[-1].outcome == "pending"
        assert await keys.complete_manifest(epoch, parent) is None
        await settle(keys, epoch, action)
    manifest = await keys.complete_manifest(epoch, parent)
    assert manifest is not None and set(manifest["keys"]) == {"reader", "writer", "collector"}
    assert len({row.action.issuance_id for row in await keys.readback(epoch, parent)}) == 3
    assert db.operation.state == "open"


async def test_unknown_reservation_cannot_be_repeated_or_skipped_after_lost_commit_ack():
    db, parent_repo, keys, epoch, parent = await group()
    db.lose_next_commit_response = True
    with pytest.raises(AliasRecoveryError, match="rag_alias_commit_unknown"):
        await keys.reserve_issue(epoch, parent, "reader", "c" * 64)
    rows = await keys.readback(epoch, parent)
    assert len(rows) == 1 and rows[0].outcome == "pending"
    for role in ("reader", "writer"):
        with pytest.raises(AliasRecoveryError, match="rag_alias_claim_conflict"):
            await keys.reserve_issue(epoch, parent, role, "c" * 64)
    await keys.mark_unknown(epoch, rows[0].action)
    assert await keys.complete_manifest(epoch, parent) is None


async def test_inaccessible_issue_requires_exact_invalidation_before_new_uuid_replacement():
    db, parent_repo, keys, epoch, parent = await group()
    issue = await keys.reserve_issue(epoch, parent, "reader", "c" * 64)
    await settle(keys, epoch, issue, "issued_inaccessible")
    with pytest.raises(AliasRecoveryError, match="rag_alias_claim_conflict"):
        await keys.reserve_issue(epoch, parent, "reader", "c" * 64)
    revoke = await keys.reserve_invalidation(
        epoch, parent, issue.issuance_id, f"key-{issue.issuance_id.hex}"
    )
    assert revoke.kind == "invalidate" and revoke.issuance_id == issue.issuance_id
    await settle(keys, epoch, revoke, "invalidated")
    replacement = await keys.reserve_issue(
        epoch, parent, "reader", "c" * 64, replaces=issue.issuance_id
    )
    assert replacement.issuance_id != issue.issuance_id
    assert replacement.replaces_issuance_id == issue.issuance_id
    await settle(keys, epoch, replacement)
    with pytest.raises(AliasRecoveryError, match="rag_alias_claim_conflict"):
        await keys.reserve_issue(epoch, parent, "reader", "c" * 64)


@pytest.mark.parametrize("change", ["role", "permissions", "issuance", "result", "private_key_id"])
async def test_wrong_role_issuance_or_result_cannot_settle(change):
    from ai_workshop.labs.rag.indexing.access_epoch_keys import KeyResult

    db, parent_repo, keys, epoch, parent = await group()
    action = await keys.reserve_issue(epoch, parent, "reader", "c" * 64)
    values = {
        "result": "issued",
        "key_id": "safe-key-id",
        "role": "reader",
        "issuance_id": action.issuance_id,
        "permissions_sha256": "c" * 64,
        "observed_at": datetime.now(UTC),
    }
    if change == "role":
        values["role"] = "writer"
    elif change == "permissions":
        values["permissions_sha256"] = "d" * 64
    elif change == "issuance":
        values["issuance_id"] = uuid4()
    elif change == "result":
        values["result"] = "invalidated"
    else:
        values["key_id"] = "private/body/marker"
    with pytest.raises(AliasRecoveryError, match="rag_alias_claim_conflict"):
        await keys.settle(epoch, action, KeyResult(**values))
    assert (await keys.readback(epoch, parent))[-1].outcome == "pending"


async def test_parent_cannot_settle_empty_or_partial_key_group():
    db, repo, keys, epoch, parent = await group()
    for partial in (False, True):
        if partial:
            action = await keys.reserve_issue(epoch, parent, "reader", "c" * 64)
            await settle(keys, epoch, action)
        with pytest.raises(AliasRecoveryError, match="rag_alias_claim_conflict"):
            await repo.settle_action(
                parent,
                ControlSettlement(
                    parent.action_id,
                    parent.execution_id,
                    parent.executor_generation,
                    "settled",
                    "{}",
                    datetime.now(UTC),
                ),
            )
    assert (await repo.readback(epoch.binding.claim)).actions[-1].outcome == "pending"


async def test_parent_requires_exact_complete_manifest_and_cannot_accept_replaced_ids():
    db, repo, keys, epoch, parent = await group()
    for role in ("reader", "writer", "collector"):
        await settle(keys, epoch, await keys.reserve_issue(epoch, parent, role, "c" * 64))
    manifest = await keys.complete_manifest(epoch, parent)
    assert manifest is not None
    forged = manifest | {
        "keys": {"reader": "unobserved", "writer": "unobserved", "collector": "unobserved"}
    }
    with pytest.raises(AliasRecoveryError, match="rag_alias_claim_conflict"):
        await repo.settle_action(
            parent,
            ControlSettlement(
                parent.action_id,
                parent.execution_id,
                parent.executor_generation,
                "settled",
                canonical_json(forged),
                datetime.now(UTC),
            ),
        )
    await repo.settle_action(
        parent,
        ControlSettlement(
            parent.action_id,
            parent.execution_id,
            parent.executor_generation,
            "settled",
            canonical_json(manifest),
            datetime.now(UTC),
        ),
    )
    assert (await repo.readback(epoch.binding.claim)).actions[-1].outcome == "settled"


@pytest.mark.parametrize("malformed", [None, object(), {"key_id": "private/body/marker"}])
async def test_malformed_result_is_fixed_refusal_before_attribute_access(malformed):
    from ai_workshop.labs.rag.indexing.access_epoch_keys import KeyResult

    db, repo, keys, epoch, parent = await group()
    action = await keys.reserve_issue(epoch, parent, "reader", "c" * 64)
    with pytest.raises(AliasRecoveryError, match="rag_alias_claim_conflict"):
        await keys.settle(epoch, action, cast(KeyResult, malformed))
    assert (await keys.readback(epoch, parent))[-1].outcome == "pending"


async def test_fresh_key_permit_is_exact_object_once_and_absent_after_commit_ack_loss():
    db, repo, keys, epoch, parent = await group()
    action = await keys.reserve_issue(epoch, parent, "reader", "c" * 64)
    with pytest.raises(AliasRecoveryError):
        keys.consume_fresh(replace(action))
    # A copied attempt consumes the nonce; it cannot be used by either object.
    with pytest.raises(AliasRecoveryError):
        keys.consume_fresh(action)
    db, repo, keys, epoch, parent = await group()
    action = await keys.reserve_issue(epoch, parent, "reader", "c" * 64)
    keys.consume_fresh(action)
    with pytest.raises(AliasRecoveryError):
        keys.consume_fresh(action)
    db, repo, keys, epoch, parent = await group()
    db.lose_next_commit_response = True
    with pytest.raises(AliasRecoveryError, match="rag_alias_commit_unknown"):
        await keys.reserve_issue(epoch, parent, "reader", "c" * 64)
    stored = (await keys.readback(epoch, parent))[0].action
    with pytest.raises(AliasRecoveryError):
        keys.consume_fresh(stored)
