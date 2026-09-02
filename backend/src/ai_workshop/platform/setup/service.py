from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.identity.repository import SqlAlchemyUserRepository
from ai_workshop.platform.identity.service import (
    Argon2PasswordHasher,
    JwtTokenService,
    PasswordHasher,
)
from ai_workshop.platform.workspaces.domain import WorkspaceKind
from ai_workshop.platform.workspaces.repository import SqlAlchemyWorkspaceRepository
from ai_workshop.platform.workspaces.service import WorkspaceService
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError


class OwnerSetupRepository(Protocol):
    async def lock_owner_setup(self) -> None: ...

    async def owner_exists(self) -> bool: ...

    async def add(self, user: User) -> User: ...


class SessionTokenIssuer(Protocol):
    def create(self, user: User) -> str: ...


class SystemSetupService:
    def __init__(
        self,
        users: OwnerSetupRepository,
        workspaces: WorkspaceService,
        password_hasher: PasswordHasher,
        tokens: SessionTokenIssuer,
        settings: Settings,
    ) -> None:
        self.users = users
        self.workspaces = workspaces
        self.password_hasher = password_hasher
        self.tokens = tokens
        self.settings = settings

    async def setup_required(self) -> bool:
        return self.settings.environment == "local" and not await self.users.owner_exists()

    async def create_owner(
        self,
        *,
        display_name: str,
        email: str,
        password: str,
        password_confirmation: str,
    ) -> tuple[User, str]:
        if self.settings.environment != "local":
            raise AppError("setup_unavailable", "Initial setup is unavailable.", 404)
        if password != password_confirmation:
            raise AppError(
                "password_confirmation_mismatch",
                "Password confirmation does not match.",
                422,
            )
        if len(password) < 12:
            raise AppError(
                "password_too_short",
                "Password must contain at least 12 characters.",
                422,
            )

        await self.users.lock_owner_setup()
        if await self.users.owner_exists():
            raise AppError(
                "setup_already_completed",
                "Initial setup has already been completed.",
                409,
            )

        owner = await self.users.add(
            User.create_owner(
                display_name=display_name,
                email=email,
                password_hash=self.password_hasher.hash(password),
            )
        )
        await self.workspaces.create(
            name=self.settings.setup_company_workspace_name,
            kind=WorkspaceKind.COMPANY,
            creator=owner,
        )
        await self.workspaces.create(
            name=self.settings.setup_personal_workspace_name,
            kind=WorkspaceKind.PERSONAL,
            creator=owner,
        )
        return owner, self.tokens.create(owner)


def get_system_setup_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SystemSetupService:
    return SystemSetupService(
        SqlAlchemyUserRepository(session),
        WorkspaceService(SqlAlchemyWorkspaceRepository(session)),
        Argon2PasswordHasher(),
        JwtTokenService(settings),
        settings,
    )
