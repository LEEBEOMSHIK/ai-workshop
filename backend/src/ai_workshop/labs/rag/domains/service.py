from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import NoReturn, Protocol
from uuid import UUID, uuid4

from ai_workshop.labs.rag.configurations.domain import SavedRagConfiguration
from ai_workshop.labs.rag.configurations.service import ConfigurationReadiness
from ai_workshop.labs.rag.generation.domain import GenerationExecutionSnapshot
from ai_workshop.labs.rag.models.domain import EvaluationState
from ai_workshop.platform.workspaces.domain import WorkspaceKind
from ai_workshop.shared.errors import AppError

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class Domain:
    id: UUID
    slug: str
    display_name: str
    description: str
    active_connection_version_id: UUID | None
    created_by: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        slug: str,
        display_name: str,
        description: str,
        created_by: UUID,
    ) -> Domain:
        clean_slug = slug.strip()
        clean_name = display_name.strip()
        clean_description = description.strip()
        if not _SLUG_PATTERN.fullmatch(clean_slug) or len(clean_slug) > 80:
            raise AppError(
                "invalid_domain_slug",
                "A domain slug must use lowercase letters, numbers, and single hyphens.",
                422,
            )
        if not clean_name or len(clean_name) > 180:
            raise AppError("invalid_domain", "A domain display name is required.", 422)
        if len(clean_description) > 1000:
            raise AppError("invalid_domain", "A domain description is too long.", 422)
        return cls(
            id=uuid4(),
            slug=clean_slug,
            display_name=clean_name,
            description=clean_description,
            active_connection_version_id=None,
            created_by=created_by,
        )

    def with_details(self, *, display_name: str, description: str) -> Domain:
        clean_name = display_name.strip()
        clean_description = description.strip()
        if not clean_name or len(clean_name) > 180:
            raise AppError("invalid_domain", "A domain display name is required.", 422)
        if len(clean_description) > 1000:
            raise AppError("invalid_domain", "A domain description is too long.", 422)
        return replace(
            self,
            display_name=clean_name,
            description=clean_description,
        )


@dataclass(frozen=True, slots=True)
class DomainConnectionVersion:
    id: UUID
    domain_id: UUID
    version: int
    configuration_version_id: UUID
    workspace_ids: tuple[UUID, ...]
    created_by: UUID
    created_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        domain_id: UUID,
        version: int,
        configuration_version_id: UUID,
        workspace_ids: tuple[UUID, ...],
        created_by: UUID,
    ) -> DomainConnectionVersion:
        normalized = tuple(dict.fromkeys(workspace_ids))
        if version < 1 or not normalized or len(normalized) != len(workspace_ids):
            raise AppError(
                "invalid_domain_connection",
                "A domain connection requires a positive version and unique workspaces.",
                422,
            )
        return cls(
            id=uuid4(),
            domain_id=domain_id,
            version=version,
            configuration_version_id=configuration_version_id,
            workspace_ids=normalized,
            created_by=created_by,
        )


@dataclass(frozen=True, slots=True)
class AdminDomainConnectionVersion:
    connection: DomainConnectionVersion
    configuration_name: str
    configuration_version: int


@dataclass(frozen=True, slots=True)
class DomainWorkspaceOption:
    id: UUID
    name: str
    kind: WorkspaceKind
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class DomainView:
    domain: Domain
    connection: DomainConnectionVersion | None
    workspace_options: tuple[DomainWorkspaceOption, ...]
    active: bool
    ready: bool
    search_ready: bool
    answer_ready: bool
    reason_codes: tuple[str, ...]
    generation_execution_preview: GenerationExecutionSnapshot | None = None

    @property
    def allowed_workspace_ids(self) -> tuple[UUID, ...]:
        return tuple(option.id for option in self.workspace_options)


@dataclass(frozen=True, slots=True)
class DomainLibraryContext:
    domain: Domain
    connection: DomainConnectionVersion
    workspace_options: tuple[DomainWorkspaceOption, ...]

    @property
    def allowed_workspace_ids(self) -> tuple[UUID, ...]:
        return tuple(option.id for option in self.workspace_options)


@dataclass(frozen=True, slots=True)
class DomainSearchContext:
    actor_id: UUID
    domain_id: UUID
    connection_version_id: UUID
    configuration_version_id: UUID
    configuration_id: UUID
    workspace_ids: tuple[UUID, ...]
    folder_ids: tuple[UUID, ...]
    document_ids: tuple[UUID, ...] | None = None


