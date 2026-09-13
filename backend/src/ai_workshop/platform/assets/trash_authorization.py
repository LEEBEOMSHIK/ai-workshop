"""Current database authorization for asset trash actions."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.assets.trash_policy import TrashAction, allows_trash_action
from ai_workshop.platform.workspaces.domain import WorkspaceCapabilities
from ai_workshop.platform.workspaces.member_repository import (
    SqlAlchemyWorkspaceMemberRepository,
)
from ai_workshop.platform.workspaces.permissions import (
    lock_workspace_memberships,
    not_found,
)


async def require_trash_action(
    session: AsyncSession,
    actor_id: UUID,
    workspace_id: UUID,
    action: TrashAction,
) -> WorkspaceCapabilities:
    """Require current workspace authority for one trash action."""
    repository = SqlAlchemyWorkspaceMemberRepository(session)
    capabilities = await repository.capabilities(actor_id, workspace_id)
    if not allows_trash_action(capabilities, action):
        raise not_found()
    if action is not TrashAction.LIST:
        await lock_workspace_memberships(session, workspace_id, (actor_id,))
        capabilities = await repository.capabilities(actor_id, workspace_id)
        if not allows_trash_action(capabilities, action):
            raise not_found()
    return capabilities
