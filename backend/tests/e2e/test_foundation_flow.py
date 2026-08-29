from asyncio import sleep
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from os import environ
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text, update

from ai_workshop.config import get_settings
from ai_workshop.main import create_app
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.identity.service import Argon2PasswordHasher
from ai_workshop.platform.workspaces.domain import MembershipRole
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.shared.db import create_engine, create_session_factory

pytestmark = pytest.mark.skipif(
    environ.get("AI_WORKSHOP_E2E") != "1",
    reason="Set AI_WORKSHOP_E2E=1 to run tests against the disposable PostgreSQL database.",
)

OWNER_EMAIL = "owner.e2e@example.com"
MEMBER_EMAIL = "member.e2e@example.com"
TEST_PASSWORD = "foundation-test-password"
TRUNCATE_SQL = """
TRUNCATE TABLE
    rag_profile_model_bindings,
    rag_profiles,
    rag_model_definitions,
    jobs,
    asset_versions,
    documents,
    folders,
    workspace_memberships,
    workspaces,
    users
RESTART IDENTITY CASCADE
"""


@pytest.fixture(autouse=True)
async def isolated_database() -> AsyncIterator[None]:
    settings = get_settings()
    if settings.environment != "test":
        pytest.fail("Foundation E2E tests require AI_WORKSHOP_ENVIRONMENT=test.")
    engine = create_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(TRUNCATE_SQL))
        yield
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(TRUNCATE_SQL))
        await engine.dispose()


async def seed_user(email: str, display_name: str) -> UUID:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    user_id = uuid4()
    try:
        async with session_factory.begin() as session:
            session.add(
                UserRecord(
                    id=user_id,
                    display_name=display_name,
                    email=email,
                    normalized_email=email.casefold(),
                    password_hash=Argon2PasswordHasher().hash(TEST_PASSWORD),
                    role=UserRole.OWNER,
                    is_active=True,
                )
            )
    finally:
        await engine.dispose()
    return user_id


async def add_membership(workspace_id: UUID, user_id: UUID) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory.begin() as session:
            session.add(
                WorkspaceMembershipRecord(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    role=MembershipRole.MEMBER,
                )
            )
    finally:
        await engine.dispose()


async def expire_workspace(workspace_id: UUID) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory.begin() as session:
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == workspace_id)
                .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
    finally:
        await engine.dispose()


def create_http_client() -> AsyncClient:
    base_url = environ.get("AI_WORKSHOP_E2E_BASE_URL")
    if base_url:
        return AsyncClient(base_url=base_url)
    return AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://test",
    )


