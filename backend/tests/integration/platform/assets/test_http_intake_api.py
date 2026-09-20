"""ASGI intake contract coverage without production DB, storage or queue services."""

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import BinaryIO, cast
from uuid import UUID, uuid4

import pytest
import starlette.formparsers
from fastapi import FastAPI
from starlette.types import Message, Scope

from ai_workshop.platform.assets.api import router
from ai_workshop.platform.assets.domain import Document
from ai_workshop.platform.assets.intake_contracts import UploadIntakeClaim
from ai_workshop.platform.assets.intake_repository import UploadIntakeJournal
from ai_workshop.platform.assets.intake_service import (
    HttpUploadIntakeService,
    UploadIntakeLease,
    get_upload_intake_service,
)
from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.service import AssetUploadResult
from ai_workshop.platform.assets.temporary_contracts import TemporaryBinding
from ai_workshop.platform.assets.temporary_service import TemporaryWorkspace
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.jobs.domain import Job, JobType
from ai_workshop.shared.errors import AppError, register_error_handlers
from ai_workshop.worker import get_job_dispatcher


class Payload:
    def __init__(self, path: Path, events: list[str]) -> None:
        self.path, self.events = path, events
        self.handles: list[BinaryIO] = []

    def open(self, mode: str) -> BinaryIO:
        self.events.append(mode)
        handle = cast(BinaryIO, self.path.open(mode))
        self.handles.append(handle)
        return handle


class Workspace:
    def __init__(self, root: Path, events: list[str]) -> None:
        self.root, self.events = root, events
        self.payload = Payload(root / "payload.bin", events)

    def create_file(self, name: str) -> Path:
        assert name == "payload.bin"
        self.events.append("allocate")
        self.payload.path.touch(exist_ok=False)
        return cast(Path, self.payload)

    def discard(self) -> None:
        assert self.payload.handles and all(handle.closed for handle in self.payload.handles)
        self.events.append("discard")
        self.payload.path.unlink()

    def close(self) -> None:
        self.events.append("release")


class Store:
    def __init__(self, workspace: Workspace, binding: TemporaryBinding) -> None:
        self.workspace, self.binding = workspace, binding

    def create(self, claim: UploadIntakeClaim) -> TemporaryWorkspace:
        assert claim.binding == self.binding
        self.workspace.events.append("create")
        return self.workspace

    def observe(self, claim: UploadIntakeClaim) -> bool:
        self.workspace.events.append("observe")
        return self.workspace.payload.path.exists()


class Journal:
    def __init__(self, events: list[str], workspace: Workspace) -> None:
        self.events, self.workspace = events, workspace
        self.failure: Exception | None = None
        self.cleanup_failure = False
        self.claim: UploadIntakeClaim | None = None

    async def reserve(
        self,
        *,
        user_id: UUID,
        workspace_id: UUID | None,
        document_id: UUID | None,
        binding: TemporaryBinding,
    ) -> UploadIntakeClaim:
        self.events.append("reserve")
        if self.failure:
            raise self.failure
        self.claim = UploadIntakeClaim(
            uuid4(),
            SourceIdentity(workspace_id or uuid4(), document_id or uuid4(), uuid4()),
            user_id,
            document_id is None,
            binding,
            generation=1 if document_id else None,
        )
        self.events.append("reserved")
        return self.claim

    async def transition(
        self, claim: UploadIntakeClaim, *, expected_state: str
    ) -> UploadIntakeClaim:
        assert all(handle.closed for handle in self.workspace.payload.handles)
        self.events.append(expected_state)
        if self.cleanup_failure:
            raise RuntimeError("synthetic-private-cleanup")
        self.claim = replace(
            claim,
            state={"open": "closed", "closed": "cleaning", "cleaning": "cleaned"}[expected_state],
            revision=claim.revision + 1,
        )
        return self.claim


