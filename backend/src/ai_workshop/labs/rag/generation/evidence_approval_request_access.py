"""Current document access and mutation locks; owner is not a personal-space bypass."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.assets.library_repository import SqlAlchemyLibraryRepository
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.shared.errors import AppError


def not_found() -> AppError:
    return AppError("not_found", "The requested resource was not found.", 404)


async def require_current_expiry(session: AsyncSession, workspace_id: UUID) -> None:
    """Time can advance while locks wait even though the workspace row is locked."""
    workspace = await session.get(WorkspaceRecord, workspace_id)
    if workspace is None or (
        workspace.kind == "temporary"
        and (workspace.expires_at is None or workspace.expires_at <= datetime.now(UTC))
    ):
        raise not_found()


async def actor_access(
    session: AsyncSession, actor_id: UUID, *, admin: bool, environment: str, lock: bool = False
) -> UserRecord:
    query = select(UserRecord).where(UserRecord.id == actor_id)
    if lock:
        query = query.with_for_update(read=True)
    actor = await session.scalar(query)
    if actor is None or not actor.is_active:
        raise AppError("unauthenticated", "Authentication is required.", 401)
    if admin and (actor.role != "owner" or environment not in {"local", "test"}):
        raise AppError("evidence_request_forbidden", "A development owner is required.", 403)
    return actor


async def revision_access(
    session: AsyncSession, revision_id: UUID, actor_ids: tuple[UUID, ...], *, lock: bool = False
) -> tuple[AssetVersionRecord, DocumentRecord]:
    ids = (
        await session.execute(
            select(AssetVersionRecord.document_id, DocumentRecord.workspace_id)
            .join(DocumentRecord, DocumentRecord.id == AssetVersionRecord.document_id)
            .where(AssetVersionRecord.id == revision_id)
        )
    ).one_or_none()
    if ids is None:
        raise not_found()
    if lock:
        await session.scalar(
            select(WorkspaceRecord)
            .where(WorkspaceRecord.id == ids.workspace_id)
            .with_for_update(read=True)
        )
        for actor_id in sorted(set(actor_ids)):
            await session.scalar(
                select(WorkspaceMembershipRecord)
                .where(
                    WorkspaceMembershipRecord.workspace_id == ids.workspace_id,
                    WorkspaceMembershipRecord.user_id == actor_id,
                )
                .with_for_update(read=True)
            )
    # Reuse current library membership/expiry guard, with explicit personal ownership.
    for actor_id in actor_ids:
        workspace = await SqlAlchemyLibraryRepository(session).workspace_for_user(
            actor_id, ids.workspace_id
        )
        if workspace is None or (workspace.kind == "personal" and workspace.created_by != actor_id):
            raise not_found()
        if workspace.kind == "temporary" and (
            workspace.expires_at is None or workspace.expires_at <= datetime.now(UTC)
        ):
            raise not_found()
    asset_query = select(AssetVersionRecord).where(AssetVersionRecord.id == revision_id)
    document_query = select(DocumentRecord).where(DocumentRecord.id == ids.document_id)
    if lock:
        asset_query = asset_query.with_for_update()
        document_query = document_query.with_for_update(read=True)
    asset = await session.scalar(asset_query)
    document = await session.scalar(document_query)
    if (
        asset is None
        or document is None
        or asset.document_id != document.id
        or document.workspace_id != ids.workspace_id
    ):
        raise not_found()
    return asset, document
