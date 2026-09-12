from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from ai_workshop.platform.identity.authorization import Capability
from ai_workshop.platform.identity.authorization_models import (
    AuthorityAuditRecord,
    AuthorizationStateRecord,
    TechnologyGrantRecord,
    UserAuthorizationStateRecord,
)
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.shared.errors import AppError


@dataclass(frozen=True, slots=True)
class AuthorityUser:
    id: UUID
    display_name: str
    email: str
    role: UserRole
    is_active: bool
    revision: int
    grants: Mapping[str, frozenset[Capability]]


@dataclass(frozen=True, slots=True)
class AuthorityAuditEntry:
    id: int | None
    actor_id: UUID | None
    target_user_id: UUID
    event_type: str
    technology_key: str | None
    before: Mapping[str, object]
    after: Mapping[str, object]
    created_at: datetime | None = None


class AuthorizationRepository(Protocol):
    async def get_authority(self, user_id: UUID) -> AuthorityUser | None: ...

    async def list_authorities(self, cursor: UUID | None, limit: int) -> list[AuthorityUser]: ...

    async def lock_authorization_state(self) -> None: ...

    async def lock_users(self, user_ids: tuple[UUID, ...]) -> None: ...

    async def count_active_masters(self) -> int: ...

    async def replace_grant(
        self,
        user_id: UUID,
        technology_key: str,
        capabilities: frozenset[Capability],
    ) -> None: ...

    async def clear_grants(self, user_id: UUID) -> None: ...

    async def set_status(self, user_id: UUID, is_active: bool) -> None: ...

    async def set_role(self, user_id: UUID, role: UserRole) -> None: ...

    async def increment_revision(self, user_id: UUID) -> int: ...

    async def append_audit(self, entry: AuthorityAuditEntry) -> None: ...

    async def list_audit(
        self, target_user_id: UUID, cursor: int | None, limit: int
    ) -> list[AuthorityAuditEntry]: ...


class SqlAlchemyAuthorizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_authority(self, user_id: UUID) -> AuthorityUser | None:
        await self._require_initialized_state()
        rows = (
            await self.session.execute(
                _authority_snapshot_statement().where(UserRecord.id == user_id)
            )
        ).mappings().all()
        authorities = _authorities_from_snapshot_rows(rows)
        return authorities[0] if authorities else None

    async def list_authorities(self, cursor: UUID | None, limit: int) -> list[AuthorityUser]:
        await self._require_initialized_state()
        statement = select(UserRecord.id.label("user_id")).order_by(UserRecord.id).limit(limit)
        if cursor is not None:
            statement = statement.where(UserRecord.id > cursor)
        page = statement.cte("authority_user_page")
        rows = (
            await self.session.execute(
                _authority_snapshot_statement()
                .join(page, page.c.user_id == UserRecord.id)
                .order_by(UserRecord.id, TechnologyGrantRecord.technology_key)
            )
        ).mappings().all()
        return _authorities_from_snapshot_rows(rows)

    async def lock_authorization_state(self) -> None:
        initialized = await self.session.scalar(
            select(AuthorizationStateRecord.initialized)
            .where(AuthorizationStateRecord.id == 1)
            .with_for_update()
        )
        if initialized is None:
            raise AppError(
                "authorization_migration_required",
                "Authorization storage is unavailable; apply the required migration.",
                409,
            )
        if not initialized:
            raise AppError(
                "authorization_not_initialized",
                "Authorization has not been initialized.",
                409,
            )

    async def _require_initialized_state(self) -> None:
        initialized = await self.session.scalar(
            select(AuthorizationStateRecord.initialized).where(AuthorizationStateRecord.id == 1)
        )
        if initialized is None:
            raise AppError(
                "authorization_migration_required",
                "Authorization storage is unavailable; apply the required migration.",
                409,
            )
        if not initialized:
            raise AppError(
                "authorization_not_initialized",
                "Authorization has not been initialized.",
                409,
            )

    async def lock_users(self, user_ids: tuple[UUID, ...]) -> None:
        await self.session.execute(
            select(UserRecord.id)
            .where(UserRecord.id.in_(user_ids))
            .order_by(UserRecord.id)
            .with_for_update()
        )

    async def count_active_masters(self) -> int:
        count = await self.session.scalar(
            select(func.count())
            .select_from(UserRecord)
            .where(UserRecord.role == UserRole.OWNER, UserRecord.is_active.is_(True))
        )
        return int(count or 0)

    async def replace_grant(
        self,
        user_id: UUID,
        technology_key: str,
        capabilities: frozenset[Capability],
    ) -> None:
        await self.session.execute(
            delete(TechnologyGrantRecord).where(
                TechnologyGrantRecord.user_id == user_id,
                TechnologyGrantRecord.technology_key == technology_key,
            )
        )
        if capabilities:
            self.session.add(
                TechnologyGrantRecord(
                    user_id=user_id,
                    technology_key=technology_key,
                    can_view=Capability.VIEW in capabilities,
                    can_configure=Capability.CONFIGURE in capabilities,
                    can_execute=Capability.EXECUTE in capabilities,
                )
            )
        await self.session.flush()

    async def clear_grants(self, user_id: UUID) -> None:
        await self.session.execute(
            delete(TechnologyGrantRecord).where(TechnologyGrantRecord.user_id == user_id)
        )

    async def set_status(self, user_id: UUID, is_active: bool) -> None:
        await self.session.execute(
            update(UserRecord).where(UserRecord.id == user_id).values(is_active=is_active)
        )

    async def set_role(self, user_id: UUID, role: UserRole) -> None:
        await self.session.execute(
            update(UserRecord).where(UserRecord.id == user_id).values(role=role)
        )

    async def increment_revision(self, user_id: UUID) -> int:
        revision = await self.session.scalar(
            update(UserAuthorizationStateRecord)
            .where(UserAuthorizationStateRecord.user_id == user_id)
            .values(revision=UserAuthorizationStateRecord.revision + 1)
            .returning(UserAuthorizationStateRecord.revision)
        )
        if revision is None:
            raise AppError(
                "authorization_state_missing",
                "Authorization storage is incomplete; apply the required migration.",
                409,
            )
        return revision

    async def append_audit(self, entry: AuthorityAuditEntry) -> None:
        self.session.add(
            AuthorityAuditRecord(
                actor_id=entry.actor_id,
                target_user_id=entry.target_user_id,
                event_type=entry.event_type,
                technology_key=entry.technology_key,
                before=dict(entry.before),
                after=dict(entry.after),
            )
        )
        await self.session.flush()

    async def list_audit(
        self, target_user_id: UUID, cursor: int | None, limit: int
    ) -> list[AuthorityAuditEntry]:
        statement = (
            select(
                AuthorityAuditRecord.id,
                AuthorityAuditRecord.actor_id,
                AuthorityAuditRecord.target_user_id,
                AuthorityAuditRecord.event_type,
                AuthorityAuditRecord.technology_key,
                AuthorityAuditRecord.before,
                AuthorityAuditRecord.after,
                AuthorityAuditRecord.created_at,
            )
            .where(AuthorityAuditRecord.target_user_id == target_user_id)
            .order_by(AuthorityAuditRecord.id.desc())
            .limit(limit)
        )
        if cursor is not None:
            statement = statement.where(AuthorityAuditRecord.id < cursor)
        rows = (await self.session.execute(statement)).all()
        return [
            AuthorityAuditEntry(
                id=row.id,
                actor_id=row.actor_id,
                target_user_id=row.target_user_id,
                event_type=row.event_type,
                technology_key=row.technology_key,
                before=row.before,
                after=row.after,
                created_at=row.created_at,
            )
            for row in rows
        ]


