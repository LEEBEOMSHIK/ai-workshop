"""Block new RAG writers and inspect durable evidence of outstanding writers.

This is not a proof of external administrator or pre-deployment writer termination.
All supported admissions serialize on Document and alias writers on Profile.
"""

from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord, RagProjectionRecord
from ai_workshop.labs.rag.indexing.alias_models import AliasOperationRecord
from ai_workshop.labs.rag.indexing.fence_models import RagIndexWriteFenceRecord
from ai_workshop.labs.rag.indexing.resource_models import (
    RagIndexAttemptRecord,
    RagIndexResourceRecord,
)
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexTrackingError
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord


async def _lock_document_scopes(
    session: AsyncSession, workspace_id: UUID, document_id: UUID, generation: int
) -> set[tuple[UUID, UUID]]:
    document = await session.scalar(
        select(DocumentRecord)
        .where(DocumentRecord.id == document_id, DocumentRecord.workspace_id == workspace_id)
        .with_for_update()
    )
    if document is None:
        raise IndexTrackingError("rag_index_inventory_incomplete")
    if type(generation) is not int or generation < 1 or document.lifecycle_generation != generation:
        raise IndexTrackingError("rag_index_inventory_changed")
    scopes = set(
        (
            await session.execute(
                select(
                    RagProjectionRecord.indexing_profile_id,
                    RagProjectionRecord.document_processing_profile_id,
                )
                .join(
                    AssetVersionRecord,
                    AssetVersionRecord.id == RagProjectionRecord.asset_version_id,
                )
                .where(AssetVersionRecord.document_id == document_id)
            )
        )
        .tuples()
        .all()
    )
    profile_ids = {scope[0] for scope in scopes}
    if profile_ids:
        locked = tuple(
            (
                await session.scalars(
                    select(ProfileRecord.id)
                    .where(ProfileRecord.id.in_(profile_ids))
                    .order_by(ProfileRecord.id)
                    .with_for_update()
                )
            ).all()
        )
        if set(locked) != profile_ids:
            raise IndexTrackingError("rag_index_inventory_incomplete")
    return scopes


async def block_index_writes(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    document_id: UUID,
    generation: int,
) -> None:
    """Persist a fence after prior profile critical sections have finished."""
    async with sessions.begin() as session:
        await _lock_document_scopes(session, workspace_id, document_id, generation)
        fence = await session.get(RagIndexWriteFenceRecord, document_id)
        if fence is not None:
            if fence.workspace_id != workspace_id or fence.generation != generation:
                raise IndexTrackingError("rag_index_inventory_changed")
            return
        session.add(
            RagIndexWriteFenceRecord(
                document_id=document_id, workspace_id=workspace_id, generation=generation
            )
        )


async def inspect_index_writers(
    sessions: async_sessionmaker[AsyncSession],
    workspace_id: UUID,
    document_id: UUID,
    generation: int,
) -> bool:
    """Return whether this exact fence has no known or untracked RAG writers.

    All source versions and build states participate. Binding changes cannot hide
    open alias operations in a relevant profile/processing scope. No body is read.
    """
    async with sessions.begin() as session:
        try:
            scopes = await _lock_document_scopes(session, workspace_id, document_id, generation)
        except IndexTrackingError:
            return False
        fence = await session.get(RagIndexWriteFenceRecord, document_id)
        if fence is None or fence.workspace_id != workspace_id or fence.generation != generation:
            return False
        builds = tuple(
            (
                await session.scalars(
                    select(RagIndexBuildRecord.id)
                    .join(
                        RagProjectionRecord,
                        RagProjectionRecord.id == RagIndexBuildRecord.projection_id,
                    )
                    .join(
                        AssetVersionRecord,
                        AssetVersionRecord.id == RagProjectionRecord.asset_version_id,
                    )
                    .where(AssetVersionRecord.document_id == document_id)
                )
            ).all()
        )
        if builds:
            tracked = set(
                (
                    await session.scalars(
                        select(RagIndexResourceRecord.build_id).where(
                            RagIndexResourceRecord.build_id.in_(builds),
                            RagIndexResourceRecord.workspace_id == workspace_id,
                            RagIndexResourceRecord.document_id == document_id,
                        )
                    )
                ).all()
            )
            if tracked != set(builds):
                return False
            if (
                await session.scalar(
                    select(RagIndexAttemptRecord.id)
                    .where(
                        RagIndexAttemptRecord.build_id.in_(builds),
                        RagIndexAttemptRecord.state == "open",
                    )
                    .limit(1)
                )
                is not None
            ):
                return False
        return not (
            scopes
            and await session.scalar(
                select(AliasOperationRecord.id)
                .where(
                    tuple_(
                        AliasOperationRecord.indexing_profile_id,
                        AliasOperationRecord.document_processing_profile_id,
                    ).in_(scopes),
                    AliasOperationRecord.state == "open",
                )
                .limit(1)
            )
            is not None
        )
