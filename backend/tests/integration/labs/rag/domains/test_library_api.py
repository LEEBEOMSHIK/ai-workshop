from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ai_workshop.labs.rag.domains.library import DomainLibraryService
from ai_workshop.labs.rag.domains.library_api import get_domain_library_service
from ai_workshop.labs.rag.domains.service import (
    Domain,
    DomainConnectionVersion,
    DomainLibraryContext,
    DomainWorkspaceOption,
)
from ai_workshop.main import create_app
from ai_workshop.platform.assets.domain import AssetVersion, Document, Folder, VersionStatus
from ai_workshop.platform.assets.library import (
    AssetVersionPage,
    LibraryFolder,
    LibraryPage,
    get_library_service,
)
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.workspaces.domain import Workspace, WorkspaceKind
from ai_workshop.shared.errors import AppError

ACTOR_ID = UUID("10000000-0000-0000-0000-000000000001")
DOMAIN_ID = UUID("20000000-0000-0000-0000-000000000001")
CONNECTION_ID = UUID("30000000-0000-0000-0000-000000000001")
CONFIGURATION_VERSION_ID = UUID("40000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("50000000-0000-0000-0000-000000000001")
FOREIGN_WORKSPACE_ID = UUID("50000000-0000-0000-0000-000000000002")
FOLDER_ID = UUID("60000000-0000-0000-0000-000000000001")
CHILD_FOLDER_ID = UUID("60000000-0000-0000-0000-000000000002")
DOCUMENT_ID = UUID("70000000-0000-0000-0000-000000000001")
ACTIVE_VERSION_ID = UUID("80000000-0000-0000-0000-000000000001")
LATEST_VERSION_ID = UUID("80000000-0000-0000-0000-000000000002")


def _user() -> User:
    return User(
        id=ACTOR_ID,
        display_name="Domain library member",
        email="domain-library@example.test",
        normalized_email="domain-library@example.test",
        password_hash="hash",
        role=UserRole.MEMBER,
    )


def _context() -> DomainLibraryContext:
    domain = Domain(
        id=DOMAIN_ID,
        slug="fund-management",
        display_name="자산운용",
        description="승인된 지식",
        active_connection_version_id=CONNECTION_ID,
        created_by=ACTOR_ID,
    )
    connection = DomainConnectionVersion(
        id=CONNECTION_ID,
        domain_id=DOMAIN_ID,
        version=3,
        configuration_version_id=CONFIGURATION_VERSION_ID,
        workspace_ids=(WORKSPACE_ID,),
        created_by=ACTOR_ID,
    )
    return DomainLibraryContext(
        domain=domain,
        connection=connection,
        workspace_options=(
            DomainWorkspaceOption(
                WORKSPACE_ID,
                "허용 공간",
                WorkspaceKind.TEAM,
                None,
            ),
        ),
    )


def _document() -> Document:
    document = Document(
        id=DOCUMENT_ID,
        workspace_id=WORKSPACE_ID,
        folder_id=FOLDER_ID,
        name="status.md",
        active_version_id=ACTIVE_VERSION_ID,
        versions=[],
    )
    document.versions.extend(
        [
            AssetVersion(
                id=ACTIVE_VERSION_ID,
                document_id=DOCUMENT_ID,
                number=1,
                object_key="synthetic/status-v1.md",
                sha256="1" * 64,
                media_type="text/markdown",
                size=1,
                status=VersionStatus.READY,
            ),
            AssetVersion(
                id=LATEST_VERSION_ID,
                document_id=DOCUMENT_ID,
                number=2,
                object_key="synthetic/status-v2.md",
                sha256="2" * 64,
                media_type="text/markdown",
                size=2,
                status=VersionStatus.PROCESSING,
            ),
        ]
    )
    return document


class MutableResolver:
    def __init__(self) -> None:
        self.context: DomainLibraryContext | None = _context()
        self.calls: list[tuple[str, UUID]] = []

    async def resolve_library(
        self,
        *,
        slug: str,
        actor_id: UUID,
    ) -> DomainLibraryContext:
        self.calls.append((slug, actor_id))
        if self.context is None:
            raise AppError("not_found", "The requested resource was not found.", 404)
        return self.context


class PlatformLibraryStub:
    def __init__(self) -> None:
        self.workspace = Workspace(
            id=WORKSPACE_ID,
            name="허용 공간",
            kind=WorkspaceKind.TEAM,
            created_by=ACTOR_ID,
        )
        self.folder = Folder(FOLDER_ID, WORKSPACE_ID, None, "Reports")
        self.child = Folder(CHILD_FOLDER_ID, WORKSPACE_ID, FOLDER_ID, "Annual")
        self.selected_document = _document()
        self.browse_calls: list[dict[str, object]] = []
        self.document_calls: list[dict[str, object]] = []
        self.version_calls: list[dict[str, object]] = []

    async def browse(self, **kwargs: object) -> LibraryPage:
        self.browse_calls.append(kwargs)
        return LibraryPage(
            workspace=self.workspace,
            folder=self.folder,
            ancestors=(),
            folders=(LibraryFolder(self.child, False),),
            documents=(self.selected_document,),
            next_folder_cursor="next-folder",
            next_document_cursor="next-document",
        )

    async def document(self, **kwargs: object) -> Document:
        self.document_calls.append(kwargs)
        return self.selected_document

    async def versions(self, **kwargs: object) -> AssetVersionPage:
        self.version_calls.append(kwargs)
        return AssetVersionPage(
            tuple(reversed(self.selected_document.versions)),
            "next-version",
        )


def _app(
    service: DomainLibraryService,
    platform: PlatformLibraryStub,
) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_domain_library_service] = lambda: service
    app.dependency_overrides[get_library_service] = lambda: platform
    return app


