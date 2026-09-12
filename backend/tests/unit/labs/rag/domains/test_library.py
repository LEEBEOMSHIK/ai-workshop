from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.configurations.domain import (
    AnswerPolicyVersion,
    SavedRagConfiguration,
)
from ai_workshop.labs.rag.configurations.service import ConfigurationReadiness
from ai_workshop.labs.rag.domains.library import DomainLibraryService
from ai_workshop.labs.rag.domains.service import (
    Domain,
    DomainConnectionVersion,
    DomainLibraryContext,
    DomainService,
    DomainWorkspaceOption,
)
from ai_workshop.labs.rag.models.domain import EvaluationState
from ai_workshop.platform.assets.domain import Document
from ai_workshop.platform.assets.library import AssetVersionPage, LibraryPage
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.workspaces.domain import Workspace, WorkspaceKind
from ai_workshop.shared.errors import AppError

ACTOR_ID = UUID("10000000-0000-0000-0000-000000000001")
DOMAIN_ID = UUID("20000000-0000-0000-0000-000000000001")
OTHER_DOMAIN_ID = UUID("20000000-0000-0000-0000-000000000002")
CONNECTION_ID = UUID("30000000-0000-0000-0000-000000000001")
CONFIGURATION_ID = UUID("40000000-0000-0000-0000-000000000001")
CONFIGURATION_VERSION_ID = UUID("40000000-0000-0000-0000-000000000002")
WORKSPACE_ID = UUID("50000000-0000-0000-0000-000000000001")
REMOVED_WORKSPACE_ID = UUID("50000000-0000-0000-0000-000000000002")


def _configuration() -> SavedRagConfiguration:
    indexing_profile_id = uuid4()
    return SavedRagConfiguration.create(
        configuration_id=CONFIGURATION_ID,
        configuration_version_id=CONFIGURATION_VERSION_ID,
        owner_id=ACTOR_ID,
        name="Library metadata configuration",
        version=1,
        indexing_profile_id=indexing_profile_id,
        retrieval_profile_id=uuid4(),
        retrieval_indexing_profile_id=indexing_profile_id,
        generation_profile_id=uuid4(),
        answer_policy_version=AnswerPolicyVersion.create(
            configuration_id=CONFIGURATION_ID,
            version=1,
            mode="generative",
            min_semantic_score=0.8,
            min_keyword_coverage=0.7,
            require_complete_provenance=True,
            conflict_mode="separate_sources",
        ),
        workspace_ids=(WORKSPACE_ID,),
        evaluation_state=EvaluationState.PASSED,
    )


def _domain() -> Domain:
    return Domain(
        id=DOMAIN_ID,
        slug="fund-management",
        display_name="자산운용",
        description="승인된 지식",
        active_connection_version_id=CONNECTION_ID,
        created_by=ACTOR_ID,
    )


def _connection() -> DomainConnectionVersion:
    return DomainConnectionVersion(
        id=CONNECTION_ID,
        domain_id=DOMAIN_ID,
        version=3,
        configuration_version_id=CONFIGURATION_VERSION_ID,
        workspace_ids=(WORKSPACE_ID, REMOVED_WORKSPACE_ID),
        created_by=ACTOR_ID,
    )


class MetadataRepository:
    def __init__(self) -> None:
        self.domain = _domain()
        self.connection = _connection()
        self.workspace_options = (
            DomainWorkspaceOption(
                WORKSPACE_ID,
                "허용 공간",
                WorkspaceKind.TEAM,
                None,
            ),
            DomainWorkspaceOption(
                REMOVED_WORKSPACE_ID,
                "구성에서 제거된 공간",
                WorkspaceKind.TEAM,
                None,
            ),
        )

    async def list_domains(self) -> tuple[Domain, ...]:
        return (self.domain,)

    async def find_by_slug(self, slug: str) -> Domain | None:
        return self.domain if slug == self.domain.slug else None

    async def find_by_id(self, domain_id: UUID) -> Domain | None:
        return self.domain if domain_id == self.domain.id else None

    async def find_connection(self, connection_id: UUID) -> DomainConnectionVersion | None:
        return self.connection if connection_id == self.connection.id else None

    async def latest_connection(self, domain_id: UUID) -> DomainConnectionVersion | None:
        return self.connection if domain_id == self.domain.id else None

    async def list_connections(
        self, domain_id: UUID
    ) -> tuple[DomainConnectionVersion, ...]:
        return (self.connection,) if domain_id == self.domain.id else ()

    async def workspace_options_for_actor(
        self,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
    ) -> tuple[DomainWorkspaceOption, ...]:
        if actor_id != ACTOR_ID:
            return ()
        allowed = set(workspace_ids)
        return tuple(item for item in self.workspace_options if item.id in allowed)

    async def add_domain(self, domain: Domain) -> Domain:
        self.domain = domain
        return domain

    async def update_domain(self, domain: Domain) -> Domain:
        self.domain = domain
        return domain

    async def next_connection_version(self, domain_id: UUID) -> int:
        return 4

    async def add_connection(
        self, connection: DomainConnectionVersion
    ) -> DomainConnectionVersion:
        self.connection = connection
        return connection

    async def set_active_connection(
        self,
        domain_id: UUID,
        connection_version_id: UUID | None,
    ) -> Domain:
        self.domain = replace(
            self.domain,
            active_connection_version_id=connection_version_id,
        )
        return self.domain


