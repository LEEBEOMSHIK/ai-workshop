"""Opt-in original database checks; every synthetic write is rolled back.

Run only after migration with AI_WORKSHOP_VERIFY_ORIGINAL_ISSUES=1. No database,
schema, account or persistent fixture is created. Normal test runs skip this file.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import date
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ai_workshop.config import Settings
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.issue_history import schemas as s
from ai_workshop.platform.issue_history.importer import (
    CATEGORY_NAMES,
    CATEGORY_PARENTS,
    ImportDocument,
    ImportManifest,
    SourceEvent,
    SourceIssue,
    apply_import,
    verify_import,
)
from ai_workshop.platform.issue_history.models import IssueDocument
from ai_workshop.platform.issue_history.service import IssueHistoryService
from ai_workshop.shared.db import create_engine
from ai_workshop.shared.errors import AppError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_ORIGINAL_ISSUES") != "1",
        reason="Explicit original-database rollback verification is required.",
    ),
]


def create_rollback_engine() -> AsyncEngine:
    """Reject every outer COMMIT; SAVEPOINT release remains permitted."""
    root = Path(__file__).resolve().parents[5]
    settings = Settings(_env_file=root / ".env")  # type: ignore[call-arg]
    engine = create_engine(settings)

    @sqlalchemy_event.listens_for(engine.sync_engine, "commit")
    def reject_outer_commit(_connection: Connection) -> None:
        raise AssertionError("Original database verification must never COMMIT.")

    return engine


@pytest.fixture
async def service() -> AsyncIterator[IssueHistoryService]:
    engine = create_rollback_engine()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    record = await session.scalar(
                        select(UserRecord)
                        .where(UserRecord.role == UserRole.OWNER, UserRecord.is_active.is_(True))
                        .limit(1)
                    )
                    assert record is not None, "An existing active owner is required."
                    actor = User(
                        id=record.id,
                        display_name=record.display_name,
                        email=record.email,
                        normalized_email=record.normalized_email,
                        password_hash=record.password_hash,
                        role=UserRole.OWNER,
                    )
                    yield IssueHistoryService(session, actor)
                    await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
            finally:
                await transaction.rollback()
                assert not connection.in_transaction()
    finally:
        await engine.dispose()


async def test_commands_replay_conflict_inactive_and_audit(service: IssueHistoryService) -> None:
    parent = await service.create_category(
        s.CategoryCreate(request_id=uuid4(), code=f"root-{uuid4().hex}", name="Synthetic root")
    )
    category = await service.create_category(
        s.CategoryCreate(
            parent_id=parent.id,
            request_id=uuid4(),
            code=f"verify-{uuid4().hex}",
            name="Synthetic verification",
        )
    )
    request = s.IssueCreate(
        request_id=uuid4(),
        category_id=category.id,
        title="Synthetic rollback issue",
    )
    created = await service.create_issue(request)
    assert (await service.create_issue(request)).id == created.id
    assert len((await service.detail(created.id)).events) == 1
    with pytest.raises(AppError) as conflict:
        await service.create_issue(request.model_copy(update={"title": "Different payload"}))
    assert conflict.value.status_code == 409
    await service.update_category(
        category.id,
        s.CategoryUpdate(
            request_id=uuid4(),
            expected_revision=category.revision,
            parent_id=category.parent_id,
            name=category.name,
            is_active=False,
        ),
    )
    updated = await service.update_issue(
        created.id,
        s.IssueUpdate(
            request_id=uuid4(),
            expected_revision=1,
            category_id=category.id,
            title="Existing inactive category retained",
        ),
    )
    assert updated.revision == 2
    assert len(updated.events) == 2
    matching = await service.list_issues(q=created.issue_key, category_id=category.id, limit=1)
    assert matching.total == 1 and matching.items[0].id == created.id
    assert (await service.list_issues(q=created.issue_key, status="verified")).total == 0
    assert (await service.list_issues(q=created.issue_key, offset=1)).items == []
    with pytest.raises(AppError) as inactive:
        await service.create_issue(
            s.IssueCreate(
                request_id=uuid4(),
                category_id=category.id,
                title="Blocked inactive assignment",
            )
        )
    assert inactive.value.status_code == 409
    with pytest.raises(AppError) as stale:
        await service.update_issue(
            created.id,
            s.IssueUpdate(
                request_id=uuid4(),
                expected_revision=1,
                category_id=category.id,
                title="Stale",
            ),
        )
    assert stale.value.status_code == 409


async def test_document_versions_links_and_history_are_pinned(service: IssueHistoryService) -> None:
    parent = await service.create_category(
        s.CategoryCreate(request_id=uuid4(), code=f"root-{uuid4().hex}", name="Synthetic root")
    )
    category = await service.create_category(
        s.CategoryCreate(
            parent_id=parent.id,
            request_id=uuid4(),
            code=f"verify-{uuid4().hex}",
            name="Synthetic verification",
        )
    )
    issue = await service.create_issue(
        s.IssueCreate(
            request_id=uuid4(),
            category_id=category.id,
            title="Synthetic rollback issue",
        )
    )
    first = await service.create_document(
        s.DocumentCreate(
            request_id=uuid4(),
            title="Synthetic rollback document",
            content="Version one",
        )
    )
    linked = await service.replace_links(
        issue.id,
        s.LinksUpdate(
            request_id=uuid4(),
            expected_revision=issue.revision,
            links=[s.DocumentLink(document_id=first.document_id, version=first.version)],
        ),
    )
    second = await service.add_version(
        first.document_id,
        s.DocumentVersionCreate(
            request_id=uuid4(),
            expected_revision=1,
            content="Version two",
        ),
    )
    assert second.version == 2
    replay_old = await service.add_version(
        first.document_id,
        s.DocumentVersionCreate(
            request_id=uuid4(),
            expected_revision=2,
            content="Version one",
        ),
    )
    assert replay_old.version == 1 and replay_old.current_version == 2
    pinned = await service.document_version(first.document_id, 1, issue.id)
    assert pinned.content == "Version one"
    with pytest.raises(AppError) as unlinked:
        await service.document_version(first.document_id, 2, issue.id)
    assert unlinked.value.status_code == 404
    for _ in range(3):
        linked = await service.replace_links(
            issue.id,
            s.LinksUpdate(
                request_id=uuid4(),
                expected_revision=linked.revision,
                links=[],
            ),
        )
    assert (await service.document_version(first.document_id, 1)).content == "Version one"
    for event in linked.events:
        if event.kind == "links_updated":
            before, after = event.snapshot.get("before"), event.snapshot.get("after")
            assert isinstance(before, dict) and "events" not in before
            assert isinstance(after, dict) and "events" not in after


async def test_original_import_replay_and_manifest_conflict(
    service: IssueHistoryService, monkeypatch: pytest.MonkeyPatch
) -> None:
    suffix = uuid4().hex
    category = f"verify-{suffix}"
    source_key = f"verification-{suffix}"
    document_path = f"docs/synthetic-{suffix}.md"
    content = "Synthetic immutable import verification"
    digest = sha256(content.encode()).hexdigest()
    monkeypatch.setitem(CATEGORY_NAMES, category, "Synthetic verification category")
    monkeypatch.setitem(CATEGORY_PARENTS, category, "rag")
    manifest = ImportManifest(
        digest=sha256(suffix.encode()).hexdigest(),
        issues=(
            SourceIssue(
                id=f"VERIFY-{suffix}",
                title="Synthetic imported issue",
                area=category,
                status="open",
                symptom="Synthetic symptom",
                cause="",
                resolution="",
                verification=[],
                remaining=[],
                commits=[],
                evidence=[document_path],
                history=[SourceEvent(date=date(2026, 1, 1), event="Synthetic historical event")],
            ),
        ),
        documents=(ImportDocument(document_path, content, digest),),
    )
    first = await apply_import(service.session, manifest, service.actor.id, source_key)
    assert first["result"] == "imported"
    assert (await apply_import(service.session, manifest, service.actor.id, source_key))[
        "result"
    ] == "unchanged"
    assert (await verify_import(service.session, manifest, source_key))["result"] == "verified"
    with pytest.raises(AppError) as changed:
        await apply_import(
            service.session, replace(manifest, digest="0" * 64), service.actor.id, source_key
        )
    assert changed.value.status_code == 409


async def test_concurrent_version_waits_for_document_lock() -> None:
    engine = create_rollback_engine()
    task: asyncio.Task[s.IssueDocumentVersionView] | None = None
    try:
        async with engine.connect() as first, engine.connect() as second:
            first_transaction = await first.begin()
            second_transaction = await second.begin()
            try:
                async with (
                    AsyncSession(bind=first) as first_session,
                    AsyncSession(
                        bind=second,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as second_session,
                ):
                    document = await first_session.scalar(
                        select(IssueDocument).limit(1).with_for_update()
                    )
                    assert document is not None, "Run the original ledger import first."
                    record = await second_session.scalar(
                        select(UserRecord)
                        .where(UserRecord.role == UserRole.OWNER, UserRecord.is_active.is_(True))
                        .limit(1)
                    )
                    assert record is not None
                    actor = User(
                        id=record.id,
                        display_name=record.display_name,
                        email=record.email,
                        normalized_email=record.normalized_email,
                        password_hash=record.password_hash,
                        role=UserRole.OWNER,
                    )
                    service = IssueHistoryService(second_session, actor)
                    task = asyncio.create_task(
                        service.add_version(
                            document.id,
                            s.DocumentVersionCreate(
                                request_id=uuid4(),
                                expected_revision=document.revision,
                                content=f"Synthetic rollback lock verification {uuid4()}",
                            ),
                        )
                    )
                    await asyncio.sleep(0.2)
                    assert not task.done(), (
                        "Concurrent version writer must wait for document row lock."
                    )
                    await first_transaction.rollback()
                    result = await asyncio.wait_for(task, timeout=10)
                    assert result.version == document.current_version + 1
                    await second_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
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
