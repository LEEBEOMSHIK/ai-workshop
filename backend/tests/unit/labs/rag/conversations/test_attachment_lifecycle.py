from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.conversations.attachment_lifecycle import (
    assess_attachment_cleanup,
    reconcile_deleted_attachments,
)
from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity


def test_finished_job_status_cannot_substitute_for_writer_proof():
    decision = assess_attachment_cleanup(
        upload_terminated=False,
        turns_terminated=True,
        jobs_present=True,
        resources=(),
        shared_reference=False,
        inventory_complete=True,
    )
    assert decision.state == "cleanup_waiting"
    assert "upload_termination_unconfirmed" in decision.blockers
    assert "ingestion_termination_unconfirmed" in decision.blockers


def test_provenance_and_shared_references_retain_the_original():
    resource = ResourceIdentity("rag", "projection", uuid4(), 1)
    decision = assess_attachment_cleanup(
        upload_terminated=True,
        turns_terminated=True,
        jobs_present=False,
        resources=(resource,),
        shared_reference=True,
        inventory_complete=True,
    )
    assert decision.state == "cleanup_waiting"
    assert "source_resources_remaining" in decision.blockers
    assert "shared_reference_remaining" in decision.blockers


def test_missing_inventory_and_turn_termination_fail_closed():
    decision = assess_attachment_cleanup(
        upload_terminated=True,
        turns_terminated=False,
        jobs_present=False,
        resources=(),
        shared_reference=False,
        inventory_complete=False,
    )
    assert decision.state == "cleanup_waiting"
    assert set(decision.blockers) == {"inventory_incomplete", "turn_termination_unconfirmed"}


def test_candidate_requires_complete_empty_inventory_and_joined_writers():
    decision = assess_attachment_cleanup(
        upload_terminated=True,
        turns_terminated=True,
        jobs_present=False,
        resources=(),
        shared_reference=False,
        inventory_complete=True,
    )
    assert decision.state == "cleanup_candidate" and decision.blockers == ()


@pytest.mark.asyncio
async def test_deleted_attachment_reconciles_unknown_then_joined_without_deleting():
    now = datetime.now(UTC)
    conversation = SimpleNamespace(id=uuid4(), owner_id=uuid4(), deleted_at=now)
    row = SimpleNamespace(
        cleanup_requested_at=None,
        document_id=None,
        planned_document_id=None,
        asset_version_id=None,
        planned_version_id=None,
        intake_id=None,
        upload_terminated_at=None,
        cleanup_state="retained",
        cleanup_blockers=[],
        cleanup_checked_at=None,
    )
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])),
        scalar=AsyncMock(return_value=uuid4()),
    )
    await reconcile_deleted_attachments(session, conversation)
    assert row.cleanup_state == "cleanup_waiting"
    assert set(row.cleanup_blockers) == {
        "upload_termination_unconfirmed",
        "turn_termination_unconfirmed",
    }
    assert row.cleanup_requested_at == now and row.cleanup_checked_at is not None
    row.upload_terminated_at = now
    session.scalar.return_value = None
    await reconcile_deleted_attachments(session, conversation)
    assert row.cleanup_state == "cleanup_candidate" and row.cleanup_blockers == []


@pytest.mark.asyncio
async def test_live_conversation_never_enters_attachment_cleanup():
    session = SimpleNamespace(scalars=AsyncMock())
    await reconcile_deleted_attachments(session, SimpleNamespace(deleted_at=None))
    session.scalars.assert_not_awaited()
