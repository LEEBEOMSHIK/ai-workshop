from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.retrieval.domain import SelectedDocumentIdentity
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
        document_locations: dict[UUID, tuple[UUID, UUID | None]] | None = None,
        searchable_lifecycle: tuple[SelectedDocumentIdentity, ...] = (),
    ) -> None:
        self.workspaces = {workspace.id: workspace for workspace in workspaces}
        self.memberships = memberships
        self.folders = folders or {}
        self.document_locations = document_locations or {}
        self.searchable_lifecycle = searchable_lifecycle
        self.lifecycle_requests: list[
            tuple[tuple[UUID, ...], tuple[UUID, ...], UUID, tuple[UUID, ...] | None, UUID | None]
        ] = []

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

    async def find_searchable_lifecycle(
        self,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
        indexing_profile_id: UUID,
        document_ids: tuple[UUID, ...] | None = None,
        document_processing_profile_id: UUID | None = None,
    ) -> tuple[SelectedDocumentIdentity, ...]:
        self.lifecycle_requests.append(
            (
                workspace_ids,
                folder_ids,
                indexing_profile_id,
                document_ids,
                document_processing_profile_id,
            )
        )
        return self.searchable_lifecycle

    async def find_document_locations(
        self, document_ids: tuple[UUID, ...]
    ) -> tuple[tuple[UUID, UUID, UUID | None], ...]:
        return tuple(
            (document_id, workspace_id, folder_id)
            for document_id in document_ids
            if (location := self.document_locations.get(document_id)) is not None
            for workspace_id, folder_id in (location,)
        )


NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def resolver(
    *,
    workspaces: tuple[Workspace, ...],
    actor_id: UUID,
    member_workspace_ids: frozenset[UUID],
    folders: dict[UUID, UUID] | None = None,
    document_locations: dict[UUID, tuple[UUID, UUID | None]] | None = None,
    searchable_lifecycle: tuple[SelectedDocumentIdentity, ...] = (),
) -> SearchScopeResolver:
    return SearchScopeResolver(
        InMemorySearchScopeRepository(
            workspaces=workspaces,
            memberships={actor_id: member_workspace_ids},
            folders=folders,
            document_locations=document_locations,
            searchable_lifecycle=searchable_lifecycle,
        ),
        now=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_version_switch_excludes_superseded_a1_until_a2_is_searchable() -> None:
    actor_id = uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, uuid4())
    indexing_profile_id = uuid4()
    a1_asset_id, a1_build_id = uuid4(), uuid4()
    b_asset_id, b_build_id = uuid4(), uuid4()
    b_identity = SelectedDocumentIdentity(uuid4(), b_asset_id, uuid4(), b_build_id)
    scope_resolver = resolver(
        workspaces=(company,),
        actor_id=actor_id,
        member_workspace_ids=frozenset({company.id}),
        # A1 is superseded. A2 is not READY yet. B remains authoritative.
        searchable_lifecycle=(b_identity,),
    )

    scope = await scope_resolver.resolve(
        actor_id=actor_id,
        workspace_ids=(company.id,),
        folder_ids=(),
        indexing_profile_id=indexing_profile_id,
    )

    assert scope.asset_version_ids == (b_asset_id,)
    assert scope.index_build_ids == (b_build_id,)
    assert getattr(scope, "authorized_documents", ()) == (b_identity,)
    assert a1_asset_id not in scope.asset_version_ids
    assert a1_build_id not in scope.index_build_ids


@pytest.mark.asyncio
async def test_db_inactive_a2_after_es_success_is_excluded_while_b_remains() -> None:
    actor_id = uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, uuid4())
    indexing_profile_id = uuid4()
    a2_asset_id, a2_build_id = uuid4(), uuid4()
    b_asset_id, b_build_id = uuid4(), uuid4()
    b_identity = SelectedDocumentIdentity(uuid4(), b_asset_id, uuid4(), b_build_id)
    scope_resolver = resolver(
        workspaces=(company,),
        actor_id=actor_id,
        member_workspace_ids=frozenset({company.id}),
        # Elasticsearch may contain A2, but DB rollback left its build inactive.
        searchable_lifecycle=(b_identity,),
    )

    scope = await scope_resolver.resolve(
        actor_id=actor_id,
        workspace_ids=(company.id,),
        folder_ids=(),
        indexing_profile_id=indexing_profile_id,
    )

    assert scope.asset_version_ids == (b_asset_id,)
    assert scope.index_build_ids == (b_build_id,)
    assert a2_asset_id not in scope.asset_version_ids
    assert a2_build_id not in scope.index_build_ids


