"""Reserve ownership before receiving HTTP bytes and retain uncertain allocations."""

import logging
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from contextlib import aclosing, contextmanager
from pathlib import Path
from typing import Annotated, BinaryIO, Literal, Protocol
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ai_workshop.config import Settings, get_settings
from ai_workshop.infrastructure.document_formats.upload_multipart import parse_upload
from ai_workshop.infrastructure.object_store.intake import TrackedIntakeStore
from ai_workshop.platform.assets.intake_contracts import UploadIntakeClaim
from ai_workshop.platform.assets.intake_repository import UploadIntakeJournal
from ai_workshop.platform.assets.service import (
    AssetUploadCoordinator,
    AssetUploadResult,
    get_asset_upload_coordinator,
)
from ai_workshop.platform.assets.temporary_contracts import (
    TemporaryBinding,
    TemporaryOwnershipError,
)
from ai_workshop.platform.assets.temporary_service import TemporaryWorkspace
from ai_workshop.platform.assets.upload_contracts import UploadClaim, UploadOwnershipError
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError

_logger = logging.getLogger(__name__)


class IntakeStore(Protocol):
    @property
    def binding(self) -> TemporaryBinding: ...
    def create(self, claim: UploadIntakeClaim) -> TemporaryWorkspace: ...
    def observe(self, claim: UploadIntakeClaim) -> bool: ...


class UploadIntakeLease:
    def __init__(
        self,
        claim: UploadIntakeClaim,
        workspace: TemporaryWorkspace,
        journal: UploadIntakeJournal,
        store: IntakeStore,
    ) -> None:
        self.claim, self.workspace = claim, workspace
        self.journal, self.store = journal, store
        self._uncertain = False
        self._finished = False

    def mark_uncertain(self) -> None:
        self._uncertain = True

    async def reserve_original(self, original: UploadClaim) -> None:
        try:
            self.claim = await self.journal.reserve_original(self.claim, original)
        except (AppError, UploadOwnershipError):
            raise
        except BaseException:
            self.mark_uncertain()
            raise

    async def prepare_attachment(self, session: AsyncSession, original: UploadClaim) -> None:
        await self.journal.prepare_attachment(session, self.claim, original)

    async def attach(self, session: AsyncSession, original: UploadClaim) -> UploadIntakeClaim:
        return await self.journal.attach(session, self.claim, original)

    def acknowledge(self, claim: UploadIntakeClaim) -> None:
        self.claim = claim

    async def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        try:
            if self._uncertain:
                return
            self.claim = await self.journal.transition(self.claim, expected_state="open")
            self.claim = await self.journal.transition(self.claim, expected_state="closed")
            self.workspace.discard()
            if self.store.observe(self.claim):
                raise TemporaryOwnershipError("cleanup_unconfirmed")
            self.claim = await self.journal.transition(self.claim, expected_state="cleaning")
        except BaseException:
            _logger.warning("http_intake_cleanup_incomplete")
        finally:
            try:
                self.workspace.close()
            except BaseException:
                _logger.warning("http_intake_cleanup_incomplete")


@contextmanager
def _payload_file(
    path: Path, mode: Literal["wb", "rb"], lease: UploadIntakeLease
) -> Iterator[BinaryIO]:
    handle = path.open(mode)
    try:
        yield handle
    finally:
        try:
            handle.close()
        except BaseException:
            lease.mark_uncertain()
            raise


class IntakeCoordinator(Protocol):
    async def upload_intake(
        self,
        *,
        user: User,
        intake: UploadIntakeLease,
        filename: str,
        media_type: str,
        folder_id: UUID | None,
        content: AsyncIterator[bytes],
    ) -> AssetUploadResult: ...


class HttpUploadIntakeService:
    def __init__(
        self, journal: UploadIntakeJournal, store: IntakeStore, coordinator: IntakeCoordinator
    ) -> None:
        self.journal, self.store, self.coordinator = journal, store, coordinator

    async def upload(
        self,
        *,
        user: User,
        stream: AsyncIterator[bytes],
        content_type: str,
        workspace_id: UUID | None = None,
        document_id: UUID | None = None,
    ) -> AssetUploadResult:
        lease = None
        try:
            claim = await self.journal.reserve(
                user_id=user.id,
                workspace_id=workspace_id,
                document_id=document_id,
                binding=self.store.binding,
            )
            workspace = self.store.create(claim)
            lease = UploadIntakeLease(claim, workspace, self.journal, self.store)
            path = workspace.create_file("payload.bin")
            with _payload_file(path, "wb", lease) as destination:
                parsed = await parse_upload(
                    stream, content_type, destination, allow_folder=claim.new_document
                )

            async def content() -> AsyncGenerator[bytes]:
                with _payload_file(path, "rb", lease) as source:
                    while chunk := source.read(64 * 1024):
                        yield chunk

            async with aclosing(content()) as reader:
                return await self.coordinator.upload_intake(
                    user=user,
                    intake=lease,
                    filename=parsed.filename,
                    media_type=parsed.media_type,
                    folder_id=parsed.folder_id,
                    content=reader,
                )
        except AppError:
            raise
        except UploadOwnershipError as error:
            if error.code == "source_unavailable":
                raise AppError("not_found", "The requested resource was not found.", 404) from None
            if error.code == "generation_mismatch":
                raise AppError(
                    "upload_conflict", "The document changed during upload.", 409
                ) from None
            raise AppError(
                "http_intake_unavailable", "The upload could not be safely completed.", 503
            ) from None
        except Exception:
            raise AppError(
                "http_intake_unavailable", "The upload could not be safely completed.", 503
            ) from None
        finally:
            if lease is not None:
                await lease.finish()


def get_upload_intake_service(
    coordinator: Annotated[AssetUploadCoordinator, Depends(get_asset_upload_coordinator)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HttpUploadIntakeService:
    from ai_workshop.platform.assets.tracked_uploads import TrackedAssetUploadCoordinator

    if (
        not isinstance(coordinator, TrackedAssetUploadCoordinator)
        or not isinstance(session.bind, AsyncEngine)
        or settings.temporary_store_root is None
        or settings.temporary_store_id is None
        or settings.temporary_store_binding_id is None
    ):
        raise AppError("http_intake_unavailable", "Upload temporary storage is not ready.", 503)
    return HttpUploadIntakeService(
        UploadIntakeJournal(async_sessionmaker(session.bind, expire_on_commit=False)),
        TrackedIntakeStore(
            settings.temporary_store_root,
            TemporaryBinding(settings.temporary_store_id, settings.temporary_store_binding_id),
        ),
        coordinator,
    )
