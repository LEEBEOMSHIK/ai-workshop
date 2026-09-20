from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.platform.assets.domain import Document
from ai_workshop.platform.assets.service import AssetService
from ai_workshop.platform.assets.storage import StoredObject
from ai_workshop.platform.assets.tracked_uploads import TrackedAssetUploadCoordinator
from ai_workshop.platform.assets.upload_contracts import (
    OriginalFileObservation,
    OriginalStoreBinding,
    UploadClaim,
    UploadOwnershipError,
)
from ai_workshop.platform.jobs.service import JobService
from ai_workshop.shared.errors import AppError
from tests.unit.platform.assets.test_asset_service import (
    FailingJobRepository,
    MemoryAssetRepository,
    MemoryJobRepository,
    owner,
)


class Journal:
    def __init__(self, events: list[str], repository: MemoryAssetRepository):
        self.events = events
        self.repository = repository
        self.claim: UploadClaim | None = None
        self.state = ""
        self.fail_reserve = False
        self.fail_published = False
        self.fail_prepare = False
        self.attached_during_prepare = False

    async def reserve(self, claim: UploadClaim) -> UploadClaim:
        self.claim = replace(claim, generation=None if claim.new_document else 1)
        self.state = "open"
        if self.fail_reserve:
            raise RuntimeError("reservation commit response lost")
        self.events.append("reserved")
        return self.claim

    async def published(self, claim: UploadClaim, stored: StoredObject) -> None:
        if self.fail_published:
            raise RuntimeError("publication record unavailable")
        self.state = "published"
        self.events.append("published")

    async def prepare_attachment(self, session: AsyncSession, claim: UploadClaim):
        if self.attached_during_prepare:
            self.state = "attached"
            raise UploadOwnershipError("invalid_state")
        if self.fail_prepare:
            raise AppError("not_found", "Not found.", 404)
        return None if claim.new_document else self.repository.saved

    async def attach(self, session: AsyncSession, claim: UploadClaim, stored: StoredObject):
        self.events.append("attach")

    async def abandoned(self, claim: UploadClaim, *, expected_state: str):
        assert self.state == expected_state
        self.state = "abandoned"
        self.events.append("abandoned")

    async def cleanup(self, claim, *, expected_state, discard, observe):
        if self.state != expected_state:
            raise UploadOwnershipError("invalid_state")
        if expected_state == "published":
            self.state = "discarding"
        discard()
        observation = observe()
        assert observation.canonical is None and not observation.temporary_exists
        self.state = "abandoned"
        self.events.append("abandoned")


class Store:
    binding = OriginalStoreBinding("originals_test", uuid4())

    def __init__(self, events: list[str]):
        self.events = events
        self.canonical: StoredObject | None = None
        self.bytes = b""
        self.fail_discard = False

    async def publish(self, claim: UploadClaim, source: AsyncIterator[bytes]):
        async for chunk in source:
            self.events.append("first_byte")
            self.bytes += chunk
        self.canonical = StoredObject(claim.canonical_key, len(self.bytes), "a" * 64)
        return self.canonical

    def observe(self, claim: UploadClaim):
        return OriginalFileObservation(self.canonical, False)

    def discard(self, claim: UploadClaim, expected: StoredObject):
        if self.fail_discard:
            raise OSError("cannot remove")
        self.events.append("discard")
        assert self.canonical == expected
        self.canonical = None


def setup(tmp_path: Path, *, failing_jobs=False):
    events: list[str] = []
    repository = MemoryAssetRepository()
    journal = Journal(events, repository)
    store = Store(events)
    session = AsyncMock(spec=AsyncSession)

    async def commit():
        events.append("commit")

    async def rollback():
        events.append("rollback")

    session.commit.side_effect = commit
    session.rollback.side_effect = rollback
    service = TrackedAssetUploadCoordinator(
        AssetService(repository, LocalObjectStore(tmp_path), max_upload_bytes=10, max_depth=64),
        JobService(FailingJobRepository() if failing_jobs else MemoryJobRepository()),
        session=cast(AsyncSession, session),
        journal=journal,
        store=store,
    )
    return service, journal, store, session, events


async def content():
    yield b"hello"


