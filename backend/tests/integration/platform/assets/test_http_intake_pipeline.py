"""Synthetic HTTP streams through real PostgreSQL journals and Windows native stores."""

import asyncio
import json
import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ai_workshop.infrastructure.object_store.intake import TrackedIntakeStore
from ai_workshop.platform.assets.intake_models import UploadIntakeRecord
from ai_workshop.platform.assets.intake_repository import UploadIntakeJournal, record_claim
from ai_workshop.platform.assets.intake_service import HttpUploadIntakeService
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord, FolderRecord
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.temporary_contracts import TemporaryBinding
from ai_workshop.platform.assets.upload_models import OriginalResourceRecord, UploadAttemptRecord
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.platform.assets.original_upload_support import (
    require_explicit_original_test_database,
)
from tests.integration.platform.assets.test_tracked_uploads import configure, coordinator, seed
from tests.integration.publishing_support import isolated_publishing_database

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native HTTP intake pipeline")


@pytest.fixture(autouse=True)
def ensure_legacy_document_processing_profile() -> None:
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


def stores(tmp_path):
    originals = tmp_path / "originals"
    originals.mkdir()
    settings = configure(originals)
    temporary = tmp_path / "intakes"
    temporary.mkdir()
    binding = TemporaryBinding("http_pipeline", uuid4())
    (temporary / ".ai-workshop-temporary-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "store_id": binding.store_id,
                "binding_id": str(binding.binding_id),
            }
        ),
        encoding="utf-8",
    )
    return settings, temporary, TrackedIntakeStore(temporary, binding)


def multipart(payload=b"first original", *, folder=None, duplicate=False, truncated=False):
    file = (
        b'--pipeline\r\nContent-Disposition: form-data; name="file"; filename="synthetic.txt"\r\n'
        b"Content-Type: text/plain\r\n\r\n" + payload + b"\r\n"
    )
    body = file
    if duplicate:
        body += file
    if folder is not None:
        body += (
            b'--pipeline\r\nContent-Disposition: form-data; name="folder_id"\r\n\r\n'
            + str(folder).encode()
            + b"\r\n"
        )
    return body if truncated else body + b"--pipeline--\r\n"


async def stream(body):
    # Splits headers, separators, field UUIDs, payload and terminal suffix.
    for offset in range(0, len(body), 7):
        yield body[offset : offset + 7]


def service(session, sessions, settings, store):
    return HttpUploadIntakeService(
        UploadIntakeJournal(sessions), store, coordinator(session, settings)
    )


async def upload(session, sessions, settings, store, user, workspace, body, *, document=None):
    return await service(session, sessions, settings, store).upload(
        user=user,
        workspace_id=workspace if document is None else None,
        document_id=document,
        stream=stream(body),
        content_type="multipart/form-data; boundary=pipeline",
    )


