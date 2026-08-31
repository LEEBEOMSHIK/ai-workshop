import logging
from io import StringIO
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


def test_programmatic_migration_preserves_existing_application_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_alembic_logging_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    logger = logging.getLogger("ai_workshop.tests.alembic_logging")
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    previous_disabled = logger.disabled
    previous_level = logger.level
    previous_propagate = logger.propagate

    logger.disabled = False
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    logger.addHandler(handler)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))

            command.upgrade(config, "head")
            logger.error("application logger survived programmatic migration")

            assert logger.disabled is False
            assert "application logger survived programmatic migration" in stream.getvalue()
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.disabled = previous_disabled
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