async def upload(service, **kwargs):
    return await service.upload(
        user=owner(),
        workspace_id=uuid4(),
        folder_id=None,
        filename="test.txt",
        media_type="text/plain",
        content=content(),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_reservation_precedes_bytes_and_all_metadata_precedes_commit(tmp_path):
    service, journal, store, session, events = setup(tmp_path)
    result = await upload(service)
    assert events == ["reserved", "first_byte", "published", "attach", "commit"]
    assert journal.claim is not None
    assert result.document.id == journal.claim.source.document_id
    assert result.document.versions[0].id == journal.claim.source.asset_version_id
    assert result.job.asset_version_id == journal.claim.source.asset_version_id


@pytest.mark.asyncio
async def test_uncertain_reservation_does_not_consume_bytes(tmp_path):
    service, journal, store, session, events = setup(tmp_path)
    journal.fail_reserve = True
    with pytest.raises(RuntimeError, match="reservation"):
        await upload(service)
    assert store.bytes == b""
    assert journal.state == "open"
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_uncertain_commit_preserves_canonical_and_published_record(tmp_path):
    service, journal, store, session, events = setup(tmp_path)
    session.commit.side_effect = RuntimeError("commit response lost")
    with pytest.raises(RuntimeError, match="commit"):
        await upload(service)
    assert store.canonical is not None
    assert journal.state == "published"
    assert "discard" not in events


@pytest.mark.asyncio
async def test_job_failure_rolls_back_before_owned_file_cleanup(tmp_path):
    service, journal, store, session, events = setup(tmp_path, failing_jobs=True)
    with pytest.raises(RuntimeError, match="database"):
        await upload(service)
    assert events[-3:] == ["rollback", "discard", "abandoned"]
    assert store.canonical is None
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_failure_leaves_discarding_fence(tmp_path):
    service, journal, store, session, events = setup(tmp_path, failing_jobs=True)
    store.fail_discard = True
    with pytest.raises(RuntimeError, match="database"):
        await upload(service)
    assert journal.state == "discarding"
    assert store.canonical is not None


@pytest.mark.asyncio
async def test_already_attached_attempt_never_reaches_discard(tmp_path):
    service, journal, store, session, events = setup(tmp_path)
    journal.attached_during_prepare = True
    with pytest.raises(AppError) as exc:
        await upload(service)
    assert exc.value.code == "original_upload_unavailable"
    assert "discard" not in events
    assert store.canonical is not None


@pytest.mark.asyncio
async def test_rollback_failure_never_starts_file_cleanup(tmp_path):
    service, journal, store, session, events = setup(tmp_path, failing_jobs=True)
    session.rollback.side_effect = RuntimeError("rollback unknown")
    with pytest.raises(RuntimeError, match="database"):
        await upload(service)
    assert store.canonical is not None
    assert "discard" not in events


@pytest.mark.asyncio
async def test_publication_record_failure_preserves_file(tmp_path):
    service, journal, store, session, events = setup(tmp_path)
    journal.fail_published = True
    with pytest.raises(RuntimeError, match="publication"):
        await upload(service)
    assert store.canonical is not None
    assert "discard" not in events


@pytest.mark.asyncio
async def test_current_permission_failure_abandons_only_after_rollback(tmp_path):
    service, journal, store, session, events = setup(tmp_path)
    journal.fail_prepare = True
    with pytest.raises(AppError):
        await upload(service)
    assert events[-3:] == ["rollback", "discard", "abandoned"]


@pytest.mark.asyncio
async def test_new_version_keeps_planned_id_and_uses_max_number(tmp_path):
    service, journal, store, session, events = setup(tmp_path)
    user = owner()
    document = Document.create(workspace_id=uuid4(), folder_id=None, name="old.txt")
    v = document.new_version(object_key="old", sha256="b" * 64, media_type="text/plain", size=1)
    document.versions = [replace(v, number=7)]
    journal.repository.saved = document
    result = await service.upload_version(
        user=user,
        document_id=document.id,
        filename="new.txt",
        media_type="text/plain",
        content=content(),
    )
    assert result.document.versions[-1].number == 8
    assert journal.claim is not None
    assert result.document.versions[-1].id == journal.claim.source.asset_version_id


@pytest.mark.asyncio
async def test_stream_cancel_without_file_is_recorded_abandoned(tmp_path):
    import asyncio

    service, journal, store, session, events = setup(tmp_path)

    async def cancelled():
        yield b"a"
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await service.upload(
            user=owner(),
            workspace_id=uuid4(),
            folder_id=None,
            filename="a.txt",
            media_type="text/plain",
            content=cancelled(),
        )
    assert journal.state == "abandoned"
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_oversize_stream_is_rejected_before_publication(tmp_path):
    service, journal, store, session, events = setup(tmp_path)

    async def oversized():
        yield b"a" * 11

    with pytest.raises(AppError) as exc:
        await service.upload(
            user=owner(),
            workspace_id=uuid4(),
            folder_id=None,
            filename="a.txt",
            media_type="text/plain",
            content=oversized(),
        )
    assert exc.value.code == "file_too_large"
    assert store.canonical is None
    assert journal.state == "abandoned"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "commit", "published", "abandon", "stored"])
async def test_http_intake_keeps_planned_identity_and_acknowledges_only_after_commit(
    tmp_path, failure
):
    from ai_workshop.platform.assets.intake_contracts import UploadIntakeClaim
    from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
    from ai_workshop.platform.assets.temporary_contracts import TemporaryBinding

    service, journal, store, session, events = setup(tmp_path)
    user = owner()
    planned = UploadIntakeClaim(
        uuid4(),
        SourceIdentity(uuid4(), uuid4(), uuid4()),
        user.id,
        True,
        TemporaryBinding("intake_test", uuid4()),
    )

    class Intake:
        claim = planned
        uncertain = False

        async def reserve_original(self, original):
            await journal.reserve(original)

        async def prepare_attachment(self, session, original):
            events.append("intake_prepare")

        async def attach(self, session, original):
            events.append("intake_attach")
            return planned

        def acknowledge(self, pending):
            events.append("intake_ack")

        def mark_uncertain(self):
            self.uncertain = True

    intake = Intake()
    if failure == "commit":
        session.commit.side_effect = RuntimeError("lost response")
    elif failure == "published":
        journal.fail_published = True
    elif failure == "abandon":
        store.publish = AsyncMock(side_effect=RuntimeError("writer failed"))
        journal.cleanup = AsyncMock(side_effect=RuntimeError("cleanup commit lost"))
    elif failure == "stored":
        store.publish = AsyncMock(return_value=StoredObject("foreign", 5, "a" * 64))
    if failure:
        with pytest.raises((RuntimeError, UploadOwnershipError)):
            await service.upload_intake(
                user=user,
                intake=intake,
                filename="test.txt",
                media_type="text/plain",
                folder_id=None,
                content=content(),
            )
        assert intake.uncertain
        assert "intake_ack" not in events
        return
    result = await service.upload_intake(
        user=user,
        intake=intake,
        filename="test.txt",
        media_type="text/plain",
        folder_id=None,
        content=content(),
    )
    assert result.document.id == planned.source.document_id
    assert result.document.versions[0].id == planned.source.asset_version_id
    assert events[-5:] == ["intake_prepare", "attach", "intake_attach", "commit", "intake_ack"]
