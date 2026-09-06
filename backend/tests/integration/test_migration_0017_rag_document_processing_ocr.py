from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import make_url

from ai_workshop.config import get_settings
from alembic import command

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REVISION_0016 = "0016_rag_llm_deployments"
REVISION_0017 = "0017_rag_document_processing_ocr"
LEGACY_DOCUMENT_PROCESSING_PROFILE_ID = UUID(
    "00000000-0000-0000-0000-000000000207"
)
BASELINE_CONFIGURATION_VERSION_ID = UUID("00000000-0000-0000-0000-000000000503")


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


def test_upgrade_seeds_legacy_profile_and_backfills_processing_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t17_doc_process_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            command.upgrade(config, REVISION_0017)
            command.current(config, check_heads=True)

            with psycopg.connect(_sync_url(isolated_url)) as connection:
                profile = connection.execute(
                    """
                    SELECT kind, name, version, evaluation_state, is_default,
                           config::jsonb -> 'ocr' ->> 'enabled'
                    FROM rag_profiles WHERE id = %s
                    """,
                    (LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,),
                ).fetchone()
                assert profile == (
                    "document_processing",
                    "legacy-text-document-processing",
                    1,
                    "passed",
                    True,
                    "false",
                )
                assert connection.execute(
                    """
                    SELECT document_processing_profile_id
                    FROM rag_configuration_versions WHERE id = %s
                    """,
                    (BASELINE_CONFIGURATION_VERSION_ID,),
                ).fetchone() == (LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,)
                columns = connection.execute(
                    """
                    SELECT table_name, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND column_name = 'document_processing_profile_id'
                      AND table_name IN (
                        'rag_configuration_versions',
                        'rag_document_projections',
                        'rag_ingestion_jobs',
                        'rag_index_builds',
                        'rag_asset_handoff_failures'
                      )
                    ORDER BY table_name
                    """
                ).fetchall()
                assert columns == [
                    ("rag_asset_handoff_failures", "NO"),
                    ("rag_configuration_versions", "NO"),
                    ("rag_document_projections", "NO"),
                    ("rag_index_builds", "NO"),
                    ("rag_ingestion_jobs", "NO"),
                ]
                identity_constraints = connection.execute(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conname IN (
                        'uq_rag_document_projections_processing_indexing',
                        'uq_rag_ingestion_jobs_processing_indexing',
                        'pk_rag_asset_handoff_failures_processing_indexing'
                    )
                    ORDER BY conname
                    """
                ).fetchall()
                assert identity_constraints == [
                    ("pk_rag_asset_handoff_failures_processing_indexing",),
                    ("uq_rag_document_projections_processing_indexing",),
                    ("uq_rag_ingestion_jobs_processing_indexing",),
                ]

            command.downgrade(config, REVISION_0016)
            command.upgrade(config, REVISION_0017)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
