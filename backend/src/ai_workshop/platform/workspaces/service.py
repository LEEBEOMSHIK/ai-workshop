from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.workspaces.domain import Workspace, WorkspaceKind
from ai_workshop.platform.workspaces.repository import (
    SqlAlchemyWorkspaceRepository,
    WorkspaceRepository,
)
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError


class WorkspaceService:
    def __init__(self, repository: WorkspaceRepository) -> None:
        self.repository = repository

    async def list_for(self, user: User) -> list[Workspace]:
        return await self.repository.list_for_user(user.id)

    async def create(
        self,
        *,
        name: str,
        kind: WorkspaceKind,
        creator: User,
        expires_at: datetime | None = None,
    ) -> Workspace:
        if kind is WorkspaceKind.PERSONAL and await self.repository.has_personal(creator.id):
            raise AppError("personal_workspace_exists", "A personal workspace already exists.", 409)
        try:
            workspace = Workspace.create(
                name=name, kind=kind, creator=creator, expires_at=expires_at
            )
        except ValueError as exc:
            raise AppError("invalid_workspace", str(exc), 422) from exc
        return await self.repository.add(workspace, creator.id)


def get_workspace_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkspaceService:
    return WorkspaceService(SqlAlchemyWorkspaceRepository(session))
