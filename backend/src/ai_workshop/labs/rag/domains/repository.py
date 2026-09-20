from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings
from ai_workshop.labs.rag.configurations.domain import SavedRagConfiguration
from ai_workshop.labs.rag.configurations.repository import (
    SqlAlchemyRagConfigurationRepository,
    SqlAlchemySearchConfigurationResolver,
)
from ai_workshop.labs.rag.configurations.service import (
    ConfigurationReadiness,
    RagConfigurationService,
)
from ai_workshop.labs.rag.domains.models import (
    RagDomainConnectionVersionRecord,
    RagDomainConnectionWorkspaceRecord,
    RagDomainRecord,
)
from ai_workshop.labs.rag.domains.service import (
    Domain,
    DomainConnectionVersion,
    DomainWorkspaceOption,
)
from ai_workshop.labs.rag.generation.readiness import SqlAlchemyGenerationReadiness
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand
from ai_workshop.labs.rag.search.configuration_port import ResolvedSearchConfiguration
from ai_workshop.platform.workspaces.domain import WorkspaceKind
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.platform.workspaces.permissions import workspace_read_allowed
from ai_workshop.platform.workspaces.repository import workspace_is_active
from ai_workshop.shared.errors import AppError


class SqlAlchemyDomainSearchConfigurationResolver(SqlAlchemySearchConfigurationResolver):
    """Trusted exact resolver used only after DomainService authorizes an actor."""

    async def resolve_domain_version(
        self,
        configuration_version_id: UUID,
        actor_id: UUID,
    ) -> ResolvedSearchConfiguration:
        configuration = await self.repository.find_server_bound_version(configuration_version_id)
        if configuration is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return await self._resolve(configuration, actor_id)


