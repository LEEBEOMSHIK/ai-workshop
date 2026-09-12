from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.configurations.domain import (
    AnswerPolicyVersion,
    SavedRagConfiguration,
)
from ai_workshop.labs.rag.configurations.service import ConfigurationReadiness
from ai_workshop.labs.rag.domains.service import (
    Domain,
    DomainConnectionVersion,
    DomainService,
    DomainWorkspaceOption,
    resolve_allowed_workspaces,
)
from ai_workshop.labs.rag.models.domain import EvaluationState
from ai_workshop.platform.workspaces.domain import WorkspaceKind
from ai_workshop.shared.errors import AppError

ACTOR_ID = UUID("10000000-0000-0000-0000-000000000001")
MEMBER_ID = UUID("10000000-0000-0000-0000-000000000002")
DOMAIN_ID = UUID("20000000-0000-0000-0000-000000000001")
CONNECTION_ID = UUID("20000000-0000-0000-0000-000000000002")
CONFIGURATION_ID = UUID("30000000-0000-0000-0000-000000000001")
CONFIGURATION_VERSION_ID = UUID("30000000-0000-0000-0000-000000000002")
WORKSPACE_A = UUID("40000000-0000-0000-0000-000000000001")
WORKSPACE_B = UUID("40000000-0000-0000-0000-000000000002")
WORKSPACE_C = UUID("40000000-0000-0000-0000-000000000003")


def _configuration(
    *,
    evaluation_state: EvaluationState = EvaluationState.PASSED,
    generative: bool = True,
) -> SavedRagConfiguration:
    policy = AnswerPolicyVersion.create(
        configuration_id=CONFIGURATION_ID,
        version=1,
        mode="generative" if generative else "extractive",
        min_semantic_score=0.8,
        min_keyword_coverage=0.7,
        require_complete_provenance=True,
        conflict_mode="separate_sources",
    )
    indexing_id = uuid4()
    return SavedRagConfiguration.create(
        configuration_id=CONFIGURATION_ID,
        configuration_version_id=CONFIGURATION_VERSION_ID,
        owner_id=ACTOR_ID,
        name="Domain configuration",
        version=1,
        indexing_profile_id=indexing_id,
        retrieval_profile_id=uuid4(),
        retrieval_indexing_profile_id=indexing_id,
        generation_profile_id=uuid4() if generative else None,
        answer_policy_version=policy,
        workspace_ids=(WORKSPACE_B, WORKSPACE_C),
        evaluation_state=evaluation_state,
    )


def _domain(*, active_connection_version_id: UUID | None = CONNECTION_ID) -> Domain:
    return Domain(
        id=DOMAIN_ID,
        slug="fund-management",
        display_name="자산운용",
        description="승인된 운용 지식",
        active_connection_version_id=active_connection_version_id,
        created_by=ACTOR_ID,
    )


def _connection(*, connection_id: UUID = CONNECTION_ID) -> DomainConnectionVersion:
    return DomainConnectionVersion(
        id=connection_id,
        domain_id=DOMAIN_ID,
        version=1,
        configuration_version_id=CONFIGURATION_VERSION_ID,
        workspace_ids=(WORKSPACE_A, WORKSPACE_B),
        created_by=ACTOR_ID,
    )


class FakeRepository:
    def __init__(self) -> None:
        self.domain = _domain()
        self.connection = _connection()
        self.options_by_actor = {
            ACTOR_ID: (
                DomainWorkspaceOption(WORKSPACE_A, "A", WorkspaceKind.TEAM, None),
                DomainWorkspaceOption(WORKSPACE_B, "B", WorkspaceKind.TEAM, None),
            ),
            MEMBER_ID: (
                DomainWorkspaceOption(WORKSPACE_B, "B", WorkspaceKind.TEAM, None),
            ),
        }
        self.active_updates: list[UUID | None] = []

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

    async def workspace_options_for_actor(
        self, actor_id: UUID, workspace_ids: tuple[UUID, ...]
    ) -> tuple[DomainWorkspaceOption, ...]:
        allowed = set(workspace_ids)
        return tuple(
            option for option in self.options_by_actor.get(actor_id, ()) if option.id in allowed
        )

    async def set_active_connection(
        self, domain_id: UUID, connection_version_id: UUID | None
    ) -> Domain:
        assert domain_id == self.domain.id
        self.active_updates.append(connection_version_id)
        self.domain = replace(
            self.domain, active_connection_version_id=connection_version_id
        )
        return self.domain

    async def add_domain(self, domain: Domain) -> Domain:
        self.domain = domain
        return domain

    async def update_domain(self, domain: Domain) -> Domain:
        self.domain = domain
        return domain

    async def next_connection_version(self, domain_id: UUID) -> int:
        assert domain_id == self.domain.id
        return 2

    async def add_connection(
        self, connection: DomainConnectionVersion
    ) -> DomainConnectionVersion:
        self.connection = connection
        return connection


