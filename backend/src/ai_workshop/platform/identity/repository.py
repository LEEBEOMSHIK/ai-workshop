from typing import Protocol
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.identity.models import UserRecord


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
        """Serialize the one-time owner setup within the current transaction."""
        await self.session.execute(text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))

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
