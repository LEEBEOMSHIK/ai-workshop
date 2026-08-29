from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.platform.jobs.repository import JobRepository
from ai_workshop.platform.jobs.service import JobService, get_job_service


class MemoryJobRepository(JobRepository):
    def __init__(self, job: Job) -> None:
        self.job = job

    async def find_by_idempotency(
        self,
        user_id: UUID,
        type: JobType,
        idempotency_key: str,
    ) -> Job | None:
        return None

    async def add(self, job: Job) -> Job:
        self.job = job
        return job

    async def find_for_user(self, user_id: UUID, job_id: UUID) -> Job | None:
        if self.job.id == job_id and self.job.user_id == user_id:
            return self.job
        return None

    async def find_by_id(self, job_id: UUID) -> Job | None:
        return self.job if self.job.id == job_id else None

    async def update(self, job: Job) -> Job:
        self.job = job
        return job


def user(user_id: UUID) -> User:
    return User(
        id=user_id,
        display_name="Owner",
        email="owner@example.com",
        normalized_email="owner@example.com",
        password_hash="hash",
        role=UserRole.OWNER,
    )


def test_job_status_is_visible_only_to_its_requesting_user() -> None:
    owner_id = uuid4()
    job = Job.create(
        user_id=owner_id,
        workspace_id=uuid4(),
        asset_version_id=uuid4(),
        type=JobType.VERIFY_ASSET,
        idempotency_key="asset-version:test",
    )
    repository = MemoryJobRepository(job)
    app = create_app()
    app.dependency_overrides[get_job_service] = lambda: JobService(repository)
    app.dependency_overrides[get_current_user] = lambda: user(owner_id)

    with TestClient(app) as client:
        response = client.get(f"/api/v1/jobs/{job.id}")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(job.id),
        "type": "verify_asset",
        "status": "queued",
        "stage": "queued",
        "attempt": 0,
        "error_code": None,
        "error_message": None,
        "started_at": None,
        "finished_at": None,
    }

    app.dependency_overrides[get_current_user] = lambda: user(uuid4())
    with TestClient(app) as client:
        hidden = client.get(f"/api/v1/jobs/{job.id}")

    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "not_found"