class Coordinator:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.cancel = False
        self.job_created = True
        self.received: tuple[str, str, UUID | None, bytes] | None = None
        self.result: AssetUploadResult | None = None

    async def upload_intake(
        self,
        *,
        user: User,
        intake: UploadIntakeLease,
        filename: str,
        media_type: str,
        folder_id: UUID | None,
        content: AsyncIterator[bytes],
    ) -> AssetUploadResult:
        self.events.append("coordinate")
        data = bytearray()
        async for chunk in content:
            data.extend(chunk)
            if self.cancel:
                raise asyncio.CancelledError()
        self.received = filename, media_type, folder_id, bytes(data)
        source = intake.claim.source
        document = Document(source.document_id, source.workspace_id, folder_id, filename)
        version = document.new_version(
            object_key="synthetic",
            sha256="a" * 64,
            media_type=media_type,
            size=len(data),
            version_id=source.asset_version_id,
        )
        job = Job.create(
            user_id=user.id,
            workspace_id=source.workspace_id,
            asset_version_id=version.id,
            type=JobType.VERIFY_ASSET,
            idempotency_key="synthetic-intake",
        )
        self.result = AssetUploadResult(document, job, self.job_created)
        return self.result


@dataclass
class Dispatcher:
    jobs: list[UUID] = field(default_factory=list)

    async def verify_asset(self, job_id: UUID) -> None:
        self.jobs.append(job_id)


@dataclass
class Harness:
    app: FastAPI
    events: list[str]
    journal: Journal
    workspace: Workspace
    coordinator: Coordinator
    dispatcher: Dispatcher
    user: User


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    def forbidden_spool(*args: object, **kwargs: object) -> None:
        pytest.fail("HTTP intake must not invoke an untracked spool allocator.")

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", forbidden_spool)
    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", forbidden_spool)
    events: list[str] = []
    workspace = Workspace(tmp_path, events)
    journal = Journal(events, workspace)
    coordinator, dispatcher = Coordinator(events), Dispatcher()
    store = Store(workspace, TemporaryBinding("synthetic_intake", uuid4()))
    service = HttpUploadIntakeService(cast(UploadIntakeJournal, journal), store, coordinator)
    user = User.create_owner(
        display_name="Synthetic", email="synthetic@example.test", password_hash="unused"
    )
    app = FastAPI()
    app.include_router(router)
    register_error_handlers(app)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_upload_intake_service] = lambda: service
    app.dependency_overrides[get_job_dispatcher] = lambda: dispatcher
    return Harness(app, events, journal, workspace, coordinator, dispatcher, user)


def path(new_document: bool) -> str:
    return (
        f"/api/v1/workspaces/{uuid4()}/documents"
        if new_document
        else f"/api/v1/documents/{uuid4()}/versions"
    )


def multipart(folder: UUID | None = None) -> bytes:
    data = (
        b'--intake\r\nContent-Disposition: form-data; name="file"; filename="sample.txt"'
        b"\r\nContent-Type: text/plain\r\n\r\nhello\r\n"
    )
    if folder:
        data += (
            b'--intake\r\nContent-Disposition: form-data; name="folder_id"\r\n\r\n'
            + str(folder).encode()
            + b"\r\n"
        )
    return data + b"--intake--\r\n"


async def request(
    harness: Harness, url: str, payload: bytes, *, cancel_receive: bool = False
) -> tuple[int, dict[str, object]]:
    messages: list[Message] = []
    sent = False

    async def receive() -> Message:
        nonlocal sent
        harness.events.append("receive")
        if cancel_receive:
            raise asyncio.CancelledError()
        assert not sent
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message: Message) -> None:
        messages.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": url,
        "raw_path": url.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"multipart/form-data; boundary=intake")],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    await harness.app(scope, receive, send)
    status = next(
        message["status"] for message in messages if message["type"] == "http.response.start"
    )
    response = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return status, json.loads(response)


