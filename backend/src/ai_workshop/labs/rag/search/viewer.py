import asyncio
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, NoReturn, Protocol
from uuid import UUID

import pymupdf

from ai_workshop.labs.rag.documents.domain import ParsedDocument
from ai_workshop.labs.rag.ingestion.serialization import deserialize_parsed_document
from ai_workshop.platform.assets.storage import ObjectStore
from ai_workshop.shared.errors import AppError

NORMALIZED_VIEWER_MEDIA_TYPES = frozenset(
    {"text/plain", "text/markdown", "text/x-markdown", "application/pdf"}
)


@dataclass(frozen=True, slots=True)
class ViewerResource:
    document_id: UUID
    asset_version_id: UUID
    asset_version_number: int
    workspace_id: UUID
    folder_id: UUID | None
    projection_id: UUID
    title: str
    media_type: str
    original_object_key: str
    original_size: int
    original_sha256: str
    parsed_object_key: str
    parsed_sha256: str


class ViewerResourceAccessRepositoryPort(Protocol):
    async def resolve(
        self,
        *,
        actor_id: UUID,
        asset_version_id: UUID,
        projection_id: UUID,
    ) -> ViewerResource | None: ...


@dataclass(frozen=True, slots=True)
class NormalizedTextResource:
    resource: ViewerResource
    document: ParsedDocument


class ViewerService:
    def __init__(
        self,
        repository: ViewerResourceAccessRepositoryPort,
        object_store: ObjectStore,
    ) -> None:
        self.repository = repository
        self.object_store = object_store

    async def normalized_text(
        self,
        *,
        actor_id: UUID,
        asset_version_id: UUID,
        projection_id: UUID,
    ) -> NormalizedTextResource:
        resource = await self._authorize(
            actor_id=actor_id,
            asset_version_id=asset_version_id,
            projection_id=projection_id,
        )
        if resource.media_type not in NORMALIZED_VIEWER_MEDIA_TYPES:
            self._raise_not_found()
        content = await self._read_object(resource.parsed_object_key)
        if sha256(content).hexdigest() != resource.parsed_sha256:
            self._raise_invalid_artifact()
        try:
            document = deserialize_parsed_document(content)
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError(
                "source_artifact_invalid",
                "The normalized source artifact failed integrity validation.",
                503,
            ) from exc
        if document.asset_version_id != resource.asset_version_id:
            self._raise_invalid_artifact()
        return NormalizedTextResource(resource, document)

    async def pdf_page(
        self,
        *,
        actor_id: UUID,
        asset_version_id: UUID,
        projection_id: UUID,
        page_number: int,
    ) -> bytes:
        resource = await self._authorize(
            actor_id=actor_id,
            asset_version_id=asset_version_id,
            projection_id=projection_id,
        )
        if resource.media_type != "application/pdf" or page_number < 1:
            self._raise_not_found()
        content = await self._read_object(resource.original_object_key)
        if (
            len(content) != resource.original_size
            or sha256(content).hexdigest() != resource.original_sha256
        ):
            self._raise_invalid_artifact()
        return await asyncio.to_thread(_render_pdf_page, content, page_number)

    async def _authorize(
        self,
        *,
        actor_id: UUID,
        asset_version_id: UUID,
        projection_id: UUID,
    ) -> ViewerResource:
        resource = await self.repository.resolve(
            actor_id=actor_id,
            asset_version_id=asset_version_id,
            projection_id=projection_id,
        )
        if resource is None:
            self._raise_not_found()
        return resource

    async def _read_object(self, key: str) -> bytes:
        chunks: list[bytes] = []
        try:
            async for chunk in self.object_store.open(key):
                chunks.append(chunk)
        except (FileNotFoundError, OSError) as exc:
            raise AppError(
                "source_store_unavailable",
                "The authorized source object is temporarily unavailable.",
                503,
            ) from exc
        return b"".join(chunks)

    @staticmethod
    def _raise_not_found() -> NoReturn:
        raise AppError("not_found", "The requested resource was not found.", 404)

    @staticmethod
    def _raise_invalid_artifact() -> NoReturn:
        raise AppError(
            "source_artifact_invalid",
            "The source artifact failed integrity validation.",
            503,
        )


def _render_pdf_page(content: bytes, page_number: int) -> bytes:
    try:
        document: Any = pymupdf.open(stream=content, filetype="pdf")  # type: ignore[no-untyped-call]
    except (pymupdf.FileDataError, RuntimeError) as exc:
        raise AppError(
            "source_artifact_invalid",
            "The PDF source artifact could not be rendered.",
            503,
        ) from exc
    try:
        if page_number > document.page_count:
            raise AppError("not_found", "The requested resource was not found.", 404)
        page = document.load_page(page_number - 1)
        return bytes(page.get_pixmap(alpha=False).tobytes("png"))
    finally:
        document.close()