def test_native_stream_folder_after_file_and_existing_version_keep_planned_ids(
    database_url, tmp_path
):
    async def run():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            settings, temporary, store = stores(tmp_path)
            folder = uuid4()
            async with sessions.begin() as session:
                session.add(
                    FolderRecord(
                        id=folder, workspace_id=workspace, parent_id=None, name="Synthetic folder"
                    )
                )
            planned = []

            async def checked_stream():
                async with sessions() as observer:
                    row = await observer.scalar(
                        select(UploadIntakeRecord).where(
                            UploadIntakeRecord.workspace_id == workspace
                        )
                    )
                    assert row is not None and (row.state, row.revision) == ("open", 1)
                    assert await observer.get(DocumentRecord, row.document_id) is None
                    assert await observer.get(AssetVersionRecord, row.asset_version_id) is None
                    assert (temporary / str(row.id) / "payload.bin").exists()
                    planned.append((row.document_id, row.asset_version_id))
                async for part in stream(multipart(folder=folder)):
                    yield part

            async with sessions() as session:
                first = await service(session, sessions, settings, store).upload(
                    user=user,
                    workspace_id=workspace,
                    stream=checked_stream(),
                    content_type="multipart/form-data; boundary=pipeline",
                )
            assert first.document.folder_id == folder
            assert (first.document.id, first.document.versions[-1].id) == planned[0]
            async with sessions() as session:
                second = await upload(
                    session,
                    sessions,
                    settings,
                    store,
                    user,
                    workspace,
                    multipart(b"second original"),
                    document=first.document.id,
                )
            assert second.document.id == first.document.id
            assert second.document.versions[-1].number == 2
            async with sessions() as session:
                rows = list(
                    await session.scalars(
                        select(UploadIntakeRecord).where(
                            UploadIntakeRecord.workspace_id == workspace
                        )
                    )
                )
                assert len(rows) == 2
                for row in rows:
                    assert (row.state, row.revision, row.attached) == ("cleaned", 6, True)
                    assert not store.observe(record_claim(row))
                    assert not (temporary / str(row.id)).exists()
                    attempt = await session.get(UploadAttemptRecord, row.original_attempt_id)
                    version = await session.get(AssetVersionRecord, row.asset_version_id)
                    original = await session.get(OriginalResourceRecord, row.original_attempt_id)
                    assert attempt.state == "attached" and original is not None
                    assert (
                        attempt.workspace_id,
                        attempt.document_id,
                        attempt.asset_version_id,
                    ) == (row.workspace_id, row.document_id, row.asset_version_id)
                    assert version.document_id == row.document_id
                    expected = b"first original" if row.new_document else b"second original"
                    assert (
                        settings.object_store_root / attempt.canonical_key
                    ).read_bytes() == expected
                    assert not (settings.object_store_root / attempt.temporary_key).exists()
                    relations = list(
                        await session.scalars(
                            select(AssetSourceRelationRecord).where(
                                AssetSourceRelationRecord.resource_id.in_(
                                    [row.id, row.original_attempt_id]
                                )
                            )
                        )
                    )
                    assert {(r.participant, r.resource_revision) for r in relations} == {
                        ("platform_http_uploads", 6),
                        ("platform_originals", 1),
                    }
                    assert all(r.asset_version_id == row.asset_version_id for r in relations)
                jobs = list(
                    await session.scalars(
                        select(JobRecord).where(JobRecord.workspace_id == workspace)
                    )
                )
                assert len(jobs) == 2 and {j.id for j in jobs} == {first.job.id, second.job.id}
                assert {j.asset_version_id for j in jobs} == {row.asset_version_id for row in rows}
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("case", ["truncated", "duplicate", "epilogue"])
def test_malformed_stream_closes_tracked_payload_without_original_or_job(
    database_url, tmp_path, case
):
    async def run():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            settings, temporary, store = stores(tmp_path)
            body = multipart(truncated=case == "truncated", duplicate=case == "duplicate")
            if case == "epilogue":
                body += b"not accepted"
            async with sessions() as session:
                with pytest.raises(AppError) as caught:
                    await upload(session, sessions, settings, store, user, workspace, body)
                assert 400 <= caught.value.status_code < 500
            async with sessions() as session:
                row = await session.scalar(
                    select(UploadIntakeRecord).where(UploadIntakeRecord.workspace_id == workspace)
                )
                assert (row.state, row.revision, row.attached) == ("cleaned", 4, False)
                assert row.original_attempt_id is None and not store.observe(record_claim(row))
                assert not (temporary / str(row.id)).exists()
                assert await session.get(DocumentRecord, row.document_id) is None
                assert await session.get(AssetVersionRecord, row.asset_version_id) is None
                assert not list(
                    await session.scalars(
                        select(UploadAttemptRecord).where(
                            UploadAttemptRecord.workspace_id == workspace
                        )
                    )
                )
                assert not list(
                    await session.scalars(
                        select(JobRecord).where(JobRecord.workspace_id == workspace)
                    )
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_duplicate_content_preserves_first_original_and_removes_failed_attempt_bytes(
    database_url, tmp_path
):
    async def run():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            settings, _, store = stores(tmp_path)
            async with sessions() as session:
                first = await upload(
                    session, sessions, settings, store, user, workspace, multipart()
                )
            async with sessions() as session:
                with pytest.raises(AppError, match="same content") as caught:
                    await upload(session, sessions, settings, store, user, workspace, multipart())
                assert caught.value.status_code == 409
            async with sessions() as session:
                rows = list(
                    await session.scalars(
                        select(UploadIntakeRecord).where(
                            UploadIntakeRecord.workspace_id == workspace
                        )
                    )
                )
                assert len(rows) == 2
                assert sorted((row.state, row.revision) for row in rows) == [
                    ("cleaned", 5),
                    ("cleaned", 6),
                ]
                for row in rows:
                    assert not store.observe(record_claim(row))
                    attempt = await session.get(UploadAttemptRecord, row.original_attempt_id)
                    if row.attached:
                        assert row.document_id == first.document.id and attempt.state == "attached"
                        assert (
                            settings.object_store_root / attempt.canonical_key
                        ).read_bytes() == b"first original"
                    else:
                        assert attempt.state == "abandoned" and attempt.revision == 4
                        assert await session.get(DocumentRecord, row.document_id) is None
                        assert await session.get(AssetVersionRecord, row.asset_version_id) is None
                        assert not (settings.object_store_root / attempt.canonical_key).exists()
                        assert not (settings.object_store_root / attempt.temporary_key).exists()
                assert (
                    len(
                        list(
                            await session.scalars(
                                select(JobRecord).where(JobRecord.workspace_id == workspace)
                            )
                        )
                    )
                    == 1
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_final_commit_response_loss_preserves_attached_intake_and_payload(database_url, tmp_path):
    class LostCommitSession(AsyncSession):
        async def commit(self):
            await super().commit()
            raise RuntimeError("synthetic_http_commit_response_lost")

    async def run():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            settings, temporary, store = stores(tmp_path)
            async with LostCommitSession(engine, expire_on_commit=False) as session:
                with pytest.raises(AppError) as caught:
                    await upload(session, sessions, settings, store, user, workspace, multipart())
                assert caught.value.status_code == 503
            async with sessions() as session:
                row = await session.scalar(
                    select(UploadIntakeRecord).where(UploadIntakeRecord.workspace_id == workspace)
                )
                assert (row.state, row.revision, row.attached) == ("open", 3, True)
                assert store.observe(record_claim(row))
                assert (temporary / str(row.id) / "payload.bin").read_bytes() == b"first original"
                attempt = await session.get(UploadAttemptRecord, row.original_attempt_id)
                assert attempt.state == "attached"
                assert (
                    settings.object_store_root / attempt.canonical_key
                ).read_bytes() == b"first original"
                assert await session.get(AssetVersionRecord, row.asset_version_id)
                assert (
                    len(
                        list(
                            await session.scalars(
                                select(JobRecord).where(JobRecord.workspace_id == workspace)
                            )
                        )
                    )
                    == 1
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_native_cleanup_failure_preserves_success_and_durable_attachment(database_url, tmp_path):
    class FailedCleanupStore:
        def __init__(self, real):
            self.real = real
            self.binding = real.binding

        def create(self, claim):
            real = self.real.create(claim)

            class FailedCleanupWorkspace:
                root = real.root

                def create_file(self, name):
                    return real.create_file(name)

                def discard(self):
                    raise RuntimeError("synthetic_cleanup_failure")

                def close(self):
                    real.close()

            return FailedCleanupWorkspace()

        def observe(self, claim):
            return self.real.observe(claim)

    async def run():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            user, workspace = await seed(sessions)
            settings, temporary, native = stores(tmp_path)
            async with sessions() as session:
                result = await upload(
                    session,
                    sessions,
                    settings,
                    FailedCleanupStore(native),
                    user,
                    workspace,
                    multipart(),
                )
            async with sessions() as session:
                row = await session.scalar(
                    select(UploadIntakeRecord).where(UploadIntakeRecord.workspace_id == workspace)
                )
                assert (row.state, row.revision, row.attached) == ("cleaning", 5, True)
                assert native.observe(record_claim(row))
                assert (temporary / str(row.id) / "payload.bin").read_bytes() == b"first original"
                assert row.document_id == result.document.id
                assert await session.get(JobRecord, result.job.id)
                attempt = await session.get(UploadAttemptRecord, row.original_attempt_id)
                assert attempt.state == "attached"
                assert (
                    settings.object_store_root / attempt.canonical_key
                ).read_bytes() == b"first original"
                relation = await session.scalar(
                    select(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.resource_id == row.id
                    )
                )
                assert relation.resource_revision == 5
        finally:
            await engine.dispose()

    asyncio.run(run())
