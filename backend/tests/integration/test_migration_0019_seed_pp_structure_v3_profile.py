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
REVISION_0018 = "0018_rag_ocr_provenance"
PROFILE_ID = UUID("00000000-0000-0000-0000-000000000208")
MODEL_IDS = tuple(
    UUID(f"00000000-0000-0000-0000-{value:012d}") for value in range(301, 311)
)
EXPECTED_KINDS = {
    "ocr_layout_detection",
    "ocr_text_detection",
    "ocr_text_recognition",
    "ocr_textline_orientation",
    "ocr_table_classification",
    "ocr_table_structure_wired",
    "ocr_table_structure",
    "ocr_table_cells_wired",
    "ocr_table_cells_wireless",
    "ocr_table_orientation",
}


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


def test_upgrade_seeds_a_complete_draft_pp_structure_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t19_pp_structure_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            command.upgrade(config, REVISION_0018)
            command.upgrade(config, "0019_pp_structure_v3")

            with psycopg.connect(_sync_url(isolated_url)) as connection:
                profile = connection.execute(
                    """
                    SELECT kind, name, version, evaluation_state, is_default,
                           config::jsonb -> 'ocr' ->> 'pipeline_name'
                    FROM rag_profiles WHERE id = %s
                    """,
                    (PROFILE_ID,),
                ).fetchone()
                assert profile == (
                    "document_processing",
                    "pp-structure-v3-docx",
                    1,
                    "draft",
                    False,
                    "PP-StructureV3",
                )
                models = connection.execute(
                    """
                    SELECT id, kind, name, config::jsonb ->> 'revision',
                           config::jsonb ->> 'artifact_sha256',
                           config::jsonb ->> 'license',
                           config::jsonb ->> 'data_policy'
                    FROM rag_model_definitions
                    WHERE id = ANY(%s)
                    ORDER BY kind
                    """,
                    (list(MODEL_IDS),),
                ).fetchall()
                assert len(models) == 10
                assert {row[1] for row in models} == EXPECTED_KINDS
                assert all(len(row[3]) == 40 for row in models)
                assert all(len(row[4]) == 64 for row in models)
                assert all(row[5:] == ("Apache-2.0", "local_only") for row in models)
                bindings = connection.execute(
                    """
                    SELECT role FROM rag_profile_model_bindings
                    WHERE profile_id = %s
                    """,
                    (PROFILE_ID,),
                ).fetchall()
                assert {row[0] for row in bindings} == EXPECTED_KINDS

            command.downgrade(config, REVISION_0018)
            with psycopg.connect(_sync_url(isolated_url)) as connection:
                assert connection.execute(
                    "SELECT count(*) FROM rag_profiles WHERE id = %s",
                    (PROFILE_ID,),
                ).fetchone() == (0,)
                assert connection.execute(
                    "SELECT count(*) FROM rag_model_definitions WHERE id = ANY(%s)",
                    (list(MODEL_IDS),),
                ).fetchone() == (0,)
            command.upgrade(config, "head")
            command.current(config, check_heads=True)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
