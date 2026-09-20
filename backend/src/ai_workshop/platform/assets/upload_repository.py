"""Independent reservation commits and request-transaction source attachment."""

from collections.abc import Callable
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.platform.assets.domain import Document
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord, FolderRecord
from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.storage import StoredObject
from ai_workshop.platform.assets.upload_contracts import (
    OriginalFileObservation,
    OriginalStoreBinding,
    UploadAttempt,
    UploadClaim,
    UploadOwnershipError,
    validate_stored,
)
from ai_workshop.platform.assets.upload_models import OriginalResourceRecord, UploadAttemptRecord
from ai_workshop.platform.workspaces.permissions import require_workspace_write


def claim_from_record(record: UploadAttemptRecord) -> UploadClaim:
    claim = UploadClaim(
        record.id,
        SourceIdentity(record.workspace_id, record.document_id, record.asset_version_id),
        record.user_id,
        record.folder_id,
        record.new_document,
        OriginalStoreBinding(record.store_id, record.binding_id),
        record.suffix,
        record.generation,
    )
    if claim.canonical_key != record.canonical_key or claim.temporary_key != record.temporary_key:
        raise UploadOwnershipError("identity_mismatch")
    UploadAttempt(claim, record.state, record.revision, record.size, record.sha256)
    return claim


