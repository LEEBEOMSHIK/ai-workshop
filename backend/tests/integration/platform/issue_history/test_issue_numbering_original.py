"""Original database numbering checks; all test writes use rollback fixtures."""

import asyncio
import os
import re
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.issue_history import schemas as s
from ai_workshop.platform.issue_history.models import Issue
from ai_workshop.platform.issue_history.repository import IssueRepository
from ai_workshop.platform.issue_history.service import IssueHistoryService
from tests.integration.platform.issue_history.test_category_hierarchy_original import category
from tests.integration.platform.issue_history.test_original_database import (
    create_rollback_engine,
    service,
)

__all__ = ["service"]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_ORIGINAL_ISSUES") != "1",
        reason="Explicit original-database rollback verification is required.",
    ),
]


async def test_auto_number_replay_and_category_changes(service: IssueHistoryService) -> None:
    root = await category(service)
    first_category = await category(service, root.id)
    second_category = await category(service, root.id)
    request = s.IssueCreate(
        request_id=uuid4(),
        category_id=first_category.id,
        title="Synthetic automatic numbering verification",
    )
    first = await service.create_issue(request)
    replay = await service.create_issue(request)
    second = await service.create_issue(request.model_copy(update={"request_id": uuid4()}))
    assert re.fullmatch(r"ISSUE-\d{5,}", first.issue_key)
    assert replay.id == first.id and replay.issue_key == first.issue_key
    assert second.id != first.id and second.issue_key != first.issue_key
    assert first.legacy_keys == []
    changed = await service.update_issue(
        first.id,
        s.IssueUpdate(
            request_id=uuid4(),
            expected_revision=first.revision,
            category_id=second_category.id,
            title=first.title,
        ),
    )
    assert changed.issue_key == first.issue_key and changed.id == first.id
    assert (await service.detail(first.issue_key)).id == first.id
    assert (await service.detail(str(first.id))).id == first.id
    assert (await service.list_issues(q=first.issue_key)).items[0].id == first.id


async def test_legacy_alias_lookup_search_and_unique_namespace(
    service: IssueHistoryService,
) -> None:
    root = await category(service)
    child = await category(service, root.id)
    first = await service.create_issue(
        s.IssueCreate(
            request_id=uuid4(),
            category_id=child.id,
            title="Synthetic alias verification",
        )
    )
    second = await service.create_issue(
        s.IssueCreate(
            request_id=uuid4(),
            category_id=child.id,
            title="Synthetic alias conflict",
        )
    )
    alias = f"OLD-{uuid4().hex}"
    reserved_number = f"ISSUE-{uuid4().int}"
    await service.session.execute(
        text(
            "UPDATE issues SET legacy_keys=jsonb_build_array(CAST(:alias AS text), "
            "CAST(:reserved AS text)) WHERE id=:id"
        ),
        {"id": first.id, "alias": alias, "reserved": reserved_number},
    )
    stored = await service.session.get(Issue, first.id)
    assert stored is not None
    await service.session.refresh(stored)
    assert (await service.detail(alias)).id == first.id
    assert (await service.list_issues(q=alias)).items[0].id == first.id
    with pytest.raises(IntegrityError):
        async with service.session.begin_nested():
            await service.session.execute(
                text(
                    "UPDATE issues SET legacy_keys=jsonb_build_array(CAST(:alias AS text)) "
                    "WHERE id=:id"
                ),
                {"id": second.id, "alias": first.issue_key},
            )
    with pytest.raises(IntegrityError):
        async with service.session.begin_nested():
            await service.session.execute(
                text("UPDATE issues SET issue_key=:key WHERE id=:id"),
                {"id": second.id, "key": reserved_number},
            )
    assert (await service.detail(second.id)).issue_key == second.issue_key


async def test_failed_transaction_leaves_no_issue_or_replayed_result(
    service: IssueHistoryService,
) -> None:
    root = await category(service)
    child = await category(service, root.id)
    request = s.IssueCreate(
        request_id=uuid4(), category_id=child.id, title="Synthetic rollback allocator verification"
    )
    async with service.session.begin_nested() as savepoint:
        abandoned = await service.create_issue(request)
        await savepoint.rollback()
    assert await service.session.get(Issue, abandoned.id) is None
    recreated = await service.create_issue(request)
    assert recreated.id != abandoned.id
    assert (await service.detail(recreated.issue_key)).id == recreated.id


async def test_two_connections_serialize_allocator_and_rollback_cleanly() -> None:
    engine = create_rollback_engine()
    task: asyncio.Task[str] | None = None
    try:
        async with engine.connect() as first, engine.connect() as second:
            first_transaction = await first.begin()
            second_transaction = await second.begin()
            try:
                async with (
                    AsyncSession(bind=first) as first_session,
                    AsyncSession(
                        bind=second, join_transaction_mode="create_savepoint"
                    ) as second_session,
                ):
                    first_key = await IssueRepository(first_session).allocate_key()
                    next_key = await IssueRepository(first_session).allocate_key()
                    assert first_key != next_key
                    task = asyncio.create_task(IssueRepository(second_session).allocate_key())
                    await asyncio.sleep(0.2)
                    assert not task.done(), "Second allocator must await the counter row lock."
                    await first_transaction.rollback()
                    result = await asyncio.wait_for(task, timeout=10)
                    # Rollback frees uncommitted reservations; no persistent issue owned them.
                    assert result == first_key
            finally:
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                if first_transaction.is_active:
                    await first_transaction.rollback()
                await second_transaction.rollback()
                assert not first.in_transaction() and not second.in_transaction()
    finally:
        await engine.dispose()
