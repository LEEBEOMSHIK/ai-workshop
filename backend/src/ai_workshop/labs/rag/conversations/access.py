"""Revalidate stored source identities against current SQL authority, never saved ACLs."""

import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.conversations.domain import Turn
from ai_workshop.labs.rag.conversations.schemas import ConversationTurnCreate
from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord, RagProjectionRecord
from ai_workshop.labs.rag.generation.codex_approval_models import EvidenceApprovalStateRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import workspace_read_allowed


def source_identities(value: object) -> set[tuple[UUID, UUID, UUID]]:
    result: set[tuple[UUID, UUID, UUID]] = set()
    if isinstance(value, dict):
        if all(key in value for key in ("document_id", "asset_version_id", "projection_id")):
            result.add(
                (
                    UUID(str(value["document_id"])),
                    UUID(str(value["asset_version_id"])),
                    UUID(str(value["projection_id"])),
                )
            )
        for child in value.values():
            result.update(source_identities(child))
    elif isinstance(value, list):
        for child in value:
            result.update(source_identities(child))
    return result


class ConversationAccess:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def identity(self, actor_id: UUID, request: ConversationTurnCreate) -> str:
        async with self.sessions() as session:
            query = (
                select(DocumentRecord.id, DocumentRecord.active_version_id)
                .join(
                    WorkspaceRecord,
                    WorkspaceRecord.id == DocumentRecord.workspace_id,
                )
                .where(
                    DocumentRecord.workspace_id.in_(request.workspace_ids),
                    DocumentRecord.lifecycle == "active",
                    workspace_read_allowed(actor_id),
                )
            )
            if request.document_ids is not None:
                query = query.where(DocumentRecord.id.in_(request.document_ids))
            if request.folder_ids:
                query = query.where(DocumentRecord.folder_id.in_(request.folder_ids))
            rows = (await session.execute(query.order_by(DocumentRecord.id))).all()
            versions = [version for _, version in rows if version is not None]
            builds = (
                await session.execute(
                    select(RagProjectionRecord.id, RagIndexBuildRecord.id)
                    .join(
                        RagIndexBuildRecord,
                        RagIndexBuildRecord.projection_id == RagProjectionRecord.id,
                    )
                    .where(
                        RagProjectionRecord.asset_version_id.in_(versions),
                        RagProjectionRecord.status == "ready",
                        RagIndexBuildRecord.status == "ready",
                        RagIndexBuildRecord.is_active.is_(True),
                    )
                    .order_by(RagProjectionRecord.id, RagIndexBuildRecord.id)
                )
            ).all()
            payload = {
                "connection": str(request.connection_version_id),
                "workspaces": sorted(map(str, request.workspace_ids)),
                "folders": sorted(map(str, request.folder_ids)),
                "selected": sorted(map(str, request.document_ids or [])),
                "mode": request.document_ids is not None,
                "versions": [(str(a), str(b)) for a, b in rows],
                "builds": [(str(a), str(b)) for a, b in builds],
            }
            return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    async def visible(self, actor_id: UUID, turn: Turn, *, external: bool = False) -> bool:
        identities = source_identities(turn.response)
        async with self.sessions() as session:
            # Even an unanswered turn may expose selected scope identifiers or user text.
            workspace_ids = [
                UUID(str(item)) for item in cast_list(turn.request.get("workspace_ids"))
            ]
            permitted = set(
                (
                    await session.scalars(
                        select(WorkspaceRecord.id).where(
                            WorkspaceRecord.id.in_(workspace_ids),
                            workspace_read_allowed(actor_id),
                        )
                    )
                ).all()
            )
            if permitted != set(workspace_ids):
                return False
            selected = {UUID(str(item)) for item in cast_list(turn.request.get("document_ids"))}
            if selected:
                available = set(
                    (
                        await session.scalars(
                            select(DocumentRecord.id)
                            .join(
                                WorkspaceRecord,
                                WorkspaceRecord.id == DocumentRecord.workspace_id,
                            )
                            .where(
                                DocumentRecord.id.in_(selected),
                                DocumentRecord.lifecycle == "active",
                                DocumentRecord.workspace_id.in_(workspace_ids),
                                workspace_read_allowed(actor_id),
                            )
                        )
                    ).all()
                )
                if available != selected:
                    return False
            for document_id, version_id, projection_id in identities:
                found = await session.scalar(
                    select(DocumentRecord.id)
                    .join(
                        WorkspaceRecord,
                        WorkspaceRecord.id == DocumentRecord.workspace_id,
                    )
                    .join(AssetVersionRecord, AssetVersionRecord.document_id == DocumentRecord.id)
                    .join(
                        RagProjectionRecord,
                        RagProjectionRecord.asset_version_id == AssetVersionRecord.id,
                    )
                    .where(
                        DocumentRecord.id == document_id,
                        DocumentRecord.lifecycle == "active",
                        AssetVersionRecord.id == version_id,
                        AssetVersionRecord.status == "ready",
                        RagProjectionRecord.id == projection_id,
                        RagProjectionRecord.status == "ready",
                        workspace_read_allowed(actor_id),
                    )
                )
                if found is None:
                    return False
                if external:
                    approved = await session.scalar(
                        select(EvidenceApprovalStateRecord.revision_id)
                        .join(
                            AssetVersionRecord,
                            AssetVersionRecord.id == EvidenceApprovalStateRecord.revision_id,
                        )
                        .where(
                            EvidenceApprovalStateRecord.revision_id == version_id,
                            EvidenceApprovalStateRecord.provider == "development_codex_exec",
                            EvidenceApprovalStateRecord.status == "approved",
                            EvidenceApprovalStateRecord.revoked_at.is_(None),
                            EvidenceApprovalStateRecord.content_sha256 == AssetVersionRecord.sha256,
                        )
                    )
                    if approved is None:
                        return False
            return True


def cast_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []
