from collections.abc import AsyncIterator, Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ai_workshop.config import get_settings
from ai_workshop.main import create_app
from ai_workshop.platform.assets.domain import AssetVersion, Document, Folder, VersionStatus
from ai_workshop.platform.assets.library import (
    AssetVersionPage,
    LibraryFolder,
    LibraryPage,
    get_library_service,
)
from ai_workshop.platform.assets.service import (
    AssetUploadResult,
    get_asset_upload_coordinator,
)
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.platform.workspaces.domain import Workspace, WorkspaceKind
from ai_workshop.worker import get_job_dispatcher


@pytest.fixture(autouse=True)
def synthetic_secret_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AI_WORKSHOP_SECRET_KEY", "synthetic-asset-api-test-secret-key")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def owner() -> User:
    return User(
        id=uuid4(),
        display_name="Owner",
        email="owner@example.com",
        normalized_email="owner@example.com",
        password_hash="hash",
        role=UserRole.OWNER,
    )


class UploadCoordinatorStub:
    def __init__(self, result: AssetUploadResult) -> None:
        self.result = result

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
        return self.result


class RecordingDispatcher:
    def __init__(self) -> None:
        self.job_ids: list[UUID] = []

    def verify_asset(self, job_id: UUID) -> None:
        self.job_ids.append(job_id)


class LibraryServiceStub:
    def __init__(self, page: LibraryPage, document: Document) -> None:
        self.page = page
        self.selected_document = document

    async def browse(self, **_kwargs: object) -> LibraryPage:
        return self.page

    async def document(self, **_kwargs: object) -> Document:
        return self.selected_document

    async def versions(self, **_kwargs: object) -> AssetVersionPage:
        return AssetVersionPage(tuple(reversed(self.selected_document.versions)), "next-version")


def test_upload_returns_durable_job_id_and_dispatches_after_response() -> None:
    user = owner()
    workspace_id = uuid4()
    document = Document.create(workspace_id=workspace_id, folder_id=None, name="report.pdf")
    version = document.new_version(
        object_key="workspace/document/report.pdf",
        sha256="0" * 64,
        media_type="application/pdf",
        size=6,
    )
    job = Job.create(
        user_id=user.id,
        workspace_id=workspace_id,
        asset_version_id=version.id,
        type=JobType.VERIFY_ASSET,
        idempotency_key=f"asset-version:{version.id}",
    )
    dispatcher = RecordingDispatcher()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_asset_upload_coordinator] = lambda: UploadCoordinatorStub(
        AssetUploadResult(document, job, job_created=True)
    )
    app.dependency_overrides[get_job_dispatcher] = lambda: dispatcher

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/workspaces/{workspace_id}/documents",
            files={"file": ("report.pdf", b"report", "application/pdf")},
        )

    assert response.status_code == 201
    assert response.json()["job_id"] == str(job.id)
    assert dispatcher.job_ids == [job.id]


def test_library_route_requires_authentication() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get(f"/api/v1/workspaces/{uuid4()}/library")

    assert response.status_code == 401


def test_library_endpoints_serialize_scoped_metadata_and_versions() -> None:
    user = owner()
    workspace = Workspace(
        id=uuid4(),
        name="Synthetic library",
        kind=WorkspaceKind.TEAM,
        created_by=user.id,
    )
    folder = Folder(uuid4(), workspace.id, None, "Reports")
    child = Folder(uuid4(), workspace.id, folder.id, "Annual")
    document = Document.create(
        workspace_id=workspace.id,
        folder_id=folder.id,
        name="synthetic.md",
    )
    active = document.new_version(
        object_key="synthetic/v1.md",
        sha256="1" * 64,
        media_type="text/markdown",
        size=1,
    )
    latest = AssetVersion(
        id=uuid4(),
        document_id=document.id,
        number=2,
        object_key="synthetic/v2.md",
        sha256="2" * 64,
        media_type="text/markdown",
        size=2,
        status=VersionStatus.PROCESSING,
    )
    document.versions.append(latest)
    document.active_version_id = active.id
    page = LibraryPage(
        workspace=workspace,
        folder=folder,
        ancestors=(),
        folders=(LibraryFolder(child, False),),
        documents=(document,),
        next_folder_cursor="next-folder",
        next_document_cursor="next-document",
    )
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_library_service] = lambda: LibraryServiceStub(page, document)

    with TestClient(app) as client:
        browse = client.get(f"/api/v1/workspaces/{workspace.id}/library")
        detail = client.get(
            f"/api/v1/workspaces/{workspace.id}/library/documents/{document.id}"
        )
        versions = client.get(
            f"/api/v1/workspaces/{workspace.id}/library/documents/{document.id}/versions"
        )

    assert browse.status_code == 200
    assert browse.json()["workspace"] == {
        "id": str(workspace.id),
        "name": "Synthetic library",
        "kind": "team",
        "expires_at": None,
    }
    assert browse.json()["folders"] == [
        {
            "id": str(child.id),
            "name": "Annual",
            "parent_id": str(folder.id),
            "metadata_revision": 1,
            "has_children": False,
        }
    ]
    assert browse.json()["documents"][0]["workspace_id"] == str(workspace.id)
    assert browse.json()["documents"][0]["folder_id"] == str(folder.id)
    assert browse.json()["documents"][0]["active_version_id"] == str(active.id)
    assert browse.json()["documents"][0]["latest_version_id"] == str(latest.id)
    assert browse.json()["next_folder_cursor"] == "next-folder"
    assert browse.json()["next_document_cursor"] == "next-document"
    assert detail.status_code == 200
    assert detail.json()["id"] == str(document.id)
    assert versions.status_code == 200
    assert [item["number"] for item in versions.json()["items"]] == [2, 1]
    assert versions.json()["next_cursor"] == "next-version"
