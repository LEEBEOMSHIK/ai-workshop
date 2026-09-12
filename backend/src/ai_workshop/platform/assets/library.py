from __future__ import annotations

import base64
import binascii
import hmac
import json
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.platform.assets.domain import AssetVersion, Document, Folder
from ai_workshop.platform.assets.library_repository import (
    LibraryRepository,
    NameCursor,
    SqlAlchemyLibraryRepository,
    VersionCursor,
)
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.workspaces.domain import Workspace
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError


@dataclass(frozen=True, slots=True)
class LibraryFolder:
    folder: Folder
    has_children: bool


@dataclass(frozen=True, slots=True)
class LibraryPage:
    workspace: Workspace
    folder: Folder | None
    ancestors: tuple[Folder, ...]
    folders: tuple[LibraryFolder, ...]
    documents: tuple[Document, ...]
    next_folder_cursor: str | None
    next_document_cursor: str | None


@dataclass(frozen=True, slots=True)
class AssetVersionPage:
    items: tuple[AssetVersion, ...]
    next_cursor: str | None


class LibraryService:
    def __init__(
        self,
        repository: LibraryRepository,
        *,
        secret_key: str,
        default_page_size: int,
        max_page_size: int,
        max_depth: int,
        cursor_max_chars: int,
    ) -> None:
        self.repository = repository
        self.default_page_size = default_page_size
        self.max_page_size = max_page_size
        self.max_depth = max_depth
        self.cursor_max_chars = cursor_max_chars
        if (
            not secret_key
            or not 1 <= default_page_size <= max_page_size
            or max_depth < 1
            or cursor_max_chars < 1
        ):
            raise ValueError("Library service limits are invalid.")
        self._cursor_key = hmac.digest(
            secret_key.encode("utf-8"),
            b"ai-workshop:asset-library-cursor:v1",
            "sha256",
        )

    async def browse(
        self,
        *,
        user: User,
        workspace_id: UUID,
        folder_id: UUID | None,
        folder_cursor: str | None,
        document_cursor: str | None,
        limit: int | None,
    ) -> LibraryPage:
        workspace = await self._workspace(user, workspace_id)
        page_limit = self._page_limit(limit)
        folder = None
        ancestors: tuple[Folder, ...] = ()
        if folder_id is not None:
            folder = await self.repository.folder_for_workspace(workspace_id, folder_id)
            if folder is None:
                raise _not_found()
            ancestors = await self._ancestors(workspace_id, folder)

        folder_position = self._decode_name_cursor(
            folder_cursor,
            user_id=user.id,
            workspace_id=workspace_id,
            folder_id=folder_id,
            kind="folder",
        )
        document_position = self._decode_name_cursor(
            document_cursor,
            user_id=user.id,
            workspace_id=workspace_id,
            folder_id=folder_id,
            kind="document",
        )
        folder_rows = await self.repository.child_folders(
            workspace_id,
            folder_id,
            folder_position,
            page_limit + 1,
        )
        document_rows = await self.repository.child_documents(
            workspace_id,
            folder_id,
            document_position,
            page_limit + 1,
        )
        visible_folders = folder_rows[:page_limit]
        visible_documents = document_rows[:page_limit]
        next_folder_cursor = None
        if len(folder_rows) > page_limit and visible_folders:
            last_folder = visible_folders[-1][0]
            next_folder_cursor = self._encode_cursor(
                user_id=user.id,
                workspace_id=workspace_id,
                folder_id=folder_id,
                document_id=None,
                kind="folder",
                position={"name": last_folder.name, "id": str(last_folder.id)},
            )
        next_document_cursor = None
        if len(document_rows) > page_limit and visible_documents:
            last_document = visible_documents[-1]
            next_document_cursor = self._encode_cursor(
                user_id=user.id,
                workspace_id=workspace_id,
                folder_id=folder_id,
                document_id=None,
                kind="document",
                position={"name": last_document.name, "id": str(last_document.id)},
            )
        return LibraryPage(
            workspace=workspace,
            folder=folder,
            ancestors=ancestors,
            folders=tuple(
                LibraryFolder(item, has_children)
                for item, has_children in visible_folders
            ),
            documents=tuple(visible_documents),
            next_folder_cursor=next_folder_cursor,
            next_document_cursor=next_document_cursor,
        )

    async def document(
        self,
        *,
        user: User,
        workspace_id: UUID,
        document_id: UUID,
    ) -> Document:
        await self._workspace(user, workspace_id)
        document = await self.repository.document_for_workspace(workspace_id, document_id)
        if document is None:
            raise _not_found()
        return document

    async def versions(
        self,
        *,
        user: User,
        workspace_id: UUID,
        document_id: UUID,
        cursor: str | None,
        limit: int | None,
    ) -> AssetVersionPage:
        await self._workspace(user, workspace_id)
        document = await self.repository.document_for_workspace(workspace_id, document_id)
        if document is None:
            raise _not_found()
        page_limit = self._page_limit(limit)
        position = self._decode_version_cursor(
            cursor,
            user_id=user.id,
            workspace_id=workspace_id,
            document_id=document_id,
        )
        rows = await self.repository.document_versions(
            document_id,
            position,
            page_limit + 1,
        )
        visible = rows[:page_limit]
        next_cursor = None
        if len(rows) > page_limit and visible:
            last = visible[-1]
            next_cursor = self._encode_cursor(
                user_id=user.id,
                workspace_id=workspace_id,
                folder_id=None,
                document_id=document_id,
                kind="version",
                position={"number": last.number, "id": str(last.id)},
            )
        return AssetVersionPage(tuple(visible), next_cursor)

    async def _workspace(self, user: User, workspace_id: UUID) -> Workspace:
        workspace = await self.repository.workspace_for_user(user.id, workspace_id)
        if workspace is None:
            raise _not_found()
        return workspace

    async def _ancestors(self, workspace_id: UUID, folder: Folder) -> tuple[Folder, ...]:
        reverse_ancestors: list[Folder] = []
        seen = {folder.id}
        parent_id = folder.parent_id
        while parent_id is not None:
            if len(reverse_ancestors) + 1 >= self.max_depth:
                raise _unsafe_hierarchy()
            parent = await self.repository.folder_for_workspace(workspace_id, parent_id)
            if parent is None or parent.id in seen:
                raise _unsafe_hierarchy()
            seen.add(parent.id)
            reverse_ancestors.append(parent)
            parent_id = parent.parent_id
        reverse_ancestors.reverse()
        return tuple(reverse_ancestors)

    def _page_limit(self, requested: int | None) -> int:
        value = self.default_page_size if requested is None else requested
        if not 1 <= value <= self.max_page_size:
            raise _invalid_request()
        return value

    def _encode_cursor(
        self,
        *,
        user_id: UUID,
        workspace_id: UUID,
        folder_id: UUID | None,
        document_id: UUID | None,
        kind: str,
        position: dict[str, object],
    ) -> str:
        payload = json.dumps(
            {
                "version": 1,
                "actor": str(user_id),
                "scope": {
                    "kind": kind,
                    "workspace": str(workspace_id),
                    "folder": str(folder_id) if folder_id is not None else None,
                    "document": str(document_id) if document_id is not None else None,
                },
                "position": position,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        signature = hmac.digest(self._cursor_key, payload, "sha256")
        encoded = f"{_base64_encode(payload)}.{_base64_encode(signature)}"
        if len(encoded) > self.cursor_max_chars:
            raise _invalid_request()
        return encoded

    def _decode_name_cursor(
        self,
        value: str | None,
        *,
        user_id: UUID,
        workspace_id: UUID,
        folder_id: UUID | None,
        kind: str,
    ) -> NameCursor | None:
        if value is None:
            return None
        position = self._decode_cursor(
            value,
            user_id=user_id,
            workspace_id=workspace_id,
            folder_id=folder_id,
            document_id=None,
            kind=kind,
        )
        if set(position) != {"name", "id"} or not isinstance(position["name"], str):
            raise _invalid_request()
        raw_id = position["id"]
        if not isinstance(raw_id, str):
            raise _invalid_request()
        try:
            identifier = UUID(raw_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise _invalid_request() from exc
        return NameCursor(name=position["name"], id=identifier)

    def _decode_version_cursor(
        self,
        value: str | None,
        *,
        user_id: UUID,
        workspace_id: UUID,
        document_id: UUID,
    ) -> VersionCursor | None:
        if value is None:
            return None
        position = self._decode_cursor(
            value,
            user_id=user_id,
            workspace_id=workspace_id,
            folder_id=None,
            document_id=document_id,
            kind="version",
        )
        number = position.get("number")
        if (
            set(position) != {"number", "id"}
            or not isinstance(number, int)
            or isinstance(number, bool)
            or number < 1
        ):
            raise _invalid_request()
        raw_id = position["id"]
        if not isinstance(raw_id, str):
            raise _invalid_request()
        try:
            identifier = UUID(raw_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise _invalid_request() from exc
        return VersionCursor(number=number, id=identifier)

    def _decode_cursor(
        self,
        value: str,
        *,
        user_id: UUID,
        workspace_id: UUID,
        folder_id: UUID | None,
        document_id: UUID | None,
        kind: str,
    ) -> dict[str, object]:
        if not value or len(value) > self.cursor_max_chars:
            raise _invalid_request()
        try:
            encoded_payload, encoded_signature = value.split(".", maxsplit=1)
            payload = _base64_decode(encoded_payload)
            signature = _base64_decode(encoded_signature)
            if not hmac.compare_digest(
                signature,
                hmac.digest(self._cursor_key, payload, "sha256"),
            ):
                raise ValueError("invalid cursor signature")
            decoded = json.loads(payload)
            if not isinstance(decoded, dict) or set(decoded) != {
                "version",
                "actor",
                "scope",
                "position",
            }:
                raise ValueError("invalid cursor payload")
            scope = decoded["scope"]
            position = decoded["position"]
            expected_scope = {
                "kind": kind,
                "workspace": str(workspace_id),
                "folder": str(folder_id) if folder_id is not None else None,
                "document": str(document_id) if document_id is not None else None,
            }
            if (
                type(decoded["version"]) is not int
                or decoded["version"] != 1
                or not isinstance(decoded["actor"], str)
                or decoded["actor"] != str(user_id)
                or not isinstance(scope, dict)
                or set(scope) != set(expected_scope)
                or scope != expected_scope
                or not isinstance(position, dict)
            ):
                raise ValueError("invalid cursor scope")
        except (
            ValueError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            binascii.Error,
        ) as exc:
            raise _invalid_request() from exc
        return position


def _base64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64_decode(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def _not_found() -> AppError:
    return AppError("not_found", "The requested resource was not found.", 404)


def _invalid_request() -> AppError:
    return AppError("invalid_library_request", "The library request is invalid.", 422)


def _unsafe_hierarchy() -> AppError:
    return AppError(
        "invalid_folder_hierarchy",
        "The folder hierarchy cannot be loaded safely.",
        409,
    )


def get_library_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LibraryService:
    return LibraryService(
        SqlAlchemyLibraryRepository(session),
        secret_key=settings.secret_key.get_secret_value(),
        default_page_size=settings.library_page_size,
        max_page_size=settings.library_max_page_size,
        max_depth=settings.library_max_depth,
        cursor_max_chars=settings.library_cursor_max_chars,
    )