class MetadataConfigurations:
    def __init__(self) -> None:
        self.configuration: SavedRagConfiguration | None = _configuration()
        self.readiness_calls = 0
        self.readiness_result = ConfigurationReadiness(
            search_ready=True,
            answer_ready=False,
            service_ready=False,
            answer_reasons=("deployment_not_ready",),
        )

    async def find_owner_version(
        self,
        configuration_version_id: UUID,
        actor_id: UUID,
    ) -> SavedRagConfiguration | None:
        return None

    async def find_domain_version(
        self,
        configuration_version_id: UUID,
    ) -> SavedRagConfiguration | None:
        if (
            self.configuration is not None
            and configuration_version_id == self.configuration.version_id
        ):
            return self.configuration
        return None

    async def readiness(
        self,
        configuration: SavedRagConfiguration,
    ) -> ConfigurationReadiness:
        self.readiness_calls += 1
        return self.readiness_result


def _domain_service(
    repository: MetadataRepository,
    configurations: MetadataConfigurations,
) -> DomainService:
    return DomainService(repository, configurations)


@pytest.mark.asyncio
async def test_resolve_library_uses_active_metadata_without_generation_readiness() -> None:
    repository = MetadataRepository()
    configurations = MetadataConfigurations()

    context = await _domain_service(repository, configurations).resolve_library(
        slug="fund-management",
        actor_id=ACTOR_ID,
    )

    assert context.domain.id == DOMAIN_ID
    assert context.connection.id == CONNECTION_ID
    assert context.allowed_workspace_ids == (WORKSPACE_ID,)
    assert [item.name for item in context.workspace_options] == ["허용 공간"]
    assert configurations.readiness_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["inactive", "foreign_connection", "missing_configuration"])
async def test_resolve_library_rejects_noncurrent_domain_metadata(failure: str) -> None:
    repository = MetadataRepository()
    configurations = MetadataConfigurations()
    if failure == "inactive":
        repository.domain = replace(repository.domain, active_connection_version_id=None)
    elif failure == "foreign_connection":
        repository.connection = replace(repository.connection, domain_id=OTHER_DOMAIN_ID)
    else:
        configurations.configuration = None

    with pytest.raises(AppError) as caught:
        await _domain_service(repository, configurations).resolve_library(
            slug="fund-management",
            actor_id=ACTOR_ID,
        )

    assert caught.value.code == "not_found"
    assert caught.value.status_code == 404
    assert configurations.readiness_calls == 0


@pytest.mark.asyncio
async def test_resolve_library_rejects_actor_without_current_workspace_access() -> None:
    repository = MetadataRepository()
    configurations = MetadataConfigurations()

    with pytest.raises(AppError) as caught:
        await _domain_service(repository, configurations).resolve_library(
            slug="fund-management",
            actor_id=uuid4(),
        )

    assert caught.value.code == "not_found"
    assert configurations.readiness_calls == 0


def _user() -> User:
    return User(
        id=ACTOR_ID,
        display_name="Library member",
        email="library-member@example.test",
        normalized_email="library-member@example.test",
        password_hash="hash",
        role=UserRole.MEMBER,
    )


def _library_context() -> DomainLibraryContext:
    return DomainLibraryContext(
        domain=_domain(),
        connection=_connection(),
        workspace_options=(
            DomainWorkspaceOption(
                WORKSPACE_ID,
                "허용 공간",
                WorkspaceKind.TEAM,
                None,
            ),
        ),
    )