def _to_domain(record: RagDomainRecord) -> Domain:
    return Domain(
        id=record.id,
        slug=record.slug,
        display_name=record.display_name,
        description=record.description,
        active_connection_version_id=record.active_connection_version_id,
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class SqlAlchemyDomainRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_domains(self) -> tuple[Domain, ...]:
        records = await self.session.scalars(
            select(RagDomainRecord).order_by(RagDomainRecord.display_name, RagDomainRecord.id)
        )
        return tuple(_to_domain(record) for record in records)

    async def find_by_slug(self, slug: str) -> Domain | None:
        record = await self.session.scalar(
            select(RagDomainRecord).where(RagDomainRecord.slug == slug)
        )
        return _to_domain(record) if record is not None else None

    async def find_by_id(self, domain_id: UUID) -> Domain | None:
        record = await self.session.get(RagDomainRecord, domain_id)
        return _to_domain(record) if record is not None else None

    async def find_connection(self, connection_id: UUID) -> DomainConnectionVersion | None:
        record = await self.session.get(RagDomainConnectionVersionRecord, connection_id)
        return await self._connection(record) if record is not None else None

    async def latest_connection(self, domain_id: UUID) -> DomainConnectionVersion | None:
        record = await self.session.scalar(
            select(RagDomainConnectionVersionRecord)
            .where(RagDomainConnectionVersionRecord.domain_id == domain_id)
            .order_by(RagDomainConnectionVersionRecord.version.desc())
            .limit(1)
        )
        return await self._connection(record) if record is not None else None

    async def list_connections(self, domain_id: UUID) -> tuple[DomainConnectionVersion, ...]:
        records = (
            await self.session.scalars(
                select(RagDomainConnectionVersionRecord)
                .where(RagDomainConnectionVersionRecord.domain_id == domain_id)
                .order_by(RagDomainConnectionVersionRecord.version.desc())
            )
        ).all()
        return tuple([await self._connection(record) for record in records])

    async def workspace_options_for_actor(
        self,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
    ) -> tuple[DomainWorkspaceOption, ...]:
        if not workspace_ids:
            return ()
        rows = (
            await self.session.scalars(
                select(WorkspaceRecord)
                .join(
                    WorkspaceMembershipRecord,
                    and_(
                        WorkspaceMembershipRecord.workspace_id == WorkspaceRecord.id,
                        WorkspaceMembershipRecord.user_id == actor_id,
                    ),
                )
                .where(
                    WorkspaceRecord.id.in_(workspace_ids),
                    workspace_is_active(),
                    workspace_read_allowed(actor_id),
                    or_(
                        WorkspaceRecord.kind != WorkspaceKind.PERSONAL,
                        WorkspaceRecord.created_by == actor_id,
                    ),
                )
            )
        ).all()
        by_id = {record.id: record for record in rows}
        return tuple(
            DomainWorkspaceOption(
                id=by_id[workspace_id].id,
                name=by_id[workspace_id].name,
                kind=WorkspaceKind(by_id[workspace_id].kind),
                expires_at=by_id[workspace_id].expires_at,
            )
            for workspace_id in workspace_ids
            if workspace_id in by_id
        )

    async def add_domain(self, domain: Domain) -> Domain:
        record = RagDomainRecord(
            id=domain.id,
            slug=domain.slug,
            display_name=domain.display_name,
            description=domain.description,
            active_connection_version_id=None,
            created_by=domain.created_by,
        )
        self.session.add(record)
        await self.session.flush()
        return _to_domain(record)

    async def update_domain(self, domain: Domain) -> Domain:
        record = await self.session.get(RagDomainRecord, domain.id, with_for_update=True)
        if record is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        record.display_name = domain.display_name
        record.description = domain.description
        await self.session.flush()
        await self.session.refresh(record, attribute_names=["updated_at"])
        return _to_domain(record)

    async def next_connection_version(self, domain_id: UUID) -> int:
        domain = await self.session.scalar(
            select(RagDomainRecord).where(RagDomainRecord.id == domain_id).with_for_update()
        )
        if domain is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        latest = await self.session.scalar(
            select(func.max(RagDomainConnectionVersionRecord.version)).where(
                RagDomainConnectionVersionRecord.domain_id == domain_id
            )
        )
        return int(latest or 0) + 1

    async def add_connection(self, connection: DomainConnectionVersion) -> DomainConnectionVersion:
        record = RagDomainConnectionVersionRecord(
            id=connection.id,
            domain_id=connection.domain_id,
            version=connection.version,
            configuration_version_id=connection.configuration_version_id,
            created_by=connection.created_by,
        )
        self.session.add(record)
        await self.session.flush()
        self.session.add_all(
            [
                RagDomainConnectionWorkspaceRecord(
                    connection_version_id=connection.id,
                    configuration_version_id=connection.configuration_version_id,
                    workspace_id=workspace_id,
                )
                for workspace_id in connection.workspace_ids
            ]
        )
        await self.session.flush()
        return await self._connection(record)

    async def set_active_connection(
        self,
        domain_id: UUID,
        connection_version_id: UUID | None,
    ) -> Domain:
        record = await self.session.scalar(
            select(RagDomainRecord).where(RagDomainRecord.id == domain_id).with_for_update()
        )
        if record is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        if connection_version_id is not None:
            connection = await self.session.get(
                RagDomainConnectionVersionRecord, connection_version_id
            )
            if connection is None or connection.domain_id != domain_id:
                raise AppError("not_found", "The requested resource was not found.", 404)
        record.active_connection_version_id = connection_version_id
        await self.session.flush()
        await self.session.refresh(record, attribute_names=["updated_at"])
        return _to_domain(record)

    async def _connection(
        self, record: RagDomainConnectionVersionRecord
    ) -> DomainConnectionVersion:
        workspace_ids = tuple(
            await self.session.scalars(
                select(RagDomainConnectionWorkspaceRecord.workspace_id)
                .where(RagDomainConnectionWorkspaceRecord.connection_version_id == record.id)
                .order_by(RagDomainConnectionWorkspaceRecord.workspace_id)
            )
        )
        return DomainConnectionVersion(
            id=record.id,
            domain_id=record.domain_id,
            version=record.version,
            configuration_version_id=record.configuration_version_id,
            workspace_ids=workspace_ids,
            created_by=record.created_by,
            created_at=record.created_at,
        )


class _UnusedIngestionJobs:
    async def ensure_indexed(self, _command: EnsureIndexedCommand) -> UUID:
        raise AssertionError("Domain readiness must not create ingestion jobs.")


class SqlAlchemyDomainConfigurationProvider:
    def __init__(
        self, session: AsyncSession, settings: Settings, *, actor_id: UUID | None = None
    ) -> None:
        self.repository = SqlAlchemyRagConfigurationRepository(session)
        self.service = RagConfigurationService(
            self.repository,
            _UnusedIngestionJobs(),
            generation_readiness=SqlAlchemyGenerationReadiness(
                session, settings, actor_id=actor_id
            ),
            environment=settings.environment,
        )

    async def find_owner_version(
        self,
        configuration_version_id: UUID,
        actor_id: UUID,
    ) -> SavedRagConfiguration | None:
        return await self.repository.find_version_visible(configuration_version_id, actor_id)

    async def find_domain_version(
        self,
        configuration_version_id: UUID,
    ) -> SavedRagConfiguration | None:
        return await self.repository.find_server_bound_version(configuration_version_id)

    async def readiness(self, configuration: SavedRagConfiguration) -> ConfigurationReadiness:
        return (await self.service.readiness((configuration,)))[configuration.version_id]
