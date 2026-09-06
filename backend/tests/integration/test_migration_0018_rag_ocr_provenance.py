from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import make_url

from ai_workshop.config import get_settings
from alembic import command

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REVISION_0017 = "0017_rag_document_processing_ocr"
REVISION_0018 = "0018_rag_ocr_provenance"


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _create_database(base_url: str, database: str) -> None:
    with psycopg.connect(
        _sync_url(_database_url(base_url, "postgres")), autocommit=True
    ) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))


def _drop_database(base_url: str, database: str) -> None:
    with psycopg.connect(
        _sync_url(_database_url(base_url, "postgres")), autocommit=True
    ) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
        )


def test_upgrade_adds_ocr_provenance_and_roundtrips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t18_ocr_provenance_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            command.upgrade(config, REVISION_0018)
            command.current(config, check_heads=True)

            with psycopg.connect(_sync_url(isolated_url)) as connection:
                columns = connection.execute(
                    """
                    SELECT table_name, column_name, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name IN ('rag_structural_elements', 'rag_evidence_units')
                      AND column_name IN (
                        'source_kind', 'source_part', 'image_sha256', 'table_cell',
                        'evidence_eligible', 'warnings'
                      )
                    ORDER BY table_name, column_name
                    """
                ).fetchall()
                assert columns == [
                    ("rag_evidence_units", "image_sha256", "YES"),
                    ("rag_evidence_units", "source_kind", "NO"),
                    ("rag_evidence_units", "source_part", "YES"),
                    ("rag_evidence_units", "table_cell", "YES"),
                    ("rag_structural_elements", "evidence_eligible", "NO"),
                    ("rag_structural_elements", "image_sha256", "YES"),
                    ("rag_structural_elements", "source_kind", "NO"),
                    ("rag_structural_elements", "source_part", "YES"),
                    ("rag_structural_elements", "table_cell", "YES"),
                    ("rag_structural_elements", "warnings", "NO"),
                ]

            command.downgrade(config, REVISION_0017)
            command.upgrade(config, REVISION_0018)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
