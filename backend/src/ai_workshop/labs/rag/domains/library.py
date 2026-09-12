from __future__ import annotations

from typing import Protocol
from uuid import UUID

from ai_workshop.labs.rag.domains.service import DomainLibraryContext
from ai_workshop.platform.assets.domain import Document
from ai_workshop.platform.assets.library import LibraryPage
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.errors import AppError


class DomainLibraryResolver(Protocol):
    async def resolve_library(
        self,
        *,
        slug: str,
        actor_id: UUID,
    ) -> DomainLibraryContext: ...


class PlatformLibraryPort(Protocol):
    async def browse(
        self,
        *,
        user: User,
        workspace_id: UUID,
        folder_id: UUID | None,
        folder_cursor: str | None,
        document_cursor: str | None,
        limit: int | None,
    ) -> LibraryPage: ...

    async def document(
        self,
        *,
        user: User,
        workspace_id: UUID,
        document_id: UUID,
    ) -> Document: ...


class DomainLibraryService:
    def __init__(
        self,
        domains: DomainLibraryResolver,
        library: PlatformLibraryPort,
        *,
        selection_limit: int,
    ) -> None:
        if selection_limit < 1:
            raise ValueError("The document selection limit must be positive.")
        self.domains = domains
        self.library = library
        self.selection_limit = selection_limit

    async def resolve(self, *, slug: str, actor_id: UUID) -> DomainLibraryContext:
        return await self.domains.resolve_library(slug=slug, actor_id=actor_id)

    async def browse(
        self,
        *,
        slug: str,
        user: User,
        workspace_id: UUID,
        folder_id: UUID | None,
        folder_cursor: str | None,
        document_cursor: str | None,
        limit: int | None,
    ) -> LibraryPage:
        await self._authorize_workspace(
            slug=slug,
            actor_id=user.id,
            workspace_id=workspace_id,
        )
        return await self.library.browse(
            user=user,
            workspace_id=workspace_id,
            folder_id=folder_id,
            folder_cursor=folder_cursor,
            document_cursor=document_cursor,
            limit=limit,
        )

    async def document(
        self,
        *,
        slug: str,
        user: User,
        workspace_id: UUID,
        document_id: UUID,
    ) -> Document:
        await self._authorize_workspace(
            slug=slug,
            actor_id=user.id,
            workspace_id=workspace_id,
        )
        return await self.library.document(
            user=user,
            workspace_id=workspace_id,
            document_id=document_id,
        )

    async def _authorize_workspace(
        self,
        *,
        slug: str,
        actor_id: UUID,
        workspace_id: UUID,
    ) -> None:
        context = await self.domains.resolve_library(slug=slug, actor_id=actor_id)
        if workspace_id not in context.allowed_workspace_ids:
            raise AppError("not_found", "The requested resource was not found.", 404)