async def login(client: AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200


async def wait_for_job(client: AsyncClient, job_id: object) -> dict[str, object]:
    latest: dict[str, object] | None = None
    for _attempt in range(100):
        response = await client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        latest = response.json()
        if latest["status"] in {"succeeded", "failed"}:
            return latest
        await sleep(0.1)
    pytest.fail(f"Job did not reach a terminal state: {latest}")


async def create_workspace(
    client: AsyncClient,
    *,
    name: str,
    kind: str,
    expires_at: datetime | None = None,
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/workspaces",
        json={
            "name": name,
            "kind": kind,
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    assert response.status_code == 201
    return response.json()


async def upload_document(
    client: AsyncClient,
    workspace_id: str,
    *,
    name: str,
    content: bytes,
    folder_id: str | None = None,
) -> dict[str, object]:
    data = {"folder_id": folder_id} if folder_id else None
    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        data=data,
        files={"file": (name, content, "application/pdf")},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_owner_can_complete_the_foundation_flow() -> None:
    await seed_user(OWNER_EMAIL, "Workshop Owner")
    async with create_http_client() as client:
        await login(client, OWNER_EMAIL)

        workspace = await create_workspace(client, name="My Research", kind="personal")
        workspace_id = str(workspace["id"])
        listed = await client.get("/api/v1/workspaces")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [workspace_id]

        folder_response = await client.post(
            f"/api/v1/workspaces/{workspace_id}/folders",
            json={"name": "Quarterly reports", "parent_id": None},
        )
        assert folder_response.status_code == 201
        folder_id = folder_response.json()["id"]

        document = await upload_document(
            client,
            workspace_id,
            name="fund-report.pdf",
            content=b"%PDF-1.7 foundation version one",
            folder_id=folder_id,
        )
        first_job = await wait_for_job(client, document["job_id"])
        assert first_job["status"] == "succeeded"

        second_version = await client.post(
            f"/api/v1/documents/{document['id']}/versions",
            files={
                "file": (
                    "fund-report.pdf",
                    b"%PDF-1.7 foundation version two",
                    "application/pdf",
                )
            },
        )
        assert second_version.status_code == 201
        second_job = await wait_for_job(client, second_version.json()["job_id"])
        assert second_job["status"] == "succeeded"

        versions = await client.get(f"/api/v1/documents/{document['id']}/versions")
        assert versions.status_code == 200
        assert [item["number"] for item in versions.json()] == [1, 2]
        assert all("object_key" not in item and "sha256" not in item for item in versions.json())

        model = await client.post(
            "/api/v1/rag/models",
            json={
                "kind": "embedding",
                "name": "foundation-embedding",
                "version": 1,
                "config": {"dimensions": 768},
            },
        )
        assert model.status_code == 201
        profile = await client.post(
            "/api/v1/rag/profiles/indexing",
            json={
                "name": "foundation-indexing",
                "version": 1,
                "config": {"chunker": {"size": 512, "overlap": 64}},
                "bindings": [{"role": "embedding", "model_id": model.json()["id"]}],
                "evaluation_state": "draft",
            },
        )
        assert profile.status_code == 201
        assert profile.json()["bindings"][0]["model_id"] == model.json()["id"]


@pytest.mark.asyncio
async def test_member_sees_shared_company_assets_but_not_private_or_expired_assets() -> None:
    owner_id = await seed_user(OWNER_EMAIL, "Workshop Owner")
    member_id = await seed_user(MEMBER_EMAIL, "Workshop Member")
    del owner_id

    async with create_http_client() as owner_client:
        await login(owner_client, OWNER_EMAIL)
        company = await create_workspace(owner_client, name="Company Knowledge", kind="company")
        personal = await create_workspace(owner_client, name="Owner Notes", kind="personal")
        temporary = await create_workspace(
            owner_client,
            name="Expiring Review",
            kind="temporary",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        company_document = await upload_document(
            owner_client,
            str(company["id"]),
            name="policy.pdf",
            content=b"%PDF shared policy",
        )
        private_document = await upload_document(
            owner_client,
            str(personal["id"]),
            name="private.pdf",
            content=b"%PDF private notes",
        )
        temporary_document = await upload_document(
            owner_client,
            str(temporary["id"]),
            name="temporary.pdf",
            content=b"%PDF temporary notes",
        )

    await add_membership(UUID(str(company["id"])), member_id)
    await add_membership(UUID(str(temporary["id"])), member_id)
    await expire_workspace(UUID(str(temporary["id"])))

    async with create_http_client() as member_client:
        await login(member_client, MEMBER_EMAIL)

        workspaces = await member_client.get("/api/v1/workspaces")
        assert workspaces.status_code == 200
        assert [item["id"] for item in workspaces.json()] == [str(company["id"])]

        shared = await member_client.get(f"/api/v1/workspaces/{company['id']}/documents")
        assert shared.status_code == 200
        assert [item["id"] for item in shared.json()] == [company_document["id"]]

        private_workspace = await member_client.get(
            f"/api/v1/workspaces/{personal['id']}/documents"
        )
        private_versions = await member_client.get(
            f"/api/v1/documents/{private_document['id']}/versions"
        )
        private_job = await member_client.get(f"/api/v1/jobs/{private_document['job_id']}")
        expired_workspace = await member_client.get(
            f"/api/v1/workspaces/{temporary['id']}/documents"
        )
        expired_versions = await member_client.get(
            f"/api/v1/documents/{temporary_document['id']}/versions"
        )
        expired_job = await member_client.get(f"/api/v1/jobs/{temporary_document['job_id']}")

        assert private_workspace.status_code == 404
        assert private_versions.status_code == 404
        assert private_job.status_code == 404
        assert expired_workspace.status_code == 404
        assert expired_versions.status_code == 404
        assert expired_job.status_code == 404