@pytest.mark.asyncio
async def test_domain_library_api_exposes_metadata_and_direct_folder_document_urls() -> None:
    resolver = MutableResolver()
    platform = PlatformLibraryStub()
    service = DomainLibraryService(resolver, platform, selection_limit=17)
    app = _app(service, platform)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        metadata = await client.get("/api/v1/rag/domains/fund-management/library")
        browse = await client.get(
            f"/api/v1/rag/domains/fund-management/library/workspaces/{WORKSPACE_ID}",
            params={
                "folder_id": str(FOLDER_ID),
                "folder_cursor": "folder-cursor",
                "document_cursor": "document-cursor",
                "limit": "7",
            },
        )
        detail = await client.get(
            "/api/v1/rag/domains/fund-management/library/"
            f"workspaces/{WORKSPACE_ID}/documents/{DOCUMENT_ID}"
        )

    assert metadata.status_code == 200
    assert metadata.json() == {
        "domain_id": str(DOMAIN_ID),
        "display_name": "자산운용",
        "connection_version_id": str(CONNECTION_ID),
        "workspace_options": [
            {
                "id": str(WORKSPACE_ID),
                "name": "허용 공간",
                "kind": "team",
                "expires_at": None,
            }
        ],
        "selection_limit": 17,
    }
    assert browse.status_code == 200
    assert browse.json()["workspace"]["id"] == str(WORKSPACE_ID)
    assert browse.json()["folder"]["id"] == str(FOLDER_ID)
    assert browse.json()["folders"][0]["id"] == str(CHILD_FOLDER_ID)
    assert browse.json()["documents"][0]["status"] == "processing"
    assert browse.json()["documents"][0]["active_version_id"] == str(ACTIVE_VERSION_ID)
    assert browse.json()["documents"][0]["latest_version_id"] == str(LATEST_VERSION_ID)
    assert detail.status_code == 200
    assert detail.json()["id"] == str(DOCUMENT_ID)
    assert resolver.calls == [("fund-management", ACTOR_ID)] * 3
    assert platform.browse_calls == [
        {
            "user": _user(),
            "workspace_id": WORKSPACE_ID,
            "folder_id": FOLDER_ID,
            "folder_cursor": "folder-cursor",
            "document_cursor": "document-cursor",
            "limit": 7,
        }
    ]
    assert platform.document_calls == [
        {
            "user": _user(),
            "workspace_id": WORKSPACE_ID,
            "document_id": DOCUMENT_ID,
        }
    ]


@pytest.mark.asyncio
async def test_domain_library_api_fails_closed_before_platform_after_scope_change() -> None:
    resolver = MutableResolver()
    platform = PlatformLibraryStub()
    service = DomainLibraryService(resolver, platform, selection_limit=17)
    app = _app(service, platform)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        foreign = await client.get(
            "/api/v1/rag/domains/fund-management/library/"
            f"workspaces/{FOREIGN_WORKSPACE_ID}"
        )
        allowed = await client.get(
            f"/api/v1/rag/domains/fund-management/library/workspaces/{WORKSPACE_ID}"
        )
        resolver.context = None
        changed = await client.get(
            "/api/v1/rag/domains/fund-management/library/"
            f"workspaces/{WORKSPACE_ID}/documents/{DOCUMENT_ID}"
        )

    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "not_found"
    assert allowed.status_code == 200
    assert changed.status_code == 404
    assert changed.json()["error"]["code"] == "not_found"
    assert len(platform.browse_calls) == 1
    assert platform.document_calls == []


@pytest.mark.asyncio
async def test_historical_versions_continue_through_platform_acl_endpoint() -> None:
    resolver = MutableResolver()
    resolver.context = None
    platform = PlatformLibraryStub()
    service = DomainLibraryService(resolver, platform, selection_limit=17)
    app = _app(service, platform)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        versions = await client.get(
            f"/api/v1/workspaces/{WORKSPACE_ID}/library/documents/{DOCUMENT_ID}/versions",
            params={"cursor": "version-cursor", "limit": "2"},
        )

    assert versions.status_code == 200
    assert [item["number"] for item in versions.json()["items"]] == [2, 1]
    assert versions.json()["next_cursor"] == "next-version"
    assert resolver.calls == []
    assert platform.version_calls == [
        {
            "user": _user(),
            "workspace_id": WORKSPACE_ID,
            "document_id": DOCUMENT_ID,
            "cursor": "version-cursor",
            "limit": 2,
        }
    ]