class FakeConfigurations:
    def __init__(self, configuration: SavedRagConfiguration | None = None) -> None:
        self.configuration = configuration or _configuration()
        self.ready = ConfigurationReadiness(
            search_ready=True,
            answer_ready=True,
            service_ready=True,
        )

    async def find_owner_version(
        self, configuration_version_id: UUID, actor_id: UUID
    ) -> SavedRagConfiguration | None:
        if (
            configuration_version_id == self.configuration.version_id
            and actor_id == ACTOR_ID
        ):
            return self.configuration
        return None

    async def find_domain_version(
        self, configuration_version_id: UUID
    ) -> SavedRagConfiguration | None:
        if configuration_version_id == self.configuration.version_id:
            return self.configuration
        return None

    async def readiness(
        self, configuration: SavedRagConfiguration
    ) -> ConfigurationReadiness:
        assert configuration.version_id == self.configuration.version_id
        return self.ready


async def _no_commit() -> None:
    return None


def _service(
    repository: FakeRepository | None = None,
    configurations: FakeConfigurations | None = None,
) -> DomainService:
    return DomainService(
        repository or FakeRepository(),
        configurations or FakeConfigurations(),
        commit=_no_commit,
    )


def test_allowed_workspace_scope_is_three_way_intersection_in_domain_order() -> None:
    assert resolve_allowed_workspaces(
        domain=(WORKSPACE_A, WORKSPACE_B),
        configuration=(WORKSPACE_B, WORKSPACE_C),
        actor=(WORKSPACE_A, WORKSPACE_B),
    ) == (WORKSPACE_B,)


@pytest.mark.asyncio
async def test_member_detail_returns_only_intersection_without_private_workspace_name() -> None:
    detail = await _service().detail_for_actor("fund-management", MEMBER_ID)

    assert detail.domain.slug == "fund-management"
    assert detail.connection is not None
    assert detail.allowed_workspace_ids == (WORKSPACE_B,)
    assert [option.name for option in detail.workspace_options] == ["B"]


@pytest.mark.asyncio
async def test_domain_without_actor_intersection_does_not_expose_identity_or_names() -> None:
    repository = FakeRepository()
    repository.options_by_actor[MEMBER_ID] = ()
    service = _service(repository)

    assert await service.list_for_actor(MEMBER_ID) == ()
    with pytest.raises(AppError) as caught:
        await service.detail_for_actor("fund-management", MEMBER_ID)
    assert caught.value.code == "not_found"
    assert "fund-management" not in caught.value.message
    assert "A" not in caught.value.message
    assert "B" not in caught.value.message


@pytest.mark.asyncio
async def test_inactive_domain_with_prior_connection_is_visible_but_search_is_refused() -> None:
    repository = FakeRepository()
    repository.domain = _domain(active_connection_version_id=None)
    service = _service(repository)

    domains = await service.list_for_actor(MEMBER_ID)

    assert len(domains) == 1
    assert domains[0].active is False
    assert domains[0].ready is False
    assert domains[0].reason_codes == ("domain_inactive",)
    with pytest.raises(AppError) as caught:
        await service.resolve_search(
            slug="fund-management",
            actor_id=MEMBER_ID,
            connection_version_id=CONNECTION_ID,
            workspace_ids=(WORKSPACE_B,),
        )
    assert caught.value.code == "domain_inactive"


@pytest.mark.asyncio
async def test_changed_connection_version_is_refused_without_falling_forward() -> None:
    service = _service()

    with pytest.raises(AppError) as caught:
        await service.resolve_search(
            slug="fund-management",
            actor_id=MEMBER_ID,
            connection_version_id=uuid4(),
            workspace_ids=(WORKSPACE_B,),
        )

    assert caught.value.code == "domain_connection_changed"


