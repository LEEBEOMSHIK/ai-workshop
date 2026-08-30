from asyncio import gather, to_thread
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.configurations.domain import E5_INDEXING_PROFILE_ID
from ai_workshop.labs.rag.ingestion.dispatch import (
    DispatchClaim,
    RagDispatchReconciler,
)
from ai_workshop.labs.rag.ingestion.domain import EnsureIndexedCommand
from ai_workshop.labs.rag.ingestion.models import RagIngestionDispatchRecord
from ai_workshop.labs.rag.ingestion.repository import (
    DispatchClaimLostError,
    SqlAlchemyRagDispatchRepository,
    SqlAlchemyRagIngestionCommandRepository,
)
from ai_workshop.labs.rag.ingestion.service import RagIngestionService
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.shared.db import create_engine, create_session_factory
from alembic import command

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[5]


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _create_database(base_url: str, database: str) -> None:
    administrative = _database_url(base_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))


def _drop_database(base_url: str, database: str) -> None:
    administrative = _database_url(base_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
        )


def _seed_asset(database_url: str) -> tuple[UUID, UUID]:
    user_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    asset_version_id = uuid4()
    email = f"dispatch-{user_id}@example.test"
    with psycopg.connect(_sync_url(database_url)) as connection:
        connection.execute(
            """
            INSERT INTO users (
                display_name, email, normalized_email, password_hash,
                role, is_active, id
            ) VALUES ('Dispatch Owner', %s, %s, 'fixture-hash', 'owner', true, %s)
            """,
            (email, email, user_id),
        )
        connection.execute(
            """
            INSERT INTO workspaces (name, kind, created_by, expires_at, id)
            VALUES (%s, 'private', %s, NULL, %s)
            """,
            (f"Dispatch {workspace_id}", user_id, workspace_id),
        )
        connection.execute(
            """
            INSERT INTO documents (
                workspace_id, folder_id, name, active_version_id, id
            ) VALUES (%s, NULL, %s, NULL, %s)
            """,
            (workspace_id, f"dispatch-{document_id}.txt", document_id),
        )
        connection.execute(
            """
            INSERT INTO asset_versions (
                document_id, number, object_key, sha256,
                media_type, size, status, id
            ) VALUES (%s, 1, %s, %s, 'text/plain', 1, 'verified', %s)
            """,
            (document_id, f"dispatch/{asset_version_id}.txt", "a" * 64, asset_version_id),
        )
    return user_id, asset_version_id


class FailOnceUnlockedSender:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.calls: list[UUID] = []

    def send(self, job_id: UUID) -> None:
        with psycopg.connect(_sync_url(self.database_url), autocommit=True) as connection:
            row = connection.execute(
                """
                SELECT status FROM rag_ingestion_dispatches
                WHERE job_id = %s
                FOR UPDATE NOWAIT
                """,
                (job_id,),
            ).fetchone()
        assert row == ("claimed",)
        self.calls.append(job_id)
        if len(self.calls) == 1:
            raise OSError("broker unavailable")


@pytest.mark.asyncio
async def test_postgres_outbox_is_atomic_claimed_safely_and_recovers_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t10_dispatch_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            await to_thread(
                command.upgrade,
                Config(str(BACKEND_ROOT / "alembic.ini")),
                "head",
            )
            user_id, asset_version_id = _seed_asset(isolated_url)
            settings = Settings(
                _env_file=None,
                secret_key="x" * 32,
                database_url=isolated_url,
            )
            engine = create_engine(settings)
            sessions = create_session_factory(engine)
            command_payload = EnsureIndexedCommand(
                asset_version_id,
                E5_INDEXING_PROFILE_ID,
                user_id,
            )
            try:
                async with sessions() as session:
                    transaction = await session.begin()
                    rolled_back_job_id = await RagIngestionService(
                        SqlAlchemyRagIngestionCommandRepository(session)
                    ).ensure_indexed(command_payload)
                    await session.flush()
                    assert (
                        await session.get(
                            RagIngestionDispatchRecord,
                            rolled_back_job_id,
                        )
                        is not None
                    )
                    await transaction.rollback()

                async with sessions() as session:
                    assert await session.get(JobRecord, rolled_back_job_id) is None
                    assert (
                        await session.get(
                            RagIngestionDispatchRecord,
                            rolled_back_job_id,
                        )
                        is None
                    )

                async with sessions.begin() as session:
                    job_id = await RagIngestionService(
                        SqlAlchemyRagIngestionCommandRepository(session)
                    ).ensure_indexed(command_payload)

                dispatch_repository = SqlAlchemyRagDispatchRepository(sessions)
                now = datetime.now(UTC) + timedelta(seconds=1)
                first, second = await gather(
                    dispatch_repository.claim_ready(
                        now=now,
                        stale_before=now - timedelta(minutes=2),
                        limit=1,
                    ),
                    dispatch_repository.claim_ready(
                        now=now,
                        stale_before=now - timedelta(minutes=2),
                        limit=1,
                    ),
                )
                claims = (*first, *second)
                assert len(claims) == 1
                assert claims[0].job_id == job_id

                with pytest.raises(DispatchClaimLostError):
                    await dispatch_repository.mark_sent(
                        DispatchClaim(job_id, uuid4(), claims[0].attempt_count),
                        now=now,
                    )
                with psycopg.connect(
                    _sync_url(isolated_url), autocommit=True
                ) as connection:
                    connection.execute(
                        """
                        UPDATE rag_ingestion_dispatches
                        SET claimed_at = %s
                        WHERE job_id = %s
                        """,
                        (now - timedelta(minutes=3), job_id),
                    )
                reclaimed = await dispatch_repository.claim_ready(
                    now=now,
                    stale_before=now - timedelta(minutes=2),
                    limit=1,
                )
                assert len(reclaimed) == 1
                assert reclaimed[0].claim_token != claims[0].claim_token
                with pytest.raises(DispatchClaimLostError):
                    await dispatch_repository.mark_sent(claims[0], now=now)
                await dispatch_repository.mark_failed(
                    reclaimed[0],
                    now=now,
                    retry_at=now,
                    error="reset after token test",
                )

                sender = FailOnceUnlockedSender(isolated_url)
                reconciler = RagDispatchReconciler(
                    dispatch_repository,
                    sender,
                    base_backoff=timedelta(seconds=5),
                )
                failed = await reconciler.run_once(now=now)
                assert failed.failed == 1

                async with sessions() as session:
                    pending = await session.get(RagIngestionDispatchRecord, job_id)
                    assert pending is not None
                    assert pending.status == "pending"
                    assert pending.attempt_count == 3
                    assert pending.last_error == "broker unavailable"
                    retry_at = pending.available_at

                recovered = await reconciler.run_once(now=retry_at)
                assert recovered.sent == 1
                async with sessions() as session:
                    sent = await session.get(RagIngestionDispatchRecord, job_id)
                    assert sent is not None
                    assert sent.status == "sent"
                    assert sent.sent_at == retry_at
                assert sender.calls == [job_id, job_id]
            finally:
                await engine.dispose()
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