class DomainRepository(Protocol):
    async def list_domains(self) -> tuple[Domain, ...]: ...

    async def find_by_slug(self, slug: str) -> Domain | None: ...

    async def find_by_id(self, domain_id: UUID) -> Domain | None: ...

    async def find_connection(
        self, connection_id: UUID
    ) -> DomainConnectionVersion | None: ...

    async def latest_connection(
        self, domain_id: UUID
    ) -> DomainConnectionVersion | None: ...

    async def list_connections(
        self, domain_id: UUID
    ) -> tuple[DomainConnectionVersion, ...]: ...

    async def workspace_options_for_actor(
        self,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
    ) -> tuple[DomainWorkspaceOption, ...]: ...

    async def add_domain(self, domain: Domain) -> Domain: ...

    async def update_domain(self, domain: Domain) -> Domain: ...

    async def next_connection_version(self, domain_id: UUID) -> int: ...

    async def add_connection(
        self, connection: DomainConnectionVersion
    ) -> DomainConnectionVersion: ...

    async def set_active_connection(
        self,
        domain_id: UUID,
        connection_version_id: UUID | None,
    ) -> Domain: ...


class DomainConfigurationPort(Protocol):
    async def find_owner_version(
        self,
        configuration_version_id: UUID,
        actor_id: UUID,
    ) -> SavedRagConfiguration | None: ...

    async def find_domain_version(
        self,
        configuration_version_id: UUID,
    ) -> SavedRagConfiguration | None: ...

    async def readiness(
        self,
        configuration: SavedRagConfiguration,
    ) -> ConfigurationReadiness: ...


async def _no_op_commit() -> None:
    return None


def resolve_allowed_workspaces(
    *,
    domain: tuple[UUID, ...],
    configuration: tuple[UUID, ...],
    actor: tuple[UUID, ...],
) -> tuple[UUID, ...]:
    configuration_set = set(configuration)
    actor_set = set(actor)
    return tuple(
        workspace_id
        for workspace_id in dict.fromkeys(domain)
        if workspace_id in configuration_set and workspace_id in actor_set
    )


