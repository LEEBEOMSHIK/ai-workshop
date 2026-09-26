"""Opt-in taxonomy verification using only rollback-bound original DB sessions."""

import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ai_workshop.platform.issue_history import schemas as s
from ai_workshop.platform.issue_history.service import IssueHistoryService
from ai_workshop.shared.errors import AppError
from tests.integration.platform.issue_history.test_original_database import service

__all__ = ["service"]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_ORIGINAL_ISSUES") != "1",
        reason="Explicit original-database rollback verification is required.",
    ),
]


async def category(
    service: IssueHistoryService, parent_id: UUID | None = None
) -> s.IssueCategoryView:
    return await service.create_category(
        s.CategoryCreate(
            request_id=uuid4(),
            code=f"verify-{uuid4().hex}",
            name="Synthetic category",
            parent_id=parent_id,
        )
    )


async def issue(service: IssueHistoryService, category_id: UUID) -> s.IssueDetail:
    return await service.create_issue(
        s.IssueCreate(
            request_id=uuid4(),
            issue_key=f"VERIFY-{uuid4().hex}",
            category_id=category_id,
            title="Synthetic hierarchy verification",
        )
    )


async def update_category(
    service: IssueHistoryService,
    row: s.IssueCategoryView,
    parent_id: UUID | None,
    active: bool = True,
) -> s.IssueCategoryView:
    return await service.update_category(
        row.id,
        s.CategoryUpdate(
            request_id=uuid4(),
            expected_revision=row.revision,
            name=row.name,
            sort_order=row.sort_order,
            parent_id=parent_id,
            is_active=active,
        ),
    )


async def test_only_two_levels_and_safe_reparenting(service: IssueHistoryService) -> None:
    root = await category(service)
    other_root = await category(service)
    child = await category(service, root.id)
    with pytest.raises(AppError) as third_level:
        await category(service, child.id)
    assert third_level.value.status_code == 409
    with pytest.raises(AppError) as cycle:
        await update_category(service, root, root.id)
    assert cycle.value.status_code == 409
    with pytest.raises(AppError) as root_with_children:
        await update_category(service, root, other_root.id)
    assert root_with_children.value.status_code == 409
    with pytest.raises(AppError) as assign_root:
        await issue(service, root.id)
    assert assign_root.value.status_code == 409
    assigned = await issue(service, child.id)
    with pytest.raises(AppError) as promote_assigned:
        await update_category(service, child, None)
    assert promote_assigned.value.status_code == 409
    moved = await update_category(service, child, other_root.id)
    assert moved.id == child.id and moved.parent_id == other_root.id
    assert (await service.detail(assigned.id)).category_id == child.id


async def test_parent_filter_and_child_filter_intersection(service: IssueHistoryService) -> None:
    root_a = await category(service)
    root_b = await category(service)
    child_a = await category(service, root_a.id)
    sibling_a = await category(service, root_a.id)
    child_b = await category(service, root_b.id)
    first = await issue(service, child_a.id)
    sibling = await issue(service, sibling_a.id)
    await issue(service, child_b.id)
    found = await service.list_issues(parent_category_id=root_a.id)
    assert {item.id for item in found.items} == {first.id, sibling.id}
    assert found.total == 2
    intersected = await service.list_issues(parent_category_id=root_a.id, category_id=child_a.id)
    assert intersected.total == 1 and intersected.items[0].id == first.id
    mismatched = await service.list_issues(parent_category_id=root_a.id, category_id=child_b.id)
    assert mismatched.total == 0 and mismatched.items == []
    moved = await update_category(service, child_a, root_b.id)
    assert moved.parent_id == root_b.id
    assert (await service.list_issues(parent_category_id=root_a.id)).total == 1
    assert (await service.list_issues(parent_category_id=root_b.id)).total == 2


async def test_inactive_branch_blocks_new_assignments_but_keeps_existing_edits(
    service: IssueHistoryService,
) -> None:
    root = await category(service)
    child = await category(service, root.id)
    existing = await issue(service, child.id)
    inactive_root = await update_category(service, root, None, active=False)
    with pytest.raises(AppError) as inactive_branch:
        await issue(service, child.id)
    assert inactive_branch.value.status_code == 409
    edited = await service.update_issue(
        existing.id,
        s.IssueUpdate(
            request_id=uuid4(),
            expected_revision=existing.revision,
            category_id=child.id,
            title="Existing issue may retain its inactive branch",
        ),
    )
    assert edited.revision == 2 and edited.category_id == child.id
    await update_category(service, inactive_root, None, active=True)
    await update_category(service, child, root.id, active=False)
    with pytest.raises(AppError) as inactive_child:
        await issue(service, child.id)
    assert inactive_child.value.status_code == 409


async def test_database_rejects_invalid_hierarchy_without_service_guards(
    service: IssueHistoryService,
) -> None:
    root = await category(service)
    other_root = await category(service)
    child = await category(service, root.id)
    other_child = await category(service, other_root.id)
    assigned = await issue(service, child.id)
    mutations = [
        (
            "UPDATE issue_categories SET parent_id=:parent WHERE id=:id",
            {"parent": child.id, "id": other_child.id},
        ),
        (
            "UPDATE issue_categories SET parent_id=:parent WHERE id=:id",
            {"parent": other_root.id, "id": root.id},
        ),
        ("UPDATE issue_categories SET parent_id=NULL WHERE id=:id", {"id": child.id}),
        ("UPDATE issue_categories SET parent_id=id WHERE id=:id", {"id": other_root.id}),
        (
            "UPDATE issues SET category_id=:parent WHERE id=:id",
            {"parent": root.id, "id": assigned.id},
        ),
    ]
    for statement, parameters in mutations:
        with pytest.raises(IntegrityError):
            async with service.session.begin_nested():
                await service.session.execute(text(statement), parameters)
    assert (await service.detail(assigned.id)).category_id == child.id