@pytest.mark.asyncio
async def test_company_membership_resolves_requested_workspace() -> None:
    actor_id = uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, uuid4())

    scope = await resolver(
        workspaces=(company,),
        actor_id=actor_id,
        member_workspace_ids=frozenset({company.id}),
    ).resolve(
        actor_id=actor_id,
        workspace_ids=(company.id,),
        folder_ids=(),
        indexing_profile_id=uuid4(),
    )

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
    ).resolve(
        actor_id=actor_id,
        workspace_ids=(personal.id,),
        folder_ids=(),
        indexing_profile_id=uuid4(),
    )

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
            indexing_profile_id=uuid4(),
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
            indexing_profile_id=uuid4(),
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
            indexing_profile_id=uuid4(),
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
        await scope_resolver.resolve(
            actor_id=actor_id,
            workspace_ids=(),
            folder_ids=(),
            indexing_profile_id=uuid4(),
        )

    assert (error.value.code, error.value.status_code) == ("search_scope_empty", 422)


@pytest.mark.asyncio
async def test_selected_documents_are_normalized_and_freeze_exact_lifecycle() -> None:
    actor_id = uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, actor_id)
    first_document_id, second_document_id = sorted((uuid4(), uuid4()), key=str)
    processing_profile_id = uuid4()
    first = SelectedDocumentIdentity(first_document_id, uuid4(), uuid4(), uuid4())
    second = SelectedDocumentIdentity(second_document_id, uuid4(), uuid4(), uuid4())
    scope = await resolver(
        workspaces=(company,),
        actor_id=actor_id,
        member_workspace_ids=frozenset({company.id}),
        document_locations={
            first_document_id: (company.id, None),
            second_document_id: (company.id, None),
        },
        searchable_lifecycle=(second, first),
    ).resolve(
        actor_id=actor_id,
        workspace_ids=(company.id,),
        folder_ids=(),
        indexing_profile_id=uuid4(),
        document_ids=(second_document_id, first_document_id, second_document_id),
        document_processing_profile_id=processing_profile_id,
    )
    assert scope.document_ids == (first_document_id, second_document_id)
    assert scope.selected_documents == (first, second)
    assert scope.authorized_documents == (first, second)
    assert scope.asset_version_ids == (first.asset_version_id, second.asset_version_id)
    assert scope.index_build_ids == (first.index_build_id, second.index_build_id)
    assert scope.scope_fingerprint is not None and len(scope.scope_fingerprint) == 64


@pytest.mark.asyncio
async def test_folder_scope_keeps_exact_authority_without_public_document_selection() -> None:
    actor_id, folder_id = uuid4(), uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, actor_id)
    identity = SelectedDocumentIdentity(uuid4(), uuid4(), uuid4(), uuid4())
    scope = await resolver(
        workspaces=(company,), actor_id=actor_id,
        member_workspace_ids=frozenset({company.id}), folders={folder_id: company.id},
        searchable_lifecycle=(identity,),
    ).resolve(actor_id=actor_id, workspace_ids=(company.id,), folder_ids=(folder_id,),
              indexing_profile_id=uuid4())
    assert scope.authorized_documents == (identity,)
    assert scope.selected_documents == ()
    assert scope.document_ids is None and scope.scope_fingerprint is None



@pytest.mark.asyncio
async def test_selected_document_location_failure_is_404_before_ready_lookup() -> None:
    actor_id = uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, actor_id)
    repository = InMemorySearchScopeRepository(
        workspaces=(company,),
        memberships={actor_id: frozenset({company.id})},
    )

    with pytest.raises(AppError) as error:
        await SearchScopeResolver(repository).resolve(
            actor_id=actor_id,
            workspace_ids=(company.id,),
            folder_ids=(),
            indexing_profile_id=uuid4(),
            document_ids=(uuid4(),),
            document_processing_profile_id=uuid4(),
        )

    assert (error.value.code, error.value.status_code) == ("not_found", 404)
    assert repository.lifecycle_requests == []


@pytest.mark.asyncio
async def test_selected_document_in_foreign_personal_workspace_is_404_before_ready() -> None:
    actor_id = uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, actor_id)
    foreign_personal = Workspace(uuid4(), "Private", WorkspaceKind.PERSONAL, uuid4())
    document_id = uuid4()
    repository = InMemorySearchScopeRepository(
        workspaces=(company, foreign_personal),
        memberships={actor_id: frozenset({company.id})},
        document_locations={document_id: (foreign_personal.id, None)},
    )

    with pytest.raises(AppError) as error:
        await SearchScopeResolver(repository).resolve(
            actor_id=actor_id,
            workspace_ids=(company.id,),
            folder_ids=(),
            indexing_profile_id=uuid4(),
            document_ids=(document_id,),
            document_processing_profile_id=uuid4(),
        )

    assert (error.value.code, error.value.status_code) == ("not_found", 404)
    assert repository.lifecycle_requests == []