def _library_page() -> LibraryPage:
    return LibraryPage(
        workspace=Workspace(
            id=WORKSPACE_ID,
            name="허용 공간",
            kind=WorkspaceKind.TEAM,
            created_by=ACTOR_ID,
        ),
        folder=None,
        ancestors=(),
        folders=(),
        documents=(),
        next_folder_cursor=None,
        next_document_cursor=None,
    )


class RecordingDomainLibraryResolver:
    def __init__(self) -> None:
        self.context: DomainLibraryContext | None = _library_context()
        self.calls: list[tuple[str, UUID]] = []

    async def resolve_library(
        self,
        *,
        slug: str,
        actor_id: UUID,
    ) -> DomainLibraryContext:
        self.calls.append((slug, actor_id))
        if self.context is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return self.context


class RecordingPlatformLibrary:
    def __init__(self) -> None:
        self.page = _library_page()
        self.selected_document = Document.create(
            workspace_id=WORKSPACE_ID,
            folder_id=None,
            name="allowed.md",
        )
        self.selected_document.new_version(
            object_key="synthetic/allowed.md",
            sha256="1" * 64,
            media_type="text/markdown",
            size=1,
        )
        self.browse_calls: list[dict[str, object]] = []
        self.document_calls: list[dict[str, object]] = []

    async def browse(self, **kwargs: object) -> LibraryPage:
        self.browse_calls.append(kwargs)
        return self.page

    async def document(self, **kwargs: object) -> Document:
        self.document_calls.append(kwargs)
        return self.selected_document

    async def versions(self, **_kwargs: object) -> AssetVersionPage:
        return AssetVersionPage((), None)


@pytest.mark.asyncio
async def test_domain_library_browse_preserves_platform_scope_binding() -> None:
    resolver = RecordingDomainLibraryResolver()
    platform = RecordingPlatformLibrary()
    service = DomainLibraryService(resolver, platform, selection_limit=17)
    user = _user()
    folder_id = uuid4()

    page = await service.browse(
        slug="fund-management",
        user=user,
        workspace_id=WORKSPACE_ID,
        folder_id=folder_id,
        folder_cursor="folder-cursor",
        document_cursor="document-cursor",
        limit=7,
    )

    assert page is platform.page
    assert resolver.calls == [("fund-management", ACTOR_ID)]
    assert platform.browse_calls == [
        {
            "user": user,
            "workspace_id": WORKSPACE_ID,
            "folder_id": folder_id,
            "folder_cursor": "folder-cursor",
            "document_cursor": "document-cursor",
            "limit": 7,
        }
    ]


@pytest.mark.asyncio
async def test_domain_library_rejects_workspace_before_platform_delegation() -> None:
    resolver = RecordingDomainLibraryResolver()
    platform = RecordingPlatformLibrary()
    service = DomainLibraryService(resolver, platform, selection_limit=17)

    with pytest.raises(AppError) as caught:
        await service.browse(
            slug="fund-management",
            user=_user(),
            workspace_id=REMOVED_WORKSPACE_ID,
            folder_id=None,
            folder_cursor=None,
            document_cursor=None,
            limit=None,
        )

    assert caught.value.code == "not_found"
    assert platform.browse_calls == []


@pytest.mark.asyncio
async def test_domain_library_revalidates_before_every_document_request() -> None:
    resolver = RecordingDomainLibraryResolver()
    platform = RecordingPlatformLibrary()
    service = DomainLibraryService(resolver, platform, selection_limit=17)
    user = _user()

    document = await service.document(
        slug="fund-management",
        user=user,
        workspace_id=WORKSPACE_ID,
        document_id=platform.selected_document.id,
    )
    resolver.context = None
    with pytest.raises(AppError) as caught:
        await service.document(
            slug="fund-management",
            user=user,
            workspace_id=WORKSPACE_ID,
            document_id=platform.selected_document.id,
        )

    assert document is platform.selected_document
    assert caught.value.code == "not_found"
    assert resolver.calls == [
        ("fund-management", ACTOR_ID),
        ("fund-management", ACTOR_ID),
    ]
    assert platform.document_calls == [
        {
            "user": user,
            "workspace_id": WORKSPACE_ID,
            "document_id": platform.selected_document.id,
        }
    ]
