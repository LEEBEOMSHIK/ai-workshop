import asyncio
import json
import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_workshop.config import Settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.service import AssetService, get_asset_upload_coordinator
from ai_workshop.platform.assets.upload_contracts import UploadOwnershipError
from ai_workshop.platform.assets.upload_models import OriginalResourceRecord, UploadAttemptRecord
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.jobs.repository import SqlAlchemyJobRepository
from ai_workshop.platform.jobs.service import JobService
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.platform.assets.original_upload_support import (
    require_explicit_original_test_database,
)
from tests.integration.publishing_support import isolated_publishing_database
from tests.unit.platform.assets.test_asset_service import owner

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Tracked original writes require Windows")


@pytest.fixture(autouse=True)
def ensure_legacy_document_processing_profile():
    pass


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    require_explicit_original_test_database()
    monkeypatch = pytest.MonkeyPatch()
    try:
        with isolated_publishing_database(monkeypatch) as database:
            command.upgrade(database.config, "head")
            yield database.database_url
    finally:
        monkeypatch.undo()


async def seed(sessions) -> tuple[User, UUID]:
    user, workspace = owner(), uuid4()
    async with sessions.begin() as session:
        session.add(
            UserRecord(
                id=user.id,
                display_name="Synthetic uploader",
                email=f"{user.id}@example.test",
                normalized_email=f"{user.id}@example.test",
                password_hash="synthetic-test-only",
                role="member",
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            WorkspaceRecord(
                id=workspace, name="Synthetic upload", kind="company", created_by=user.id
            )
        )
        await session.flush()
        session.add(
            WorkspaceMembershipRecord(workspace_id=workspace, user_id=user.id, role="owner")
        )
    return user, workspace


def configure(root: Path) -> Settings:
    binding = uuid4()
    (root / ".ai-workshop-original-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "store_id": "test_originals",
                "binding_id": str(binding),
            }
        ),
        encoding="utf-8",
    )
    return Settings(
        _env_file=None,
        secret_key="synthetic-original-upload-secret-key",
        original_store_id="test_originals",
        original_store_binding_id=binding,
        object_store_root=root,
    )


def coordinator(session, settings):
    return get_asset_upload_coordinator(
        assets=AssetService(
            SqlAlchemyAssetRepository(session),
            LocalObjectStore(settings.object_store_root),
            max_upload_bytes=20,
            max_depth=64,
        ),
        jobs=JobService(SqlAlchemyJobRepository(session)),
        session=session,
        settings=settings,
    )


async def content(value=b"synthetic original"):
    yield value


async def upload(service, user, workspace, stream=None):
    return await service.upload(
        user=user,
        workspace_id=workspace,
        folder_id=None,
        filename="synthetic.txt",
        media_type="text/plain",
        content=stream if stream is not None else content(),
    )


def test_real_composition_attaches_version_job_relation_and_original(database_url, tmp_path):
    async def run():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            settings = configure(tmp_path)
            async with sessions() as session:
                result = await upload(coordinator(session, settings), user, workspace)
            async with sessions() as session:
                attempt = await session.scalar(
                    select(UploadAttemptRecord).where(UploadAttemptRecord.workspace_id == workspace)
                )
                assert attempt.state == "attached" and attempt.revision == 3
                assert await session.get(JobRecord, result.job.id)
                assert await session.get(OriginalResourceRecord, attempt.id)
                relation = await session.scalar(
                    select(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.resource_id == attempt.id
                    )
                )
                assert relation.asset_version_id == result.document.versions[0].id
                assert relation.resource_revision == 1
                assert (tmp_path / attempt.canonical_key).read_bytes() == b"synthetic original"
                assert not (tmp_path / attempt.temporary_key).exists()
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_commit_response_loss_keeps_durable_original(database_url, tmp_path):
    class LostCommitSession(AsyncSession):
        async def commit(self):
            await super().commit()
            raise RuntimeError("synthetic lost commit response")

    async def run():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            settings = configure(tmp_path)
            async with LostCommitSession(engine, expire_on_commit=False) as session:
                with pytest.raises(RuntimeError, match="lost commit"):
                    await upload(coordinator(session, settings), user, workspace)
            async with sessions() as session:
                attempt = await session.scalar(
                    select(UploadAttemptRecord).where(UploadAttemptRecord.workspace_id == workspace)
                )
                assert attempt.state == "attached"
                assert await session.get(AssetVersionRecord, attempt.asset_version_id)
                assert (tmp_path / attempt.canonical_key).exists()
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_job_failure_rollback_removes_only_this_attempt(database_url, tmp_path):
    async def run():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            settings = configure(tmp_path)
            async with sessions() as session:
                service = coordinator(session, settings)
                service.jobs.create_asset_verification = AsyncMock(side_effect=RuntimeError("job"))
                with pytest.raises(RuntimeError, match="job"):
                    await upload(service, user, workspace)
            async with sessions() as session:
                attempt = await session.scalar(
                    select(UploadAttemptRecord).where(UploadAttemptRecord.workspace_id == workspace)
                )
                assert attempt.state == "abandoned" and attempt.revision == 4
                assert await session.get(DocumentRecord, attempt.document_id) is None
                assert await session.get(AssetVersionRecord, attempt.asset_version_id) is None
                assert not (tmp_path / attempt.canonical_key).exists()
                assert not (tmp_path / attempt.temporary_key).exists()
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_concurrent_versions_get_fresh_numbers(database_url, tmp_path):
    async def run():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            settings = configure(tmp_path)
            async with sessions() as session:
                first = await upload(coordinator(session, settings), user, workspace)

            async def new_version(value):
                async with sessions() as session:
                    return await coordinator(session, settings).upload_version(
                        user=user,
                        document_id=first.document.id,
                        filename="new.txt",
                        media_type="text/plain",
                        content=content(value),
                    )

            results = await asyncio.wait_for(
                asyncio.gather(new_version(b"version two"), new_version(b"version three")),
                timeout=20,
            )
            assert sorted(result.document.versions[-1].number for result in results) == [2, 3]
            async with sessions() as session:
                versions = list(
                    await session.scalars(
                        select(AssetVersionRecord).where(
                            AssetVersionRecord.document_id == first.document.id
                        )
                    )
                )
                assert len(versions) == 3
                assert len({version.object_key for version in versions}) == 3
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("revoke", ["permission", "generation"])
def test_mid_stream_authority_change_cannot_attach(database_url, tmp_path, revoke):
    async def run():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            settings = configure(tmp_path)
            async with sessions() as session:
                first = await upload(coordinator(session, settings), user, workspace)

            async def changed():
                yield b"new bytes"
                async with sessions.begin() as session:
                    if revoke == "permission":
                        await session.execute(
                            delete(WorkspaceMembershipRecord).where(
                                WorkspaceMembershipRecord.workspace_id == workspace
                            )
                        )
                    else:
                        await session.execute(
                            update(DocumentRecord)
                            .where(DocumentRecord.id == first.document.id)
                            .values(lifecycle_generation=2)
                        )

            async with sessions() as session:
                with pytest.raises((AppError, UploadOwnershipError)):
                    await coordinator(session, settings).upload_version(
                        user=user,
                        document_id=first.document.id,
                        filename="new.txt",
                        media_type="text/plain",
                        content=changed(),
                    )
            async with sessions() as session:
                attempts = list(
                    await session.scalars(
                        select(UploadAttemptRecord).where(
                            UploadAttemptRecord.workspace_id == workspace
                        )
                    )
                )
                assert sorted(item.state for item in attempts) == ["abandoned", "attached"]
                for item in attempts:
                    assert (tmp_path / item.canonical_key).exists() == (item.state == "attached")
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_duplicate_preserves_first_original(database_url, tmp_path):
    async def run():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            settings = configure(tmp_path)
            async with sessions() as session:
                first = await upload(coordinator(session, settings), user, workspace)
            async with sessions() as session:
                with pytest.raises(AppError) as exc:
                    await upload(coordinator(session, settings), user, workspace)
                assert exc.value.code == "duplicate_document_content"
            assert (
                tmp_path / first.document.versions[0].object_key
            ).read_bytes() == b"synthetic original"
            async with sessions() as session:
                attempts = list(
                    await session.scalars(
                        select(UploadAttemptRecord).where(
                            UploadAttemptRecord.workspace_id == workspace
                        )
                    )
                )
                assert sorted(item.state for item in attempts) == ["abandoned", "attached"]
        finally:
            await engine.dispose()

    asyncio.run(run())