@pytest.mark.asyncio
async def test_selected_document_outside_requested_folder_is_404_before_ready() -> None:
    actor_id = uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, actor_id)
    requested_folder_id, other_folder_id, document_id = uuid4(), uuid4(), uuid4()
    repository = InMemorySearchScopeRepository(
        workspaces=(company,),
        memberships={actor_id: frozenset({company.id})},
        folders={requested_folder_id: company.id, other_folder_id: company.id},
        document_locations={document_id: (company.id, other_folder_id)},
    )

    with pytest.raises(AppError) as error:
        await SearchScopeResolver(repository).resolve(
            actor_id=actor_id,
            workspace_ids=(company.id,),
            folder_ids=(requested_folder_id,),
            indexing_profile_id=uuid4(),
            document_ids=(document_id,),
            document_processing_profile_id=uuid4(),
        )

    assert (error.value.code, error.value.status_code) == ("not_found", 404)
    assert repository.lifecycle_requests == []


@pytest.mark.asyncio
async def test_selected_documents_require_processing_profile() -> None:
    actor_id = uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, actor_id)
    document_id = uuid4()

    with pytest.raises(AppError) as error:
        await resolver(
            workspaces=(company,),
            actor_id=actor_id,
            member_workspace_ids=frozenset({company.id}),
            document_locations={document_id: (company.id, None)},
        ).resolve(
            actor_id=actor_id,
            workspace_ids=(company.id,),
            folder_ids=(),
            indexing_profile_id=uuid4(),
            document_ids=(document_id,),
        )

    assert (error.value.code, error.value.status_code) == (
        "document_processing_profile_missing",
        409,
    )


@pytest.mark.asyncio
async def test_common_scope_rejects_raw_duplicate_selection_amplification() -> None:
    actor_id = uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, actor_id)
    repository = InMemorySearchScopeRepository(
        workspaces=(company,),
        memberships={actor_id: frozenset({company.id})},
    )

    with pytest.raises(AppError) as error:
        await SearchScopeResolver(
            repository,
            selected_documents_max_count=1,
        ).resolve(
            actor_id=actor_id,
            workspace_ids=(company.id,),
            folder_ids=(),
            indexing_profile_id=uuid4(),
            document_ids=(uuid4(),) * 11,
            document_processing_profile_id=uuid4(),
        )

    assert (error.value.code, error.value.status_code) == (
        "document_selection_limit_exceeded",
        422,
    )
    assert repository.lifecycle_requests == []


@pytest.mark.asyncio
async def test_selected_documents_fail_closed_when_any_lifecycle_is_not_ready() -> None:
    actor_id = uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, actor_id)
    first_document_id, second_document_id = uuid4(), uuid4()
    first = SelectedDocumentIdentity(first_document_id, uuid4(), uuid4(), uuid4())

    with pytest.raises(AppError) as error:
        await resolver(
            workspaces=(company,),
            actor_id=actor_id,
            member_workspace_ids=frozenset({company.id}),
            document_locations={
                first_document_id: (company.id, None),
                second_document_id: (company.id, None),
            },
            searchable_lifecycle=(first,),
        ).resolve(
            actor_id=actor_id,
            workspace_ids=(company.id,),
            folder_ids=(),
            indexing_profile_id=uuid4(),
            document_ids=(first_document_id, second_document_id),
            document_processing_profile_id=uuid4(),
        )

    assert (error.value.code, error.value.status_code) == (
        "selected_documents_not_ready",
        409,
    )


@pytest.mark.asyncio
async def test_selected_document_with_conflicting_active_builds_is_not_ready() -> None:
    actor_id = uuid4()
    company = Workspace(uuid4(), "Company", WorkspaceKind.COMPANY, actor_id)
    document_id = uuid4()
    asset_version_id, projection_id = uuid4(), uuid4()

    with pytest.raises(AppError) as error:
        await resolver(
            workspaces=(company,),
            actor_id=actor_id,
            member_workspace_ids=frozenset({company.id}),
            document_locations={document_id: (company.id, None)},
            searchable_lifecycle=(
                SelectedDocumentIdentity(
                    document_id, asset_version_id, projection_id, uuid4()
                ),
                SelectedDocumentIdentity(
                    document_id, asset_version_id, projection_id, uuid4()
                ),
            ),
        ).resolve(
            actor_id=actor_id,
            workspace_ids=(company.id,),
            folder_ids=(),
            indexing_profile_id=uuid4(),
            document_ids=(document_id,),
            document_processing_profile_id=uuid4(),
        )

    assert (error.value.code, error.value.status_code) == (
        "selected_documents_not_ready",
        409,
    )