class UploadJournal:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _source(
        self, session: AsyncSession, claim: UploadClaim, *, reserving: bool = False
    ) -> Document | None:
        await require_workspace_write(session, claim.user_id, claim.source.workspace_id, lock=True)
        if claim.new_document:
            if claim.folder_id is not None:
                folder = await session.scalar(
                    select(FolderRecord)
                    .where(FolderRecord.id == claim.folder_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if (
                    folder is None
                    or folder.workspace_id != claim.source.workspace_id
                    or folder.lifecycle != "active"
                ):
                    raise UploadOwnershipError("source_unavailable")
            if await session.get(DocumentRecord, claim.source.document_id) is not None:
                raise UploadOwnershipError("identity_mismatch")
            return None
        record = await session.scalar(
            select(DocumentRecord)
            .where(DocumentRecord.id == claim.source.document_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            record is None
            or record.workspace_id != claim.source.workspace_id
            or record.lifecycle != "active"
        ):
            raise UploadOwnershipError("source_unavailable")
        if (not reserving or claim.generation is not None) and (
            claim.generation != record.lifecycle_generation
        ):
            raise UploadOwnershipError("generation_mismatch")
        return await SqlAlchemyAssetRepository(session).find_document_for_user(
            claim.user_id, claim.source.document_id
        )

    async def reserve(self, claim: UploadClaim) -> UploadClaim:
        async with self.sessions.begin() as session:
            await self._source(session, claim, reserving=True)
            if not claim.new_document:
                generation = await session.scalar(
                    select(DocumentRecord.lifecycle_generation).where(
                        DocumentRecord.id == claim.source.document_id
                    )
                )
                claim = replace(claim, generation=generation)
            session.add(
                UploadAttemptRecord(
                    id=claim.attempt_id,
                    workspace_id=claim.source.workspace_id,
                    document_id=claim.source.document_id,
                    asset_version_id=claim.source.asset_version_id,
                    user_id=claim.user_id,
                    folder_id=claim.folder_id,
                    new_document=claim.new_document,
                    store_id=claim.binding.store_id,
                    binding_id=claim.binding.binding_id,
                    suffix=claim.suffix,
                    generation=claim.generation,
                    canonical_key=claim.canonical_key,
                    temporary_key=claim.temporary_key,
                    state="open",
                    revision=1,
                    size=None,
                    sha256=None,
                )
            )
            await session.flush()
        return claim

    async def _attempt(
        self, session: AsyncSession, claim: UploadClaim, state: str, revision: int
    ) -> UploadAttemptRecord:
        record = await session.scalar(
            select(UploadAttemptRecord)
            .where(UploadAttemptRecord.id == claim.attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if record is None or claim_from_record(record) != claim:
            raise UploadOwnershipError("identity_mismatch")
        if record.state != state or record.revision != revision:
            raise UploadOwnershipError("invalid_state")
        return record

    async def published(self, claim: UploadClaim, stored: StoredObject) -> None:
        validate_stored(claim, stored)
        async with self.sessions.begin() as session:
            record = await self._attempt(session, claim, "open", 1)
            record.state, record.revision = "published", 2
            record.size, record.sha256 = stored.size, stored.sha256

    async def abandoned(self, claim: UploadClaim, *, expected_state: str) -> None:
        if expected_state != "open":
            raise UploadOwnershipError("invalid_state")
        async with self.sessions.begin() as session:
            record = await self._attempt(session, claim, "open", 1)
            record.state, record.revision = "abandoned", 2

    async def cleanup(
        self,
        claim: UploadClaim,
        *,
        expected_state: str,
        discard: Callable[[], None],
        observe: Callable[[], OriginalFileObservation],
    ) -> None:
        if expected_state not in {"open", "published"}:
            raise UploadOwnershipError("invalid_state")
        if expected_state == "published":
            # Commit the durable attachment fence before invoking any physical callback.
            # A lost commit response cannot authorize deletion or another attachment.
            async with self.sessions.begin() as session:
                record = await self._attempt(session, claim, "published", 2)
                if await session.get(OriginalResourceRecord, claim.attempt_id) is not None:
                    raise UploadOwnershipError("attachment_mismatch")
                record.state, record.revision = "discarding", 3
            state, revision, terminal_revision = "discarding", 3, 4
        else:
            state, revision, terminal_revision = "open", 1, 2
        async with self.sessions.begin() as session:
            record = await self._attempt(session, claim, state, revision)
            if await session.get(OriginalResourceRecord, claim.attempt_id) is not None:
                raise UploadOwnershipError("attachment_mismatch")
            discard()
            observed = observe()
            if observed.canonical is not None or observed.temporary_exists:
                raise UploadOwnershipError("ownership_unconfirmed")
            record.state, record.revision = "abandoned", terminal_revision

    async def prepare_attachment(
        self, session: AsyncSession, claim: UploadClaim
    ) -> Document | None:
        document = await self._source(session, claim)
        await self._attempt(session, claim, "published", 2)
        session.info["original_upload_attachment"] = (
            claim,
            session.sync_session.get_transaction(),
            session.sync_session.get_nested_transaction(),
        )
        return document

    async def attach(self, session: AsyncSession, claim: UploadClaim, stored: StoredObject) -> None:
        validate_stored(claim, stored)
        capability = session.info.pop("original_upload_attachment", None)
        current = session.sync_session.get_transaction()
        if current is None or capability != (
            claim,
            current,
            session.sync_session.get_nested_transaction(),
        ):
            raise UploadOwnershipError("attachment_mismatch")
        record = await self._attempt(session, claim, "published", 2)
        version = await session.scalar(
            select(AssetVersionRecord)
            .where(AssetVersionRecord.id == claim.source.asset_version_id)
            .execution_options(populate_existing=True)
        )
        document = await session.scalar(
            select(DocumentRecord)
            .where(DocumentRecord.id == claim.source.document_id)
            .execution_options(populate_existing=True)
        )
        if (
            version is None
            or document is None
            or document.workspace_id != claim.source.workspace_id
            or document.lifecycle != "active"
            or (not claim.new_document and document.lifecycle_generation != claim.generation)
            or version.document_id != claim.source.document_id
            or (version.object_key, version.size, version.sha256)
            != (stored.key, stored.size, stored.sha256)
            or (record.size, record.sha256) != (stored.size, stored.sha256)
        ):
            raise UploadOwnershipError("attachment_mismatch")
        session.add(
            OriginalResourceRecord(
                id=claim.attempt_id,
                workspace_id=claim.source.workspace_id,
                document_id=claim.source.document_id,
                asset_version_id=claim.source.asset_version_id,
                revision=1,
            )
        )
        session.add(
            AssetSourceRelationRecord(
                workspace_id=claim.source.workspace_id,
                document_id=claim.source.document_id,
                asset_version_id=claim.source.asset_version_id,
                participant="platform_originals",
                kind="original",
                resource_id=claim.attempt_id,
                resource_revision=1,
                relation_kind="source_copy",
            )
        )
        record.state, record.revision = "attached", 3
        await session.flush()
