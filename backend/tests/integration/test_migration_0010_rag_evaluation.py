import json
from asyncio import to_thread
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import make_url

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.configurations.domain import (
    BM25_BASELINE_CONFIGURATION_VERSION_ID,
)
from alembic import command

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REVISION_0009 = "0009_rag_configurations"
REVISION_0010 = "0010_rag_evaluation"
BGE_MODEL_ID = UUID("00000000-0000-0000-0000-000000000102")
BGE_INDEXING_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000204")
BGE_RETRIEVAL_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000205")


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


def _seed_qualifying_evidence(database_url: str) -> tuple[UUID, UUID]:
    owner_id = uuid4()
    dataset_id = uuid4()
    policy_id = uuid4()
    run_id = uuid4()
    candidate_id = uuid4()
    email = f"evaluation-{owner_id}@example.test"
    with psycopg.connect(_sync_url(database_url)) as connection:
        connection.execute(
            """
            INSERT INTO users (
                display_name, email, normalized_email, password_hash,
                role, is_active, id
            ) VALUES ('Evaluation Owner', %s, %s, 'fixture-hash', 'owner', true, %s)
            """,
            (email, email, owner_id),
        )
        connection.execute(
            """
            INSERT INTO rag_evaluation_datasets (
                owner_id, name, version, fixture_bytes, fixture_sha256,
                document_snapshot, document_snapshot_sha256,
                query_set_sha256, case_count, id
            ) VALUES (%s, 'Synthetic V1', 1, %s, %s, %s::jsonb, %s, %s, 12, %s)
            """,
            (
                owner_id,
                b'{"schema_version":1}',
                "1" * 64,
                json.dumps([{"asset_version_id": str(uuid4())}]),
                "2" * 64,
                "3" * 64,
                dataset_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO rag_evaluation_policies (
                owner_id, dataset_snapshot_id, version,
                min_recall_at_k, min_mrr, min_ndcg,
                min_supported_precision, max_false_grounding_rate,
                min_highlight_iou, max_p50_latency_ms, max_p95_latency_ms,
                max_access_leaks, required_reproducibility, id
            ) VALUES (%s, %s, 1, 0.6, 0.5, 0.55, 0.9, 0.1,
                      0.7, 500, 1000, 0, 1.0, %s)
            """,
            (owner_id, dataset_id, policy_id),
        )
        connection.execute(
            """
            INSERT INTO rag_evaluation_runs (
                owner_id, dataset_snapshot_id, evaluation_policy_version_id,
                status, fixture_sha256, document_snapshot_sha256,
                query_set_sha256, runtime_environment, repetition_count,
                candidate_count, finished_at, id
            ) VALUES (%s, %s, %s, 'completed', %s, %s, %s,
                      '{"python":"3.13","runtime":"test"}'::jsonb,
                      2, 1, now(), %s)
            """,
            (owner_id, dataset_id, policy_id, "1" * 64, "2" * 64, "3" * 64, run_id),
        )
        connection.execute(
            """
            INSERT INTO rag_evaluation_run_configurations (
                run_id, configuration_version_id, ordinal,
                indexing_profile_id, retrieval_profile_id,
                answer_policy_version_id, generation_profile_id,
                component_snapshot, status, failure,
                recall_at_k, mrr, ndcg, supported_precision,
                false_grounding_rate, highlight_iou,
                p50_latency_ms, p95_latency_ms,
                access_leaks, reproducibility, completed_at, id
            )
            SELECT %s, version.id, 0,
                   version.indexing_profile_id, version.retrieval_profile_id,
                   version.answer_policy_version_id, version.generation_profile_id,
                   '{"models":[]}'::jsonb, 'completed', NULL,
                   0.6, 0.5, 0.55, 0.9, 0.1, 0.7,
                   500, 1000, 0, 1.0, now(), %s
            FROM rag_configuration_versions AS version
            WHERE version.id = %s
            """,
            (run_id, candidate_id, BM25_BASELINE_CONFIGURATION_VERSION_ID),
        )
        for ordinal in range(12):
            connection.execute(
                """
                INSERT INTO rag_evaluation_case_results (
                    run_configuration_id, evaluation_case_id, ordinal,
                    query_sha256, permission_scenario, expected_evidence_ids,
                    raw_observations, duration_ms, recall_at_k, reciprocal_rank,
                    ndcg, correct_supported, false_grounding, highlight_iou,
                    access_leaks, reproducible, id
                ) VALUES (
                    %s, %s, %s, %s, '{}'::jsonb, '[]'::jsonb,
                    '[{"stable":"same"},{"stable":"same"}]'::jsonb,
                    10, 0.6, 0.5, 0.55, true, false, 0.7, 0, true, %s
                )
                """,
                (candidate_id, uuid4(), ordinal, "4" * 64, uuid4()),
            )
    return owner_id, policy_id


@pytest.mark.asyncio
async def test_0010_migrates_forward_and_database_promotion_is_evidence_backed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t11_migration_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            await to_thread(command.upgrade, config, REVISION_0009)
            await to_thread(command.upgrade, config, REVISION_0010)

            with psycopg.connect(_sync_url(isolated_url), autocommit=True) as connection:
                with pytest.raises(psycopg.errors.RaiseException, match="qualifying"):
                    connection.execute(
                        """
                        UPDATE rag_configuration_versions
                        SET evaluation_state = 'passed', is_default = true
                        WHERE id = %s
                        """,
                        (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                    )

                assert connection.execute(
                    "SELECT count(*) FROM rag_configurations"
                ).fetchone() == (1,)
                assert connection.execute(
                    "SELECT count(*) FROM rag_configurations WHERE name ILIKE '%bge%'"
                ).fetchone() == (0,)
                bge = connection.execute(
                    """
                    SELECT model.config, indexing.config, retrieval.config
                    FROM rag_model_definitions AS model
                    JOIN rag_profile_model_bindings AS binding
                      ON binding.model_id = model.id
                    JOIN rag_profiles AS indexing ON indexing.id = binding.profile_id
                    JOIN rag_profiles AS retrieval
                      ON retrieval.id = %s
                    WHERE model.id = %s AND indexing.id = %s
                    """,
                    (BGE_RETRIEVAL_PROFILE_ID, BGE_MODEL_ID, BGE_INDEXING_PROFILE_ID),
                ).fetchone()
                assert bge is not None
                assert bge[0]["revision"] == "5617a9f61b028005a4858fdac845db406aefb181"
                assert bge[0]["dimension"] == 1024
                assert bge[0]["max_tokens"] == 8192
                assert bge[0]["output_mode"] == "dense"
                assert bge[0]["sparse_enabled"] is False
                assert bge[0]["colbert_enabled"] is False
                assert bge[2]["indexing_profile_id"] == str(BGE_INDEXING_PROFILE_ID)

            _, policy_id = _seed_qualifying_evidence(isolated_url)
            with psycopg.connect(_sync_url(isolated_url), autocommit=True) as connection:
                with pytest.raises(psycopg.errors.CheckViolation):
                    connection.execute(
                        """
                        UPDATE rag_evaluation_run_configurations
                        SET recall_at_k = 'Infinity'::float8
                        WHERE configuration_version_id = %s
                        """,
                        (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                    )
                connection.execute(
                    """
                    UPDATE rag_configuration_versions
                    SET evaluation_state = 'passed', is_default = true
                    WHERE id = %s
                    """,
                    (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                )
                assert connection.execute(
                    """
                    SELECT evaluation_state, is_default
                    FROM rag_configuration_versions WHERE id = %s
                    """,
                    (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                ).fetchone() == ("passed", True)
                with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                    connection.execute(
                        "UPDATE rag_evaluation_policies SET min_mrr = 0 WHERE id = %s",
                        (policy_id,),
                    )
                # Restore the pre-Task-11 state so the downgrade can reinstall its
                # temporary checks without deleting the qualifying audit evidence.
                connection.execute(
                    """
                    UPDATE rag_configuration_versions
                    SET is_default = false
                    WHERE id = %s
                    """,
                    (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                )
                connection.execute(
                    """
                    ALTER TABLE rag_configuration_versions
                    DISABLE TRIGGER trg_rag_configuration_versions_evaluation_gate
                    """
                )
                connection.execute(
                    """
                    UPDATE rag_configuration_versions
                    SET evaluation_state = 'pending'
                    WHERE id = %s
                    """,
                    (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                )
                connection.execute(
                    """
                    ALTER TABLE rag_configuration_versions
                    ENABLE TRIGGER trg_rag_configuration_versions_evaluation_gate
                    """
                )

            await to_thread(command.downgrade, config, REVISION_0009)
            with psycopg.connect(_sync_url(isolated_url), autocommit=True) as connection:
                evaluation_table = connection.execute(
                    "SELECT to_regclass('rag_evaluation_runs')"
                ).fetchone()
                assert evaluation_table == (None,)
                with pytest.raises(psycopg.errors.CheckViolation, match="no_passed"):
                    connection.execute(
                        """
                        UPDATE rag_configuration_versions
                        SET evaluation_state = 'passed'
                        WHERE id = %s
                        """,
                        (BM25_BASELINE_CONFIGURATION_VERSION_ID,),
                    )
            await to_thread(command.upgrade, config, "head")
            await to_thread(command.current, config, check_heads=True)
            await to_thread(command.check, config)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
