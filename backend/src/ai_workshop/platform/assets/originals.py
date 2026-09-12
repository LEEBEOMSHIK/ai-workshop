from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePath
from typing import Literal, NoReturn, Protocol
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.infrastructure.document_formats.pdf_preview import (
    PdfInspection,
    PdfInvalidError,
    PdfPageError,
    PdfPreviewLimitError,
    PdfPreviewTimeoutError,
    PdfPreviewWorkerError,
    RenderedPdfPage,
)
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.storage import ObjectStore
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.platform.workspaces.permissions import workspace_read_allowed
from ai_workshop.platform.workspaces.repository import (
    workspace_is_active,
    workspace_personal_owner_matches,
)
from ai_workshop.shared.errors import AppError

OriginalKind = Literal["text", "markdown", "pdf", "unsupported"]
_TEXT_SUFFIXES = frozenset({".txt"})
_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
_PDF_SUFFIX = ".pdf"
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class OriginalResource:
    document_id: UUID
    workspace_id: UUID
    asset_version_id: UUID
    version: int
    name: str
    object_key: str
    sha256: str
    size: int
    media_type: str
    status: VersionStatus


@dataclass(frozen=True, slots=True)
class OriginalPreview:
    document_id: UUID
    asset_version_id: UUID
    version: int
    name: str
    kind: OriginalKind
    size: int
    text: str | None
    page_count: int | None


@dataclass(frozen=True, slots=True)
class OriginalDownload:
    content: bytes
    content_disposition: str


class OriginalRepository(Protocol):
    async def resolve(
        self,
        *,
        user_id: UUID,
        document_id: UUID,
        version_id: UUID,
    ) -> OriginalResource | None: ...


class PdfRenderer(Protocol):
    async def inspect(self, content: bytes) -> PdfInspection: ...
    async def render_page(self, content: bytes, page_number: int) -> RenderedPdfPage: ...


class SqlAlchemyOriginalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(
        self,
        *,
        user_id: UUID,
        document_id: UUID,
        version_id: UUID,
    ) -> OriginalResource | None:
        row = (
            await self.session.execute(
                select(
                    DocumentRecord.id.label("document_id"),
                    DocumentRecord.workspace_id,
                    DocumentRecord.name,
                    AssetVersionRecord.id.label("asset_version_id"),
                    AssetVersionRecord.number.label("version"),
                    AssetVersionRecord.object_key,
                    AssetVersionRecord.sha256,
                    AssetVersionRecord.size,
                    AssetVersionRecord.media_type,
                    AssetVersionRecord.status,
                )
                .select_from(DocumentRecord)
                .join(
                    AssetVersionRecord,
                    AssetVersionRecord.document_id == DocumentRecord.id,
                )
                .join(
                    WorkspaceRecord,
                    WorkspaceRecord.id == DocumentRecord.workspace_id,
                )
                .join(
                    WorkspaceMembershipRecord,
                    WorkspaceMembershipRecord.workspace_id == WorkspaceRecord.id,
                )
                .where(
                    DocumentRecord.id == document_id,
                    AssetVersionRecord.id == version_id,
                    WorkspaceMembershipRecord.user_id == user_id,
                    workspace_read_allowed(user_id),
                    workspace_is_active(),
                    workspace_personal_owner_matches(user_id),
                )
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return None
        return OriginalResource(
            document_id=row.document_id,
            workspace_id=row.workspace_id,
            asset_version_id=row.asset_version_id,
            version=row.version,
            name=row.name,
            object_key=row.object_key,
            sha256=row.sha256,
            size=row.size,
            media_type=row.media_type,
            status=VersionStatus(row.status),
        )


class OriginalService:
    def __init__(
        self,
        repository: OriginalRepository,
        object_store: ObjectStore,
        pdf_renderer: PdfRenderer,
        *,
        original_max_bytes: int,
        text_preview_max_bytes: int,
    ) -> None:
        if (
            original_max_bytes < 1
            or text_preview_max_bytes < 1
            or text_preview_max_bytes > original_max_bytes
        ):
            raise ValueError("Original preview limits are invalid.")
        self.repository = repository
        self.object_store = object_store
        self.pdf_renderer = pdf_renderer
        self.original_max_bytes = original_max_bytes
        self.text_preview_max_bytes = text_preview_max_bytes

    async def preview(
        self,
        *,
        user: User,
        document_id: UUID,
        version_id: UUID,
    ) -> OriginalPreview:
        resource = await self._authorize(user.id, document_id, version_id)
        content = await self._verified_bytes(resource)
        suffix = _stored_suffix(resource.object_key)
        kind = _kind_for_suffix(suffix)
        text: str | None = None
        page_count: int | None = None
        if kind in {"text", "markdown"}:
            if len(content) > self.text_preview_max_bytes:
                raise _limit_error()
            if _looks_like_pdf(content):
                raise _unsupported_error()
            try:
                text = content.decode("utf-8-sig", errors="strict")
            except UnicodeDecodeError as exc:
                raise AppError(
                    "unsupported_text_encoding",
                    "The original text is not valid UTF-8.",
                    422,
                ) from exc
        elif kind == "pdf":
            _require_pdf_signature(content)
            try:
                page_count = (await self.pdf_renderer.inspect(content)).page_count
            except _PDF_PREVIEW_ERRORS as exc:
                _raise_pdf_error(exc)
        await self._final_recheck(user.id, document_id, version_id, resource)
        return OriginalPreview(
            document_id=resource.document_id,
            asset_version_id=resource.asset_version_id,
            version=resource.version,
            name=resource.name,
            kind=kind,
            size=resource.size,
            text=text,
            page_count=page_count,
        )

    async def pdf_page(
        self,
        *,
        user: User,
        document_id: UUID,
        version_id: UUID,
        page_number: int,
    ) -> bytes:
        resource = await self._authorize(user.id, document_id, version_id)
        if _kind_for_suffix(_stored_suffix(resource.object_key)) != "pdf":
            raise _unsupported_error()
        content = await self._verified_bytes(resource)
        _require_pdf_signature(content)
        try:
            rendered = await self.pdf_renderer.render_page(content, page_number)
        except _PDF_PREVIEW_ERRORS as exc:
            _raise_pdf_error(exc)
        await self._final_recheck(user.id, document_id, version_id, resource)
        return rendered.content

    async def content(
        self,
        *,
        user: User,
        document_id: UUID,
        version_id: UUID,
    ) -> OriginalDownload:
        resource = await self._authorize(user.id, document_id, version_id)
        content = await self._verified_bytes(resource)
        final = await self._final_recheck(user.id, document_id, version_id, resource)
        filename = _safe_attachment_filename(
            final.name,
            suffix=_stored_suffix(resource.object_key),
        )
        return OriginalDownload(
            content=content,
            content_disposition=_content_disposition(filename),
        )

    async def _authorize(
        self,
        user_id: UUID,
        document_id: UUID,
        version_id: UUID,
    ) -> OriginalResource:
        resource = await self.repository.resolve(
            user_id=user_id,
            document_id=document_id,
            version_id=version_id,
        )
        if resource is None:
            raise _not_found()
        if resource.status is not VersionStatus.READY:
            raise AppError(
                "original_not_ready",
                "The requested original version is not ready.",
                409,
            )
        return resource

    async def _verified_bytes(self, resource: OriginalResource) -> bytes:
        if resource.size > self.original_max_bytes:
            raise _limit_error()
        if (
            resource.size < 0
            or not resource.object_key
            or _SHA256.fullmatch(resource.sha256) is None
        ):
            raise _integrity_error()
        content = bytearray()
        try:
            async for chunk in self.object_store.open(resource.object_key):
                if not isinstance(chunk, bytes):
                    raise _integrity_error()
                next_size = len(content) + len(chunk)
                if next_size > self.original_max_bytes:
                    raise _limit_error()
                if next_size > resource.size:
                    raise _integrity_error()
                content.extend(chunk)
        except AppError:
            raise
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise AppError(
                "original_store_unavailable",
                "The authorized original is temporarily unavailable.",
                503,
            ) from exc
        result = bytes(content)
        if len(result) != resource.size or sha256(result).hexdigest() != resource.sha256:
            raise _integrity_error()
        return result

    async def _final_recheck(
        self,
        user_id: UUID,
        document_id: UUID,
        version_id: UUID,
        original: OriginalResource,
    ) -> OriginalResource:
        current = await self._authorize(user_id, document_id, version_id)
        if (
            current.document_id != original.document_id
            or current.workspace_id != original.workspace_id
            or current.asset_version_id != original.asset_version_id
            or current.version != original.version
            or current.object_key != original.object_key
            or current.sha256 != original.sha256
            or current.size != original.size
        ):
            raise _integrity_error()
        return current


PdfPreviewErrorGroup = (
    PdfInvalidError
    | PdfPageError
    | PdfPreviewLimitError
    | PdfPreviewTimeoutError
    | PdfPreviewWorkerError
)
_PDF_PREVIEW_ERRORS = (
    PdfInvalidError,
    PdfPageError,
    PdfPreviewLimitError,
    PdfPreviewTimeoutError,
    PdfPreviewWorkerError,
)


def _kind_for_suffix(suffix: str) -> OriginalKind:
    if suffix in _TEXT_SUFFIXES:
        return "text"
    if suffix in _MARKDOWN_SUFFIXES:
        return "markdown"
    if suffix == _PDF_SUFFIX:
        return "pdf"
    return "unsupported"


def _stored_suffix(object_key: str) -> str:
    return PurePath(object_key).suffix.casefold()


def _looks_like_pdf(content: bytes) -> bool:
    return b"%PDF-" in content[:1024]


def _require_pdf_signature(content: bytes) -> None:
    if not _looks_like_pdf(content):
        raise AppError(
            "invalid_pdf",
            "The original is not a valid PDF.",
            422,
        )


def _safe_attachment_filename(name: str, *, suffix: str) -> str:
    cleaned = "".join(
        character if character >= " " and character not in {'"', "/", "\\"} else "_"
        for character in name
    ).strip(" .")
    if not cleaned:
        cleaned = "document"
    current_suffix = PurePath(cleaned).suffix.casefold()
    if suffix and current_suffix != suffix:
        stem = PurePath(cleaned).stem.strip(" .") or "document"
        cleaned = f"{stem}{suffix}"
    cleaned = cleaned[:240].strip(" .") or f"document{suffix}"
    return cleaned


def _content_disposition(filename: str) -> str:
    ascii_name = "".join(
        character if character.isascii() and (character.isalnum() or character in " ._-") else "_"
        for character in filename
    ).strip(" .")
    if not ascii_name:
        ascii_name = "document"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


def _raise_pdf_error(error: PdfPreviewErrorGroup) -> NoReturn:
    if isinstance(error, PdfPreviewLimitError):
        raise _limit_error() from error
    if isinstance(error, (PdfInvalidError, PdfPageError)):
        raise AppError(
            "invalid_pdf_preview",
            "The PDF preview request is invalid.",
            422,
        ) from error
    raise AppError(
        "pdf_preview_unavailable",
        "The PDF preview is temporarily unavailable.",
        503,
    ) from error


def _not_found() -> AppError:
    return AppError("not_found", "The requested resource was not found.", 404)


def _unsupported_error() -> AppError:
    return AppError(
        "unsupported_original_preview",
        "This original format cannot be previewed.",
        422,
    )


def _limit_error() -> AppError:
    return AppError(
        "original_preview_limit_exceeded",
        "The original exceeds the configured preview limits.",
        413,
    )


def _integrity_error() -> AppError:
    return AppError(
        "original_integrity_unavailable",
        "The original failed integrity validation.",
        503,
    )
