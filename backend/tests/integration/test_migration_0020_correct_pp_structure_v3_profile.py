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
REVISION_0019 = "0019_pp_structure_v3"
PROFILE_V1_ID = UUID("00000000-0000-0000-0000-000000000208")
PROFILE_V2_ID = UUID("00000000-0000-0000-0000-000000000209")
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


def test_upgrade_preserves_v1_and_seeds_semantically_correct_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t20_pp_structure_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            command.upgrade(config, REVISION_0019)
            command.upgrade(config, "head")

            with psycopg.connect(_sync_url(isolated_url)) as connection:
                profiles = connection.execute(
                    """
                    SELECT id, version, evaluation_state, is_default,
                           config::jsonb -> 'ocr' -> 'enabled_modules',
                           config::jsonb -> 'ocr' -> 'disabled_modules'
                    FROM rag_profiles
                    WHERE id = ANY(%s)
                    ORDER BY version
                    """,
                    ([PROFILE_V1_ID, PROFILE_V2_ID],),
                ).fetchall()
                assert profiles[0][:4] == (PROFILE_V1_ID, 1, "failed", False)
                assert profiles[1][:4] == (PROFILE_V2_ID, 2, "draft", False)
                assert "table_ocr_textline_orientation" in profiles[1][4]
                assert "general_ocr_textline_orientation" in profiles[1][5]

                bindings = connection.execute(
                    """
                    SELECT role FROM rag_profile_model_bindings
                    WHERE profile_id = %s
                    """,
                    (PROFILE_V2_ID,),
                ).fetchall()
                assert {row[0] for row in bindings} == EXPECTED_KINDS

            command.downgrade(config, REVISION_0019)
            with psycopg.connect(_sync_url(isolated_url)) as connection:
                assert connection.execute(
                    "SELECT evaluation_state FROM rag_profiles WHERE id = %s",
                    (PROFILE_V1_ID,),
                ).fetchone() == ("draft",)
                assert connection.execute(
                    "SELECT count(*) FROM rag_profiles WHERE id = %s",
                    (PROFILE_V2_ID,),
                ).fetchone() == (0,)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
