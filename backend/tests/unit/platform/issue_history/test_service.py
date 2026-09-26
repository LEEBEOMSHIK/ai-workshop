from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.issue_history import schemas as s
from ai_workshop.platform.issue_history.models import (
    IssueCategory,
    IssueCommand,
    IssueDocument,
    IssueDocumentVersion,
)
from ai_workshop.platform.issue_history.service import IssueHistoryService
from ai_workshop.shared.errors import AppError


def owner():
    return User(uuid4(), "Owner", "owner@example.test", "owner@example.test", "", UserRole.OWNER)


def service():
    session = MagicMock()
    session.begin_nested.return_value = AsyncMock()
    session.flush = AsyncMock()
    session.get = AsyncMock()
    service = IssueHistoryService(session, owner())
    service.repository.lock_command = AsyncMock()
    service.repository.command = AsyncMock(return_value=None)
    service.repository.lock_hierarchy = AsyncMock()
    return service


async def test_command_replay_does_not_run_mutation_again():
    current = service()
    request = s.CategoryCreate(request_id=uuid4(), code="category", name="Category")
    result = s.IssueCategoryView(
        id=uuid4(), code="category", name="Category", sort_order=0, is_active=True, revision=1
    )
    action = AsyncMock(return_value=result)
    assert await current._command("test", request, s.IssueCategoryView, action) == result
    saved = current.session.add.call_args.args[0]
    assert isinstance(saved, IssueCommand)
    current.repository.command.return_value = saved
    assert await current._command("test", request, s.IssueCategoryView, action) == result
    assert action.await_count == 1
    with pytest.raises(AppError) as caught:
        await current._command(
            "test", request.model_copy(update={"name": "Changed"}), s.IssueCategoryView, action
        )
    assert caught.value.status_code == 409
    assert action.await_count == 1


async def test_inactive_category_allows_existing_assignment_only():
    current = service()
    identity = uuid4()
    current.session.get.return_value = IssueCategory(
        id=identity, code="old", name="Old", is_active=False, revision=1, parent_id=uuid4()
    )
    await current._category(identity, identity)
    with pytest.raises(AppError) as caught:
        await current._category(identity)
    assert caught.value.status_code == 409


async def test_old_duplicate_body_does_not_rewind_current_version():
    current = service()
    identity = uuid4()
    document = IssueDocument(id=identity, title="Document", current_version=3, revision=5)
    existing = IssueDocumentVersion(document_id=identity, version=1)
    current._get = AsyncMock(return_value=document)
    current.session.scalar = AsyncMock(return_value=existing)
    expected = s.IssueDocumentVersionView(
        document_id=identity,
        version=1,
        title="Document",
        current_version=3,
        content="old",
        sha256="a" * 64,
        source_path=None,
        source_commit=None,
        created_at=datetime.now(UTC),
    )
    current.document_version = AsyncMock(return_value=expected)
    result = await current.add_version(
        identity, s.DocumentVersionCreate(request_id=uuid4(), expected_revision=5, content="old")
    )
    assert result.version == 1
    assert document.current_version == 3 and document.revision == 5
    assert not any(
        isinstance(call.args[0], IssueDocumentVersion)
        for call in current.session.add.call_args_list
    )


async def test_linked_document_cannot_read_unlinked_version():
    current = service()
    current.session.get.return_value = None
    with pytest.raises(AppError) as caught:
        await current.document_version(uuid4(), 2, uuid4())
    assert caught.value.status_code == 404


def test_stale_revision_rejected():
    with pytest.raises(AppError) as caught:
        IssueHistoryService._revision(IssueCategory(revision=3), 2)
    assert caught.value.status_code == 409


@pytest.mark.parametrize("status", [401, 403])
def test_api_permission_failure_is_no_store(status):
    app = create_app()

    async def current_user():
        if status == 401:
            raise AppError("authentication_required", "Authentication required.", 401)
        return User(
            uuid4(), "Member", "member@example.test", "member@example.test", "", UserRole.MEMBER
        )

    app.dependency_overrides[get_current_user] = current_user
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/issue-history/categories")
    assert response.status_code == status
    assert "no-store" in response.headers["cache-control"]


def test_issue_routes_not_registered_in_public_app():
    from ai_workshop.public_app import create_public_app

    assert not any(
        getattr(route, "path", "").startswith("/api/v1/admin/issue-history")
        for route in create_public_app().routes
    )


async def test_repeated_link_changes_do_not_snapshot_prior_events():
    from ai_workshop.platform.issue_history.models import Issue, IssueEvent

    current = service()
    now = datetime.now(UTC)
    row = Issue(
        id=uuid4(),
        issue_key="TEST-1",
        category_id=uuid4(),
        title="Test",
        status="open",
        symptom="",
        cause="",
        resolution="",
        verification=[],
        remaining=[],
        commits=[],
        revision=1,
        created_at=now,
        updated_at=now,
    )
    current._get = AsyncMock(return_value=row)
    current.repository.remove_links = AsyncMock()
    recorded = []

    async def detail(identity):
        return s.IssueDetail(
            **s.IssueView.model_validate(row).model_dump(),
            documents=[],
            events=[
                s.IssueEventView(
                    id=uuid4(),
                    event_date=now.date(),
                    recorded_at=now,
                    actor_id=current.actor.id,
                    kind="links_updated",
                    description="Links",
                    before_revision=1,
                    after_revision=2,
                    snapshot=event.snapshot,
                )
                for event in recorded
            ],
        )

    current.detail = detail
    for _ in range(3):
        await current.replace_links(
            row.id, s.LinksUpdate(request_id=uuid4(), expected_revision=row.revision, links=[])
        )
        event = next(
            call.args[0]
            for call in reversed(current.session.add.call_args_list)
            if isinstance(call.args[0], IssueEvent)
        )
        recorded.append(event)
        assert "events" not in event.snapshot["before"]
        assert "events" not in event.snapshot["after"]
    assert len(recorded) == 3


async def test_root_category_cannot_be_assigned_to_issue():
    current = service()
    current.repository.lock_hierarchy = AsyncMock()
    current.session.get.return_value = IssueCategory(
        id=uuid4(), code="root", name="Root", is_active=True, revision=1
    )
    with pytest.raises(AppError) as caught:
        await current._category(current.session.get.return_value.id)
    assert caught.value.code == "issue_category_leaf_required"


async def test_inactive_parent_blocks_new_child_assignment():
    current = service()
    current.repository.lock_hierarchy = AsyncMock()
    parent_id = uuid4()
    child = IssueCategory(
        id=uuid4(), code="child", name="Child", is_active=True, parent_id=parent_id, revision=1
    )
    parent = IssueCategory(id=parent_id, code="root", name="Root", is_active=False, revision=1)
    current.session.get.side_effect = [child, parent]
    with pytest.raises(AppError) as caught:
        await current._category(child.id)
    assert caught.value.code == "issue_category_inactive"