class DomainService:
    def __init__(
        self,
        repository: DomainRepository,
        configurations: DomainConfigurationPort,
        *,
        commit: Callable[[], Awaitable[None]] = _no_op_commit,
    ) -> None:
        self.repository = repository
        self.configurations = configurations
        self.commit = commit

    async def list_for_actor(self, actor_id: UUID) -> tuple[DomainView, ...]:
        views: list[DomainView] = []
        for domain in await self.repository.list_domains():
            connection = await self._display_connection(domain)
            if connection is None:
                continue
            view = await self._view(domain, connection, actor_id)
            if view is not None:
                views.append(view)
        return tuple(views)

    async def list_for_owner(self, actor_id: UUID) -> tuple[DomainView, ...]:
        views: list[DomainView] = []
        for domain in await self.repository.list_domains():
            connection = await self._display_connection(domain)
            if connection is None:
                views.append(
                    DomainView(
                        domain=domain,
                        connection=None,
                        workspace_options=(),
                        active=False,
                        ready=False,
                        search_ready=False,
                        answer_ready=False,
                        reason_codes=("domain_connection_missing",),
                    )
                )
                continue
            view = await self._view(domain, connection, actor_id)
            if view is None:
                views.append(
                    DomainView(
                        domain=domain,
                        connection=connection,
                        workspace_options=(),
                        active=(domain.active_connection_version_id == connection.id),
                        ready=False,
                        search_ready=False,
                        answer_ready=False,
                        reason_codes=("domain_scope_unavailable",),
                    )
                )
            else:
                views.append(view)
        return tuple(views)

    async def detail_for_actor(self, slug: str, actor_id: UUID) -> DomainView:
        domain = await self.repository.find_by_slug(slug)
        if domain is None:
            self._not_found()
        assert domain is not None
        connection = await self._display_connection(domain)
        if connection is None:
            self._not_found()
        assert connection is not None
        view = await self._view(domain, connection, actor_id)
        if view is None:
            self._not_found()
        assert view is not None
        return view

    async def resolve_library(
        self,
        *,
        slug: str,
        actor_id: UUID,
    ) -> DomainLibraryContext:
        domain = await self.repository.find_by_slug(slug)
        if domain is None or domain.active_connection_version_id is None:
            self._not_found()
        assert domain is not None
        assert domain.active_connection_version_id is not None
        connection = await self.repository.find_connection(
            domain.active_connection_version_id
        )
        if connection is None or connection.domain_id != domain.id:
            self._not_found()
        assert connection is not None
        configuration = await self.configurations.find_domain_version(
            connection.configuration_version_id
        )
        if configuration is None:
            self._not_found()
        assert configuration is not None
        candidate_options = await self.repository.workspace_options_for_actor(
            actor_id,
            connection.workspace_ids,
        )
        by_id = {option.id: option for option in candidate_options}
        allowed_ids = resolve_allowed_workspaces(
            domain=connection.workspace_ids,
            configuration=configuration.workspace_ids,
            actor=tuple(by_id),
        )
        if not allowed_ids:
            self._not_found()
        return DomainLibraryContext(
            domain=domain,
            connection=connection,
            workspace_options=tuple(by_id[item] for item in allowed_ids),
        )

    async def create_domain(
        self,
        *,
        actor_id: UUID,
        slug: str,
        display_name: str,
        description: str,
    ) -> Domain:
        if await self.repository.find_by_slug(slug.strip()) is not None:
            raise AppError("domain_slug_conflict", "The domain slug is already in use.", 409)
        domain = Domain.create(
            slug=slug,
            display_name=display_name,
            description=description,
            created_by=actor_id,
        )
        saved = await self.repository.add_domain(domain)
        await self.commit()
        return saved

    async def update_domain(
        self,
        *,
        domain_id: UUID,
        display_name: str,
        description: str,
    ) -> Domain:
        domain = await self.repository.find_by_id(domain_id)
        if domain is None:
            self._not_found()
        assert domain is not None
        saved = await self.repository.update_domain(
            domain.with_details(display_name=display_name, description=description)
        )
        await self.commit()
        return saved

    async def connections_for_owner(
        self,
        domain_id: UUID,
    ) -> tuple[AdminDomainConnectionVersion, ...]:
        if await self.repository.find_by_id(domain_id) is None:
            self._not_found()
        result: list[AdminDomainConnectionVersion] = []
        for connection in await self.repository.list_connections(domain_id):
            configuration = await self.configurations.find_domain_version(
                connection.configuration_version_id
            )
            if configuration is None:
                raise AppError(
                    "domain_connection_changed",
                    "The domain connection is no longer available.",
                    409,
                )
            result.append(
                AdminDomainConnectionVersion(
                    connection=connection,
                    configuration_name=configuration.name,
                    configuration_version=configuration.version,
                )
            )
        return tuple(result)

    async def create_connection(
        self,
        *,
        domain_id: UUID,
        actor_id: UUID,
        configuration_version_id: UUID,
        workspace_ids: tuple[UUID, ...],
    ) -> DomainConnectionVersion:
        domain = await self.repository.find_by_id(domain_id)
        if domain is None:
            self._not_found()
        configuration = await self.configurations.find_owner_version(
            configuration_version_id,
            actor_id,
        )
        if configuration is None:
            self._not_found()
        requested = tuple(dict.fromkeys(workspace_ids))
        if not requested or len(requested) != len(workspace_ids):
            raise AppError(
                "invalid_domain_connection",
                "Domain workspaces must be nonempty and unique.",
                422,
            )
        options = await self.repository.workspace_options_for_actor(actor_id, requested)
        authorized = tuple(option.id for option in options)
        allowed = resolve_allowed_workspaces(
            domain=requested,
            configuration=configuration.workspace_ids,
            actor=authorized,
        )
        if allowed != requested:
            self._not_found()
        connection = DomainConnectionVersion.create(
            domain_id=domain_id,
            version=await self.repository.next_connection_version(domain_id),
            configuration_version_id=configuration.version_id,
            workspace_ids=requested,
            created_by=actor_id,
        )
        saved = await self.repository.add_connection(connection)
        await self.commit()
        return saved

    async def activate_connection(
        self,
        *,
        domain_id: UUID,
        connection_version_id: UUID,
        actor_id: UUID,
    ) -> Domain:
        domain = await self.repository.find_by_id(domain_id)
        connection = await self.repository.find_connection(connection_version_id)
        if (
            domain is None
            or connection is None
            or connection.domain_id != domain.id
        ):
            self._not_found()
        configuration = await self.configurations.find_owner_version(
            connection.configuration_version_id,
            actor_id,
        )
        if configuration is None:
            self._not_found()
        options = await self.repository.workspace_options_for_actor(
            actor_id,
            connection.workspace_ids,
        )
        allowed = resolve_allowed_workspaces(
            domain=connection.workspace_ids,
            configuration=configuration.workspace_ids,
            actor=tuple(option.id for option in options),
        )
        if allowed != connection.workspace_ids:
            self._not_found()
        self._validate_configuration_contract(configuration)
        readiness = await self.configurations.readiness(configuration)
        if not readiness.service_ready:
            raise AppError(
                "domain_not_ready",
                "The domain connection is not ready for generative search.",
                409,
            )
        saved = await self.repository.set_active_connection(domain.id, connection.id)
        await self.commit()
        return saved

    async def deactivate(self, *, domain_id: UUID) -> Domain:
        domain = await self.repository.find_by_id(domain_id)
        if domain is None:
            self._not_found()
        assert domain is not None
        saved = await self.repository.set_active_connection(domain.id, None)
        await self.commit()
        return saved

    async def resolve_search(
        self,
        *,
        slug: str,
        actor_id: UUID,
        connection_version_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...] = (),
        document_ids: tuple[UUID, ...] | None = None,
    ) -> DomainSearchContext:
        view = await self.detail_for_actor(slug, actor_id)
        if not view.active:
            raise AppError("domain_inactive", "The domain is not active.", 409)
        assert view.connection is not None
        if connection_version_id != view.connection.id:
            raise AppError(
                "domain_connection_changed",
                "The domain connection changed. Start a new conversation.",
                409,
            )
        if not view.ready:
            raise AppError(
                "domain_not_ready",
                "The domain connection is not ready for generative search.",
                409,
            )
        requested = tuple(dict.fromkeys(workspace_ids))
        if not requested:
            raise AppError(
                "search_scope_empty",
                "At least one authorized workspace is required.",
                422,
            )
        if not set(requested).issubset(view.allowed_workspace_ids):
            self._not_found()
        configuration = await self.configurations.find_domain_version(
            view.connection.configuration_version_id
        )
        if configuration is None:
            raise AppError(
                "domain_connection_changed",
                "The domain connection changed. Start a new conversation.",
                409,
            )
        return DomainSearchContext(
            actor_id=actor_id,
            domain_id=view.domain.id,
            connection_version_id=view.connection.id,
            configuration_version_id=configuration.version_id,
            configuration_id=configuration.id,
            workspace_ids=requested,
            folder_ids=tuple(dict.fromkeys(folder_ids)),
            document_ids=document_ids,
        )

    async def _display_connection(
        self, domain: Domain
    ) -> DomainConnectionVersion | None:
        if domain.active_connection_version_id is not None:
            return await self.repository.find_connection(
                domain.active_connection_version_id
            )
        return await self.repository.latest_connection(domain.id)

    async def _view(
        self,
        domain: Domain,
        connection: DomainConnectionVersion,
        actor_id: UUID,
    ) -> DomainView | None:
        configuration = await self.configurations.find_domain_version(
            connection.configuration_version_id
        )
        if configuration is None:
            return None
        candidate_options = await self.repository.workspace_options_for_actor(
            actor_id,
            connection.workspace_ids,
        )
        by_id = {option.id: option for option in candidate_options}
        allowed_ids = resolve_allowed_workspaces(
            domain=connection.workspace_ids,
            configuration=configuration.workspace_ids,
            actor=tuple(by_id),
        )
        if not allowed_ids:
            return None
        options = tuple(by_id[workspace_id] for workspace_id in allowed_ids)
        active = domain.active_connection_version_id == connection.id
        reasons: list[str] = []
        if not active:
            reasons.append("domain_inactive")
        if configuration.evaluation_state is not EvaluationState.PASSED:
            reasons.append("configuration_not_evaluated")
        if (
            configuration.answer_policy_version.mode != "generative"
            or configuration.generation_profile_id is None
        ):
            reasons.append("generation_not_configured")
        readiness = await self.configurations.readiness(configuration)
        reasons.extend(readiness.search_reasons)
        reasons.extend(readiness.answer_reasons)
        reason_codes = tuple(dict.fromkeys(reasons))
        ready = active and not reason_codes and readiness.service_ready
        return DomainView(
            domain=domain,
            connection=connection,
            workspace_options=options,
            active=active,
            ready=ready,
            search_ready=readiness.search_ready,
            answer_ready=readiness.answer_ready,
            reason_codes=reason_codes,
            generation_execution_preview=readiness.generation_execution_preview,
        )

    @staticmethod
    def _validate_configuration_contract(
        configuration: SavedRagConfiguration,
    ) -> None:
        if configuration.evaluation_state is not EvaluationState.PASSED:
            raise AppError(
                "configuration_not_evaluated",
                "The configuration requires a passing evaluation.",
                409,
            )
        if (
            configuration.answer_policy_version.mode != "generative"
            or configuration.generation_profile_id is None
        ):
            raise AppError(
                "generation_not_configured",
                "The configuration requires generation.",
                409,
            )

    @staticmethod
    def _not_found() -> NoReturn:
        raise AppError("not_found", "The requested resource was not found.", 404)
