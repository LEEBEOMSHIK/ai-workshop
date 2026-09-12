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
NEW_ID = UUID("00000000-0000-0000-0000-000000000210")
OLD_ID = UUID("00000000-0000-0000-0000-000000000209")


def test_pdf_profile_upgrade_and_rollback_preserve_legacy_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = make_url(get_settings().database_url).update_query_dict({"connect_timeout": "10"})
    database = f"ai_workshop_t21_pdf_{uuid4().hex}"
    admin_url = base_url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    isolated_url = base_url.set(database=database).render_as_string(hide_password=False)
    sync_url = base_url.set(drivername="postgresql", database=database).render_as_string(
        hide_password=False
    )
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        monkeypatch.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
        get_settings.cache_clear()
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        command.upgrade(config, "0020_pp_structure_profile")
        with psycopg.connect(sync_url) as connection:
            old = connection.execute(
                "SELECT config, evaluation_state, is_default FROM rag_profiles WHERE id = %s",
                (OLD_ID,),
            ).fetchone()
        command.upgrade(config, "head")
        with psycopg.connect(sync_url) as connection:
            row = connection.execute(
                "SELECT name, version, config, evaluation_state, is_default "
                "FROM rag_profiles WHERE id = %s",
                (NEW_ID,),
            ).fetchone()
            assert row is not None
            assert row[:2] == ("pp-structure-v3-pdf-docx", 1)
            assert row[3:] == ("draft", False)
            assert row[2]["parser_policy"]["routes"]["application/pdf"] == {
                "name": "pymupdf-ocr",
                "version": "1",
                "options": {"raster_dpi": 144, "max_page_pixels": 16000000, "max_pages": 200},
            }
            bindings = connection.execute(
                "SELECT role, model_id FROM rag_profile_model_bindings "
                "WHERE profile_id = %s ORDER BY role",
                (NEW_ID,),
            ).fetchall()
            assert len(bindings) == 10
            assert (
                bindings
                == connection.execute(
                    "SELECT role, model_id FROM rag_profile_model_bindings "
                    "WHERE profile_id = %s ORDER BY role",
                    (OLD_ID,),
                ).fetchall()
            )
            assert (
                old
                == connection.execute(
                    "SELECT config, evaluation_state, is_default FROM rag_profiles WHERE id = %s",
                    (OLD_ID,),
                ).fetchone()
            )
        command.downgrade(config, "0020_pp_structure_profile")
        with psycopg.connect(sync_url) as connection:
            assert connection.execute(
                "SELECT count(*) FROM rag_profiles WHERE id = %s", (NEW_ID,)
            ).fetchone() == (0,)
            assert (
                old
                == connection.execute(
                    "SELECT config, evaluation_state, is_default FROM rag_profiles WHERE id = %s",
                    (OLD_ID,),
                ).fetchone()
            )
    finally:
        get_settings.cache_clear()
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )
