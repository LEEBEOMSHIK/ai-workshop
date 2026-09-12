from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from ai_workshop.config import Settings, get_settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DATABASE_NAME = re.compile(r"ai_workshop_publishing_[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class IsolatedPublishingDatabase:
    config: Config
    database_url: str
    name: str


def _database_url(base_url: str, database: str) -> str:
    return (
        make_url(base_url)
        .set(database=database)
        .update_query_dict({"connect_timeout": "5"})
        .render_as_string(hide_password=False)
    )


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _require_exact_database_name(database: str) -> None:
    if _DATABASE_NAME.fullmatch(database) is None:
        raise AssertionError("refusing to operate on a non-publishing test database")


def _assert_current_database(database_url: str, expected: str) -> None:
    with psycopg.connect(_sync_url(database_url), connect_timeout=5) as connection:
        actual = connection.execute("SELECT current_database()").fetchone()
    assert actual == (expected,)


@contextmanager
def isolated_publishing_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[IsolatedPublishingDatabase]:
    settings = Settings(_env_file=BACKEND_ROOT.parent / ".env")  # type: ignore[call-arg]
    database = f"ai_workshop_publishing_{uuid4().hex}"
    _require_exact_database_name(database)
    isolated_url = _database_url(settings.database_url, database)
    administrative_url = _database_url(settings.database_url, "postgres")
    with psycopg.connect(
        _sync_url(administrative_url), autocommit=True, connect_timeout=5
    ) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    print(f"publishing_test_database_created={database}")
    try:
        _assert_current_database(isolated_url, database)
        monkeypatch.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
        monkeypatch.setenv("AI_WORKSHOP_SECRET_KEY", "publishing-test-secret-key-value")
        get_settings.cache_clear()
        yield IsolatedPublishingDatabase(
            config=Config(str(BACKEND_ROOT / "alembic.ini")),
            database_url=isolated_url,
            name=database,
        )
    finally:
        get_settings.cache_clear()
        _require_exact_database_name(database)
        _assert_current_database(isolated_url, database)
        with psycopg.connect(
            _sync_url(administrative_url), autocommit=True, connect_timeout=5
        ) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )
        print(f"publishing_test_database_dropped={database}")
