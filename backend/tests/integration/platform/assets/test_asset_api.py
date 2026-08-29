from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ai_workshop.main import create_app
from ai_workshop.platform.assets.domain import Document
from ai_workshop.platform.assets.service import (
    AssetUploadResult,
    get_asset_upload_coordinator,
)
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.worker import get_job_dispatcher


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
