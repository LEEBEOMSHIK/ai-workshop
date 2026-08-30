import hashlib
import json
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
    case_id = uuid4()
    evidence_id = uuid4()
    query = "dispatch recovery"
    query_hash = hashlib.sha256(query.encode()).hexdigest()
    document_snapshot = [
        {
            "document_id": str(uuid4()),
            "asset_version_id": str(uuid4()),
            "sha256": "a" * 64,
            "active": True,
        }
    ]
    scenario = {
        "name": "dispatch",
        "actor": "caller",
        "workspace_ids": [str(uuid4())],
        "folder_ids": [],
        "authorized_source_ids": [str(evidence_id)],
        "forbidden_source_ids": [],
        "as_of": "2026-08-31T00:00:00Z",
    }
    raw_case = {
        "id": str(case_id),
        "kind": "dispatch",
        "query": query,
        "query_sha256": query_hash,
        "permission_scenario": scenario,
        "expected": {
            "answer_status": "supported",
            "evidence_unit_ids": [str(evidence_id)],
            "highlight": None,
        },
    }
    fixture = {
        "schema_version": 1,
        "id": str(dataset_id),
        "name": "dispatch",
        "version": 1,
        "document_snapshot": document_snapshot,
        "cases": [raw_case],
    }
    canonical = lambda value: json.dumps(  # noqa: E731
        value, sort_keys=True, separators=(",", ":")
    ).encode()
    fixture_bytes = canonical(fixture)
    document_bytes = canonical(document_snapshot)
    query_set_bytes = canonical(
        [
            {
                "id": str(case_id),
                "query_sha256": query_hash,
                "permission_scenario": "dispatch",
            }
        ]
    )
    case_bytes = canonical(raw_case)
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
                document_snapshot, document_snapshot_bytes,
                document_snapshot_sha256, query_set_bytes,
                query_set_sha256, case_count, id
            ) VALUES (%s, 'dispatch', 1, %s, %s, %s::jsonb, %s, %s, %s, %s, 1, %s)
            """,
            (
                owner_id,
                fixture_bytes,
                hashlib.sha256(fixture_bytes).hexdigest(),
                json.dumps(document_snapshot),
                document_bytes,
                hashlib.sha256(document_bytes).hexdigest(),
                query_set_bytes,
                hashlib.sha256(query_set_bytes).hexdigest(),
                dataset_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO rag_evaluation_dataset_cases (
                dataset_snapshot_id, ordinal, canonical_case_bytes,
                canonical_case_sha256, query_bytes, query_sha256,
                permission_scenario, expected_evidence_ids,
                authorized_source_ids, forbidden_source_ids,
                expected_highlight, id
            ) VALUES (%s, 0, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                      %s::jsonb, '[]'::jsonb, 'null'::jsonb, %s)
            """,
            (
                dataset_id,
                case_bytes,
                hashlib.sha256(case_bytes).hexdigest(),
                query.encode(),
                query_hash,
                json.dumps(scenario),
                json.dumps([str(evidence_id)]),
                json.dumps([str(evidence_id)]),
                case_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO rag_evaluation_runs (
                owner_id, dataset_snapshot_id, evaluation_policy_version_id,
                status, fixture_sha256, document_snapshot_sha256,
                query_set_sha256, execution_snapshot,
                execution_snapshot_bytes, execution_snapshot_sha256,
                runtime_environment,
                metric_definition_version, retrieval_k,
                repetition_count, candidate_count, id
            ) VALUES (%s, %s, NULL, 'pending', %s, %s, %s,
                      '{}'::jsonb, '{}'::bytea,
                      '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a',
                      '{"runtime":"test"}', 1, 10, 2, 1, %s)
            """,
            (
                owner_id,
                dataset_id,
                hashlib.sha256(fixture_bytes).hexdigest(),
                hashlib.sha256(document_bytes).hexdigest(),
                hashlib.sha256(query_set_bytes).hexdigest(),
                run_id,
            ),
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

                worker_lost_at = retry_at + timedelta(minutes=31)
                reclaimed_after_worker_loss = await repository.claim_ready(
                    now=worker_lost_at,
                    stale_before=worker_lost_at - timedelta(minutes=30),
                    limit=10,
                )
                assert len(reclaimed_after_worker_loss) == 1
                assert reclaimed_after_worker_loss[0].run_id == run_id
                assert reclaimed_after_worker_loss[0].attempt_count == 4
                concurrent_empty = await repository.claim_ready(
                    now=worker_lost_at,
                    stale_before=worker_lost_at - timedelta(minutes=30),
                    limit=10,
                )
                assert concurrent_empty == ()
                await repository.mark_sent(
                    reclaimed_after_worker_loss[0], now=worker_lost_at
                )
            finally:
                await engine.dispose()
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
