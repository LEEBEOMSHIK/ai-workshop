"""Coordinate durable original ownership before consuming upload bytes."""

import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.assets.domain import Document
from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.service import (
    AssetService,
    AssetUploadCoordinator,
    AssetUploadResult,
)
from ai_workshop.platform.assets.storage import StoredObject
from ai_workshop.platform.assets.upload_contracts import (
    ALLOWED_ORIGINAL_SUFFIXES,
    OriginalFileObservation,
    OriginalStoreBinding,
    UploadClaim,
    UploadOwnershipError,
    validate_stored,
)
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.jobs.service import JobService
from ai_workshop.shared.errors import AppError

_logger = logging.getLogger(__name__)


class UploadJournalPort(Protocol):
    async def reserve(self, claim: UploadClaim) -> UploadClaim: ...
    async def published(self, claim: UploadClaim, stored: StoredObject) -> None: ...
    async def cleanup(
        self,
        claim: UploadClaim,
        *,
        expected_state: str,
        discard: Callable[[], None],
        observe: Callable[[], OriginalFileObservation],
    ) -> None: ...
    async def prepare_attachment(
        self, session: AsyncSession, claim: UploadClaim
    ) -> Document | None: ...
    async def attach(
        self, session: AsyncSession, claim: UploadClaim, stored: StoredObject
    ) -> None: ...


class OriginalStorePort(Protocol):
    binding: OriginalStoreBinding

    async def publish(self, claim: UploadClaim, source: AsyncIterator[bytes]) -> StoredObject: ...
    def observe(self, claim: UploadClaim) -> OriginalFileObservation: ...
    def discard(self, claim: UploadClaim, expected: StoredObject) -> None: ...


class TrackedAssetUploadCoordinator(AssetUploadCoordinator):
    def __init__(
        self,
        assets: AssetService,
        jobs: JobService,
        *,
        session: AsyncSession,
        journal: UploadJournalPort,
        store: OriginalStorePort,
    ) -> None:
        super().__init__(assets, jobs, commit=session.commit)
        self.session = session
        self.journal = journal
        self.store = store

    async def upload(
        self,
        *,
        user: User,
        workspace_id: UUID,
        folder_id: UUID | None,
        filename: str,
        media_type: str,
        content: AsyncIterator[bytes],
    ) -> AssetUploadResult:
        await self.assets.repository.require_workspace_write(user.id, workspace_id)
        document = Document.create(workspace_id=workspace_id, folder_id=folder_id, name=filename)
        try:
            return await self._upload(
                user, document, filename, media_type, content, new_document=True
            )
        except UploadOwnershipError as error:
            raise _public_error(error) from None

    async def upload_version(
        self,
        *,
        user: User,
        document_id: UUID,
        filename: str,
        media_type: str,
        content: AsyncIterator[bytes],
    ) -> AssetUploadResult:
        document = await self.assets.repository.find_document_for_user(user.id, document_id)
        if document is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        await self.assets.repository.require_workspace_write(user.id, document.workspace_id)
        try:
            return await self._upload(
                user, document, filename, media_type, content, new_document=False
            )
        except UploadOwnershipError as error:
            raise _public_error(error) from None

    async def _upload(
        self,
        user: User,
        document: Document,
        filename: str,
        media_type: str,
        content: AsyncIterator[bytes],
        *,
        new_document: bool,
    ) -> AssetUploadResult:
        suffix = Path(filename).suffix.casefold()
        if suffix not in ALLOWED_ORIGINAL_SUFFIXES:
            raise AppError("unsupported_document", "This document format is not supported.", 422)
        claim = await self.journal.reserve(
            UploadClaim(
                attempt_id=uuid4(),
                source=SourceIdentity(document.workspace_id, document.id, uuid4()),
                user_id=user.id,
                folder_id=document.folder_id,
                new_document=new_document,
                binding=self.store.binding,
                suffix=suffix,
            )
        )

        async def bounded_content() -> AsyncIterator[bytes]:
            size = 0
            async for chunk in content:
                size += len(chunk)
                if size > self.assets.max_upload_bytes:
                    raise AppError("file_too_large", "The document exceeds the upload limit.", 413)
                yield chunk

        try:
            stored = await self.store.publish(claim, bounded_content())
        except BaseException:
            # publish has unwound its own writer. Only exact absence permits closure.
            await self._abandon_if_absent(claim, expected_state="open")
            raise
        validate_stored(claim, stored)
        # A failed/uncertain journal commit leaves the canonical file and reservation intact.
        await self.journal.published(claim, stored)
        try:
            current = await self.journal.prepare_attachment(self.session, claim)
            if (current is None) != new_document:
                raise UploadOwnershipError("attachment_mismatch")
            if current is not None:
                document = current
            if await self.assets.repository.workspace_contains_sha256(
                document.workspace_id, stored.sha256
            ):
                raise AppError(
                    "duplicate_document_content",
                    "A document with the same content already exists in this workspace.",
                    409,
                )
            version = document.new_version(
                object_key=stored.key,
                sha256=stored.sha256,
                media_type=media_type or "application/octet-stream",
                size=stored.size,
                version_id=claim.source.asset_version_id,
            )
            if new_document:
                document = await self.assets.repository.save(document)
            else:
                document = await self.assets.repository.save_version(document, version)
            creation = await self.jobs.create_asset_verification(
                user_id=user.id,
                workspace_id=document.workspace_id,
                asset_version_id=version.id,
            )
            await self.journal.attach(self.session, claim, stored)
        except BaseException:
            await self._rollback_and_discard(claim, stored)
            raise
        # Never include this in the cleanup block: an exception may follow a durable commit.
        await self.session.commit()
        return AssetUploadResult(document, creation.job, creation.created)

    async def _rollback_and_discard(self, claim: UploadClaim, stored: StoredObject) -> None:
        try:
            await self.session.rollback()
            await self.journal.cleanup(
                claim,
                expected_state="published",
                discard=lambda: self.store.discard(claim, stored),
                observe=lambda: self.store.observe(claim),
            )
        except BaseException:
            # Keep the durable locator; do not hide the original failure or log private paths.
            _logger.warning("original_upload_cleanup_incomplete")

    async def _abandon_if_absent(self, claim: UploadClaim, *, expected_state: str) -> None:
        try:
            await self.journal.cleanup(
                claim,
                expected_state=expected_state,
                discard=lambda: None,
                observe=lambda: self.store.observe(claim),
            )
        except BaseException:
            _logger.warning("original_upload_cleanup_incomplete")


def _public_error(error: UploadOwnershipError) -> AppError:
    if error.code == "source_unavailable":
        return AppError("not_found", "The requested resource was not found.", 404)
    if error.code == "generation_mismatch":
        return AppError("original_upload_conflict", "The document changed during upload.", 409)
    return AppError("original_upload_unavailable", "The upload could not be safely completed.", 503)
