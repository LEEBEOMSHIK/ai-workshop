from typing import Protocol
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.identity.authorization_models import (
    AuthorityAuditRecord,
    AuthorizationStateRecord,
    UserAuthorizationStateRecord,
)
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.shared.errors import AppError


class UserRepository(Protocol):
    async def find_by_normalized_email(self, normalized_email: str) -> User | None: ...

    async def find_by_id(self, user_id: UUID) -> User | None: ...

    async def owner_exists(self) -> bool: ...

    async def add(self, user: User) -> User: ...


def _to_domain(record: UserRecord) -> User:
    return User(
        id=record.id,
        display_name=record.display_name,
        email=record.email,
        normalized_email=record.normalized_email,
        password_hash=record.password_hash,
        role=UserRole(record.role),
        is_active=record.is_active,
    )


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_normalized_email(self, normalized_email: str) -> User | None:
        result = await self.session.execute(
            select(UserRecord).where(UserRecord.normalized_email == normalized_email)
        )
        record = result.scalar_one_or_none()
        return _to_domain(record) if record else None

    async def find_by_id(self, user_id: UUID) -> User | None:
        record = await self.session.get(UserRecord, user_id)
        return _to_domain(record) if record else None

    async def owner_exists(self) -> bool:
        result = await self.session.execute(
            select(UserRecord.id).where(UserRecord.role == UserRole.OWNER).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def lock_owner_setup(self) -> None:
        """Serialize bootstrap on the shared authorization singleton."""
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
        if initialized:
            raise AppError(
                "setup_already_completed",
                "Initial setup has already been completed.",
                409,
            )

    async def owner_setup_required(self) -> bool:
        initialized = await self.session.scalar(
            select(AuthorizationStateRecord.initialized).where(AuthorizationStateRecord.id == 1)
        )
        return initialized is False

    async def complete_owner_setup(self, owner_id: UUID) -> None:
        self.session.add(UserAuthorizationStateRecord(user_id=owner_id, revision=0))
        self.session.add(
            AuthorityAuditRecord(
                actor_id=None,
                target_user_id=owner_id,
                event_type="authorization_bootstrap",
                technology_key=None,
                before={"initialized": False},
                after={
                    "initialized": True,
                    "role": UserRole.OWNER.value,
                    "is_active": True,
                    "revision": 0,
                    "technologies": {},
                },
            )
        )
        updated = await self.session.scalar(
            update(AuthorizationStateRecord)
            .where(
                AuthorizationStateRecord.id == 1,
                AuthorizationStateRecord.initialized.is_(False),
            )
            .values(initialized=True)
            .returning(AuthorizationStateRecord.id)
        )
        if updated != 1:
            raise AppError(
                "setup_already_completed",
                "Initial setup has already been completed.",
                409,
            )
        await self.session.flush()

    async def add(self, user: User) -> User:
        record = UserRecord(
            id=user.id,
            display_name=user.display_name,
            email=user.email,
            normalized_email=user.normalized_email,
            password_hash=user.password_hash,
            role=user.role,
            is_active=user.is_active,
        )
        self.session.add(record)
        await self.session.flush()
        return _to_domain(record)