@pytest.mark.asyncio
async def test_empty_or_outside_requested_scope_is_rejected_without_name_disclosure() -> None:
    service = _service()

    with pytest.raises(AppError) as empty:
        await service.resolve_search(
            slug="fund-management",
            actor_id=MEMBER_ID,
            connection_version_id=CONNECTION_ID,
            workspace_ids=(),
        )
    assert empty.value.code == "search_scope_empty"

    with pytest.raises(AppError) as outside:
        await service.resolve_search(
            slug="fund-management",
            actor_id=MEMBER_ID,
            connection_version_id=CONNECTION_ID,
            workspace_ids=(WORKSPACE_A,),
        )
    assert outside.value.code == "not_found"
    assert "A" not in outside.value.message


@pytest.mark.asyncio
async def test_connection_cannot_include_configuration_or_owner_foreign_workspace() -> None:
    repository = FakeRepository()
    service = _service(repository)

    with pytest.raises(AppError) as caught:
        await service.create_connection(
            domain_id=DOMAIN_ID,
            actor_id=ACTOR_ID,
            configuration_version_id=CONFIGURATION_VERSION_ID,
            workspace_ids=(WORKSPACE_A, WORKSPACE_B),
        )

    assert caught.value.code == "not_found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("configuration", "reason"),
    [
        (_configuration(generative=False), "generation_not_configured"),
        (
            _configuration(evaluation_state=EvaluationState.PENDING),
            "configuration_not_evaluated",
        ),
    ],
)
async def test_activation_requires_evaluated_generative_configuration(
    configuration: SavedRagConfiguration,
    reason: str,
) -> None:
    repository = FakeRepository()
    repository.connection = replace(repository.connection, workspace_ids=(WORKSPACE_B,))
    configurations = FakeConfigurations(configuration)
    service = _service(repository=repository, configurations=configurations)

    with pytest.raises(AppError) as caught:
        await service.activate_connection(
            domain_id=DOMAIN_ID,
            connection_version_id=CONNECTION_ID,
            actor_id=ACTOR_ID,
        )

    assert caught.value.code == reason


@pytest.mark.asyncio
async def test_activation_refuses_current_nonready_generation() -> None:
    repository = FakeRepository()
    repository.connection = replace(repository.connection, workspace_ids=(WORKSPACE_B,))
    configurations = FakeConfigurations()
    configurations.ready = ConfigurationReadiness(
        search_ready=True,
        answer_ready=False,
        service_ready=False,
        answer_reasons=("deployment_not_ready",),
    )
    service = _service(repository=repository, configurations=configurations)

    with pytest.raises(AppError) as caught:
        await service.activate_connection(
            domain_id=DOMAIN_ID,
            connection_version_id=CONNECTION_ID,
            actor_id=ACTOR_ID,
        )

    assert caught.value.code == "domain_not_ready"


@pytest.mark.asyncio
async def test_domain_search_keeps_member_actor_for_existing_search_authorization() -> None:
    context = await _service().resolve_search(
        slug="fund-management",
        actor_id=MEMBER_ID,
        connection_version_id=CONNECTION_ID,
        workspace_ids=(WORKSPACE_B,),
    )

    assert context.actor_id == MEMBER_ID
    assert context.configuration_version_id == CONFIGURATION_VERSION_ID
    assert context.workspace_ids == (WORKSPACE_B,)


@pytest.mark.asyncio
async def test_domain_search_preserves_raw_document_ids_for_common_size_guard() -> None:
    document_id = uuid4()
    raw_document_ids = (document_id,) * 11

    context = await _service().resolve_search(
        slug="fund-management",
        actor_id=MEMBER_ID,
        connection_version_id=CONNECTION_ID,
        workspace_ids=(WORKSPACE_B,),
        document_ids=raw_document_ids,
    )

    assert context.document_ids == raw_document_ids


def test_slug_is_immutable_while_display_fields_are_editable() -> None:
    domain = _domain()

    updated = domain.with_details(display_name="펀드", description="업데이트")

    assert updated.slug == domain.slug
    assert updated.display_name == "펀드"
    assert updated.description == "업데이트"