@pytest.mark.parametrize("new_document", [True, False])
async def test_unauthorized_route_reads_zero_request_bytes(
    harness: Harness, new_document: bool
) -> None:
    async def unauthorized() -> User:
        raise AppError("unauthorized", "Authentication required.", 401)

    harness.app.dependency_overrides[get_current_user] = unauthorized
    status, _ = await request(harness, path(new_document), multipart())
    assert status == 401
    assert harness.events == []
    assert not harness.dispatcher.jobs


@pytest.mark.parametrize(
    "failure,status",
    [
        (AppError("forbidden", "Permission denied.", 403), 403),
        (RuntimeError("synthetic-private-unknown-commit"), 503),
    ],
)
@pytest.mark.parametrize("new_document", [True, False])
async def test_reservation_rejection_or_unknown_commit_consumes_zero_bytes(
    harness: Harness, failure: Exception, status: int, new_document: bool
) -> None:
    harness.journal.failure = failure
    actual, response = await request(harness, path(new_document), multipart())
    assert actual == status
    assert "synthetic-private" not in str(response)
    assert harness.events == ["reserve"]
    assert not harness.workspace.payload.path.exists()


@pytest.mark.parametrize("new_document", [True, False])
@pytest.mark.parametrize("job_created", [True, False])
async def test_real_intake_parser_preserves_response_and_conditional_dispatch(
    harness: Harness, new_document: bool, job_created: bool
) -> None:
    folder = uuid4() if new_document else None
    harness.coordinator.job_created = job_created
    status, response = await request(harness, path(new_document), multipart(folder))
    assert status == 201
    assert harness.coordinator.received == ("sample.txt", "text/plain", folder, b"hello")
    result = harness.coordinator.result
    assert result is not None
    assert response["id"] == str(result.document.id)
    assert response["job_id"] == str(result.job.id)
    assert response["folder_id"] == (str(folder) if folder else None)
    assert harness.dispatcher.jobs == ([result.job.id] if job_created else [])
    assert (
        harness.events.index("reserved")
        < harness.events.index("create")
        < harness.events.index("receive")
    )
    assert harness.events[-6:] == ["open", "closed", "discard", "observe", "cleaning", "release"]
    assert all(handle.closed for handle in harness.workspace.payload.handles)
    assert not harness.workspace.payload.path.exists()


@pytest.mark.parametrize(
    "payload", [b"malformed", multipart()[:-5], multipart() + b"private-extra"]
)
async def test_malformed_upload_closes_writer_and_cleans_without_dispatch(
    harness: Harness, payload: bytes
) -> None:
    status, _ = await request(harness, path(True), payload)
    assert status == 422
    assert harness.coordinator.result is None
    assert not harness.dispatcher.jobs
    assert all(handle.closed for handle in harness.workspace.payload.handles)
    assert "discard" in harness.events
    assert not harness.workspace.payload.path.exists()


@pytest.mark.parametrize("during_read", [True, False])
async def test_cancelled_receive_or_coordinator_closes_writer_and_reader_before_cleanup(
    harness: Harness, during_read: bool
) -> None:
    harness.coordinator.cancel = not during_read
    with pytest.raises(asyncio.CancelledError):
        await request(harness, path(True), multipart(), cancel_receive=during_read)
    assert all(handle.closed for handle in harness.workspace.payload.handles)
    assert len(harness.workspace.payload.handles) == (1 if during_read else 2)
    assert "discard" in harness.events
    assert not harness.workspace.payload.path.exists()
    assert not harness.dispatcher.jobs


async def test_cleanup_failure_preserves_201_and_one_dispatch(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    harness.journal.cleanup_failure = True
    status, _ = await request(harness, path(True), multipart())
    assert status == 201
    assert len(harness.dispatcher.jobs) == 1
    assert "discard" not in harness.events
    assert harness.workspace.payload.path.exists()
    assert all(handle.closed for handle in harness.workspace.payload.handles)
    assert "synthetic-private" not in caplog.text
