from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.infrastructure.document_formats.pdf_preview import (
    PdfInspection,
    RenderedPdfPage,
)
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.originals import (
    OriginalService,
    SqlAlchemyOriginalRepository,
)
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.domain import MembershipRole, WorkspaceKind
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@pytest.fixture
def isolated_original_database(
    monkeypatch: pytest.MonkeyPatch,
) -> IsolatedPublishingDatabase:
    with isolated_publishing_database(monkeypatch) as database:
        command.upgrade(database.config, "head")
        yield database


@dataclass(frozen=True, slots=True)
class OriginalSeed:
    user: User
    foreign_user_id: UUID
    workspace_id: UUID
    document_id: UUID
    ready_version_id: UUID
    processing_version_id: UUID
    object_key: str
    content: bytes


async def seed_original(database_url: str) -> OriginalSeed:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, foreign_user_id = uuid4(), uuid4()
    workspace_id, document_id = uuid4(), uuid4()
    ready_version_id, processing_version_id = uuid4(), uuid4()
    content = b"\xef\xbb\xbf" + "합성 문서\n안녕하세요".encode()
    object_key = f"synthetic/{document_id}/historic.txt"
    try:
        async with sessions.begin() as session:
            session.add_all(
                [
                    UserRecord(
                        id=user_id,
                        display_name="Original member",
                        email=f"original-{user_id}@example.test",
                        normalized_email=f"original-{user_id}@example.test",
                        password_hash="synthetic-password-hash",
                        role=UserRole.MEMBER,
                        is_active=True,
                    ),
                    UserRecord(
                        id=foreign_user_id,
                        display_name="Foreign member",
                        email=f"foreign-{foreign_user_id}@example.test",
                        normalized_email=f"foreign-{foreign_user_id}@example.test",
                        password_hash="synthetic-password-hash",
                        role=UserRole.MEMBER,
                        is_active=True,
                    ),
                ]
            )
            await session.flush()
            session.add(
                WorkspaceRecord(
                    id=workspace_id,
                    name="Synthetic originals",
                    kind=WorkspaceKind.TEMPORARY,
                    created_by=user_id,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            await session.flush()
            session.add(
                WorkspaceMembershipRecord(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    role=MembershipRole.MEMBER,
                )
            )
            await session.flush()
            session.add(
                DocumentRecord(
                    id=document_id,
                    workspace_id=workspace_id,
                    folder_id=None,
                    name="current-name.md",
                    active_version_id=ready_version_id,
                )
            )
            await session.flush()
            session.add_all(
                [
                    AssetVersionRecord(
                        id=ready_version_id,
                        document_id=document_id,
                        number=1,
                        object_key=object_key,
                        sha256=sha256(content).hexdigest(),
                        media_type="application/pdf",
                        size=len(content),
                        status=VersionStatus.READY,
                    ),
                    AssetVersionRecord(
                        id=processing_version_id,
                        document_id=document_id,
                        number=2,
                        object_key=f"synthetic/{document_id}/latest.pdf",
                        sha256="1" * 64,
                        media_type="application/pdf",
                        size=1,
                        status=VersionStatus.PROCESSING,
                    ),
                ]
            )
    finally:
        await engine.dispose()
    return OriginalSeed(
        user=User(
            id=user_id,
            display_name="Original member",
            email=f"original-{user_id}@example.test",
            normalized_email=f"original-{user_id}@example.test",
            password_hash="synthetic-password-hash",
            role=UserRole.MEMBER,
        ),
        foreign_user_id=foreign_user_id,
        workspace_id=workspace_id,
        document_id=document_id,
        ready_version_id=ready_version_id,
        processing_version_id=processing_version_id,
        object_key=object_key,
        content=content,
    )


class RaceObjectStore:
    def __init__(
        self,
        key: str,
        content: bytes,
        after_read: Callable[[], Awaitable[None]],
    ) -> None:
        self.key = key
        self.content = content
        self.after_read = after_read

    async def put(self, key: str, source: AsyncIterator[bytes]) -> object:
        del key, source
        raise AssertionError("original reads never write")

    async def open(self, key: str) -> AsyncIterator[bytes]:
        assert key == self.key
        yield self.content
        await self.after_read()

    async def delete(self, key: str) -> None:
        del key
        raise AssertionError("original reads never delete")


class NeverPdfRenderer:
    async def inspect(self, content: bytes) -> PdfInspection:
        del content
        raise AssertionError("text preview never inspects PDF")

    async def render_page(self, content: bytes, page_number: int) -> RenderedPdfPage:
        del content, page_number
        raise AssertionError("text preview never renders PDF")


@pytest.mark.asyncio
async def test_exact_historic_version_query_scopes_document_member_expiry_and_status(
    isolated_original_database: IsolatedPublishingDatabase,
) -> None:
    seed = await seed_original(isolated_original_database.database_url)
    engine = create_async_engine(isolated_original_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            repository = SqlAlchemyOriginalRepository(session)
            exact = await repository.resolve(
                user_id=seed.user.id,
                document_id=seed.document_id,
                version_id=seed.ready_version_id,
            )
            mismatched_document = await repository.resolve(
                user_id=seed.user.id,
                document_id=uuid4(),
                version_id=seed.ready_version_id,
            )
            foreign = await repository.resolve(
                user_id=seed.foreign_user_id,
                document_id=seed.document_id,
                version_id=seed.ready_version_id,
            )
            processing = await repository.resolve(
                user_id=seed.user.id,
                document_id=seed.document_id,
                version_id=seed.processing_version_id,
            )

        assert exact is not None
        assert exact.asset_version_id == seed.ready_version_id
        assert exact.version == 1
        assert exact.object_key == seed.object_key
        assert exact.status is VersionStatus.READY
        assert mismatched_document is None
        assert foreign is None
        assert processing is not None
        assert processing.status is VersionStatus.PROCESSING
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("race", "expected_status"),
    [
        ("membership_removed", 404),
        ("workspace_expired", 404),
        ("version_not_ready", 409),
    ],
)
async def test_final_recheck_closes_authorization_and_ready_races(
    isolated_original_database: IsolatedPublishingDatabase,
    race: str,
    expected_status: int,
) -> None:
    seed = await seed_original(isolated_original_database.database_url)
    engine = create_async_engine(isolated_original_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def apply_race() -> None:
        async with sessions.begin() as race_session:
            if race == "membership_removed":
                await race_session.execute(
                    delete(WorkspaceMembershipRecord).where(
                        WorkspaceMembershipRecord.workspace_id == seed.workspace_id,
                        WorkspaceMembershipRecord.user_id == seed.user.id,
                    )
                )
            elif race == "workspace_expired":
                await race_session.execute(
                    update(WorkspaceRecord)
                    .where(WorkspaceRecord.id == seed.workspace_id)
                    .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
                )
            else:
                await race_session.execute(
                    update(AssetVersionRecord)
                    .where(AssetVersionRecord.id == seed.ready_version_id)
                    .values(status=VersionStatus.PROCESSING)
                )

    try:
        async with sessions() as session:
            held_version = await session.get(
                AssetVersionRecord,
                seed.ready_version_id,
            )
            assert held_version is not None
            service = OriginalService(
                SqlAlchemyOriginalRepository(session),
                RaceObjectStore(seed.object_key, seed.content, apply_race),
                NeverPdfRenderer(),
                original_max_bytes=1024,
                text_preview_max_bytes=1024,
            )
            with pytest.raises(AppError) as failure:
                await service.preview(
                    user=seed.user,
                    document_id=seed.document_id,
                    version_id=seed.ready_version_id,
                )

        assert failure.value.status_code == expected_status
    finally:
        await engine.dispose()
