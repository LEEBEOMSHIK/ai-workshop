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
from ai_workshop.labs.rag.evaluation.dispatch import (
    EvaluationDispatchClaim,
    EvaluationDispatchReconciler,
)
from ai_workshop.labs.rag.evaluation.models import EvaluationDispatchRecord
from ai_workshop.labs.rag.evaluation.repository import (
    EvaluationDispatchClaimLostError,
    SqlAlchemyEvaluationDispatchRepository,
)
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


def _seed_run(database_url: str) -> UUID:
    owner_id = uuid4()
    dataset_id = uuid4()
    run_id = uuid4()
    email = f"evaluation-dispatch-{owner_id}@example.test"
    with psycopg.connect(_sync_url(database_url)) as connection:
        connection.execute(
            """
            INSERT INTO users (
                display_name, email, normalized_email, password_hash,
                role, is_active, id
            ) VALUES ('Evaluation Dispatch', %s, %s, 'fixture-hash', 'owner', true, %s)
            """,
            (email, email, owner_id),
        )
        connection.execute(
            """
            INSERT INTO rag_evaluation_datasets (
                owner_id, name, version, fixture_bytes, fixture_sha256,
                document_snapshot, document_snapshot_sha256,
                query_set_sha256, case_count, id
            ) VALUES (%s, 'dispatch', 1, '{}'::bytea, %s,
                      '[{"asset_version_id":"synthetic"}]', %s, %s, 1, %s)
            """,
            (owner_id, "1" * 64, "2" * 64, "3" * 64, dataset_id),
        )
        connection.execute(
            """
            INSERT INTO rag_evaluation_runs (
                owner_id, dataset_snapshot_id, evaluation_policy_version_id,
                status, fixture_sha256, document_snapshot_sha256,
                query_set_sha256, runtime_environment,
                repetition_count, candidate_count, id
            ) VALUES (%s, %s, NULL, 'pending', %s, %s, %s,
                      '{"runtime":"test"}', 2, 1, %s)
            """,
            (owner_id, dataset_id, "1" * 64, "2" * 64, "3" * 64, run_id),
        )
        connection.execute(
            "INSERT INTO rag_evaluation_dispatches (run_id) VALUES (%s)",
            (run_id,),
        )
    return run_id


class FailOnceUnlockedSender:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.calls: list[UUID] = []

    def send(self, run_id: UUID) -> None:
        with psycopg.connect(_sync_url(self.database_url), autocommit=True) as connection:
            row = connection.execute(
                """
                SELECT status FROM rag_evaluation_dispatches
                WHERE run_id = %s FOR UPDATE NOWAIT
                """,
                (run_id,),
            ).fetchone()
        assert row == ("claimed",)
        self.calls.append(run_id)
        if len(self.calls) == 1:
            raise OSError("broker unavailable")


@pytest.mark.asyncio
async def test_evaluation_dispatch_is_token_fenced_and_recovers_broker_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t11_dispatch_{uuid4().hex}"
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
            run_id = _seed_run(isolated_url)
            settings = Settings(
                _env_file=None,
                secret_key="x" * 32,
                database_url=isolated_url,
            )
            engine = create_engine(settings)
            sessions = create_session_factory(engine)
            try:
                repository = SqlAlchemyEvaluationDispatchRepository(sessions)
                now = datetime.now(UTC) + timedelta(seconds=1)
                first, second = await gather(
                    repository.claim_ready(
                        now=now, stale_before=now - timedelta(minutes=2), limit=1
                    ),
                    repository.claim_ready(
                        now=now, stale_before=now - timedelta(minutes=2), limit=1
                    ),
                )
                claims = (*first, *second)
                assert len(claims) == 1
                assert claims[0].run_id == run_id

                with pytest.raises(EvaluationDispatchClaimLostError):
                    await repository.mark_sent(
                        EvaluationDispatchClaim(run_id, uuid4(), 1), now=now
                    )
                await repository.mark_failed(
                    claims[0], now=now, retry_at=now, error="reset"
                )

                sender = FailOnceUnlockedSender(isolated_url)
                reconciler = EvaluationDispatchReconciler(repository, sender)
                failed = await reconciler.run_once(now=now)
                assert (failed.claimed, failed.sent, failed.failed) == (1, 0, 1)

                async with sessions() as session:
                    pending = await session.get(EvaluationDispatchRecord, run_id)
                    assert pending is not None
                    assert pending.status == "pending"
                    assert pending.attempt_count == 2
                    retry_at = pending.available_at

                recovered = await reconciler.run_once(now=retry_at)
                assert (recovered.claimed, recovered.sent, recovered.failed) == (1, 1, 0)
                assert sender.calls == [run_id, run_id]
            finally:
                await engine.dispose()
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