def _capabilities_from_flags(
    can_view: bool,
    can_configure: bool,
    can_execute: bool,
) -> frozenset[Capability]:
    return frozenset(
        capability
        for capability, enabled in (
            (Capability.VIEW, can_view),
            (Capability.CONFIGURE, can_configure),
            (Capability.EXECUTE, can_execute),
        )
        if enabled
    )


def _authority_snapshot_statement() -> Select[Any]:
    return (
        select(
            UserRecord.id.label("user_id"),
            UserRecord.display_name.label("display_name"),
            UserRecord.email.label("email"),
            UserRecord.role.label("role"),
            UserRecord.is_active.label("is_active"),
            UserAuthorizationStateRecord.revision.label("revision"),
            TechnologyGrantRecord.technology_key.label("technology_key"),
            TechnologyGrantRecord.can_view.label("can_view"),
            TechnologyGrantRecord.can_configure.label("can_configure"),
            TechnologyGrantRecord.can_execute.label("can_execute"),
        )
        .select_from(UserRecord)
        .outerjoin(
            UserAuthorizationStateRecord,
            UserAuthorizationStateRecord.user_id == UserRecord.id,
        )
        .outerjoin(
            TechnologyGrantRecord,
            TechnologyGrantRecord.user_id == UserRecord.id,
        )
    )


def _authorities_from_snapshot_rows(rows: Sequence[RowMapping]) -> list[AuthorityUser]:
    authorities: dict[UUID, AuthorityUser] = {}
    grants_by_user: dict[UUID, dict[str, frozenset[Capability]]] = {}
    for row in rows:
        user_id = row["user_id"]
        revision = row["revision"]
        if revision is None:
            raise AppError(
                "authorization_state_missing",
                "Authorization storage is incomplete; apply the required migration.",
                409,
            )
        if user_id not in authorities:
            grants: dict[str, frozenset[Capability]] = {}
            grants_by_user[user_id] = grants
            authorities[user_id] = AuthorityUser(
                id=user_id,
                display_name=row["display_name"],
                email=row["email"],
                role=UserRole(row["role"]),
                is_active=row["is_active"],
                revision=revision,
                grants=grants,
            )
        technology_key = row["technology_key"]
        if technology_key is not None:
            grants_by_user[user_id][technology_key] = _capabilities_from_flags(
                row["can_view"],
                row["can_configure"],
                row["can_execute"],
            )
    return list(authorities.values())
