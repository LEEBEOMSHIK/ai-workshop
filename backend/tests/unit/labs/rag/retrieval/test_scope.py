from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.retrieval.scope import (
    SearchScopeResolver,
    WorkspaceAccess,
)
from ai_workshop.platform.workspaces.domain import Workspace, WorkspaceKind
from ai_workshop.shared.errors import AppError


class InMemorySearchScopeRepository:
    def __init__(
        self,
        *,
        workspaces: tuple[Workspace, ...],
        memberships: dict[UUID, frozenset[UUID]],
        folders: dict[UUID, UUID] | None = None,
    ) -> None:
        self.workspaces = {workspace.id: workspace for workspace in workspaces}
        self.memberships = memberships
        self.folders = folders or {}

    async def find_workspace_access(
        self,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
    ) -> tuple[WorkspaceAccess, ...]:
        member_ids = self.memberships.get(actor_id, frozenset())
        return tuple(
            WorkspaceAccess(workspace, workspace.id in member_ids)
            for workspace_id in workspace_ids
            if (workspace := self.workspaces.get(workspace_id)) is not None
        )

    async def find_folder_workspaces(
        self,
        folder_ids: tuple[UUID, ...],
    ) -> tuple[tuple[UUID, UUID], ...]:
        return tuple(
            (folder_id, workspace_id)
            for folder_id in folder_ids
            if (workspace_id := self.folders.get(folder_id)) is not None
        )


NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def resolver(
    *,
    workspaces: tuple[Workspace, ...],
    actor_id: UUID,
    member_workspace_ids: frozenset[UUID],
    folders: dict[UUID, UUID] | None = None,
) -> SearchScopeResolver:
    return SearchScopeResolver(
        InMemorySearchScopeRepository(
            workspaces=workspaces,
            memberships={actor_id: member_workspace_ids},
            folders=folders,
        ),
        now=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_company_membership_resolves_requested_workspace() -> None:
    actor_id = uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, uuid4())

    scope = await resolver(
        workspaces=(company,),
        actor_id=actor_id,
        member_workspace_ids=frozenset({company.id}),
    ).resolve(actor_id=actor_id, workspace_ids=(company.id,), folder_ids=())

    assert scope.workspace_ids == (company.id,)
    assert scope.folder_ids == ()
    assert scope.active_only is True
    assert scope.ready_only is True


@pytest.mark.asyncio
async def test_owner_membership_resolves_own_personal_workspace() -> None:
    actor_id = uuid4()
    personal = Workspace(uuid4(), "Personal", WorkspaceKind.PERSONAL, actor_id)

    scope = await resolver(
        workspaces=(personal,),
        actor_id=actor_id,
        member_workspace_ids=frozenset({personal.id}),
    ).resolve(actor_id=actor_id, workspace_ids=(personal.id,), folder_ids=())

    assert scope.workspace_ids == (personal.id,)


@pytest.mark.asyncio
async def test_another_personal_workspace_is_indistinguishable_from_missing() -> None:
    actor_id = uuid4()
    another_personal = Workspace(uuid4(), "Private", WorkspaceKind.PERSONAL, uuid4())
    scope_resolver = resolver(
        workspaces=(another_personal,),
        actor_id=actor_id,
        member_workspace_ids=frozenset({another_personal.id}),
    )

    with pytest.raises(AppError) as error:
        await scope_resolver.resolve(
            actor_id=actor_id,
            workspace_ids=(another_personal.id,),
            folder_ids=(),
        )

    assert (error.value.code, error.value.status_code) == ("not_found", 404)


@pytest.mark.asyncio
async def test_expired_temporary_workspace_is_excluded() -> None:
    actor_id = uuid4()
    expired = Workspace(
        uuid4(),
        "Expired",
        WorkspaceKind.TEMPORARY,
        actor_id,
        NOW - timedelta(seconds=1),
    )
    scope_resolver = resolver(
        workspaces=(expired,),
        actor_id=actor_id,
        member_workspace_ids=frozenset({expired.id}),
    )

    with pytest.raises(AppError) as error:
        await scope_resolver.resolve(
            actor_id=actor_id,
            workspace_ids=(expired.id,),
            folder_ids=(),
        )

    assert (error.value.code, error.value.status_code) == ("not_found", 404)


@pytest.mark.asyncio
async def test_folder_filter_must_belong_to_authorized_workspace_scope() -> None:
    actor_id = uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, uuid4())
    other = Workspace(uuid4(), "Other", WorkspaceKind.COMPANY, uuid4())
    requested_folder = uuid4()
    scope_resolver = resolver(
        workspaces=(company, other),
        actor_id=actor_id,
        member_workspace_ids=frozenset({company.id}),
        folders={requested_folder: other.id},
    )

    with pytest.raises(AppError) as error:
        await scope_resolver.resolve(
            actor_id=actor_id,
            workspace_ids=(company.id,),
            folder_ids=(requested_folder,),
        )

    assert (error.value.code, error.value.status_code) == ("not_found", 404)


@pytest.mark.asyncio
async def test_empty_requested_scope_is_rejected_before_external_search() -> None:
    actor_id = uuid4()
    scope_resolver = resolver(
        workspaces=(),
        actor_id=actor_id,
        member_workspace_ids=frozenset(),
    )

    with pytest.raises(AppError) as error:
        await scope_resolver.resolve(actor_id=actor_id, workspace_ids=(), folder_ids=())

    assert (error.value.code, error.value.status_code) == ("search_scope_empty", 422)
