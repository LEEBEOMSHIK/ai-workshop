import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import make_url

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.configurations.domain import (
    BM25_BASELINE_CONFIGURATION_ID,
    BM25_RETRIEVAL_PROFILE_ID,
    E5_INDEXING_PROFILE_ID,
)
from alembic import command

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REVISION_0008 = "0008_rag_embedding_artifacts"
REVISION_0009 = "0009_rag_configurations"


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


def _seed_populated_database(database_url: str) -> str:
    email = f"populated-{uuid4()}@example.test"
    with psycopg.connect(_sync_url(database_url)) as connection:
        connection.execute(
            """
            INSERT INTO users (
                display_name, email, normalized_email, password_hash,
                role, is_active, id
            ) VALUES ('Existing Owner', %s, %s, 'fixture-hash', 'owner', true, %s)
            """,
            (email, email, uuid4()),
        )
    return email


def _assert_seed(database_url: str, *, existing_email: str) -> None:
    with psycopg.connect(_sync_url(database_url)) as connection:
        baseline = connection.execute(
            """
            SELECT identity.name, version.evaluation_state, version.is_default,
                   version.indexing_profile_id, version.retrieval_profile_id,
                   version.generation_profile_id
            FROM rag_configurations AS identity
            JOIN rag_configuration_versions AS version
              ON version.configuration_id = identity.id
            WHERE identity.id = %s
            """,
            (BM25_BASELINE_CONFIGURATION_ID,),
        ).fetchone()
        assert baseline == (
            "BM25 기준선",
            "pending",
            False,
            E5_INDEXING_PROFILE_ID,
            BM25_RETRIEVAL_PROFILE_ID,
            None,
        )
        count = connection.execute(
            "SELECT count(*) FROM rag_configurations WHERE is_system"
        ).fetchone()
        assert count == (1,)
        assert connection.execute(
            "SELECT count(*) FROM users WHERE normalized_email = %s",
            (existing_email,),
        ).fetchone() == (1,)


def test_0009_upgrades_populated_database_and_reseeds_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t10_migration_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            command.upgrade(config, REVISION_0008)
            existing_email = _seed_populated_database(isolated_url)

            command.upgrade(config, REVISION_0009)
            _assert_seed(isolated_url, existing_email=existing_email)
            command.downgrade(config, REVISION_0008)
            with psycopg.connect(_sync_url(isolated_url)) as connection:
                assert connection.execute(
                    "SELECT to_regclass('rag_configurations')"
                ).fetchone() == (None,)
                assert connection.execute(
                    "SELECT count(*) FROM rag_profiles WHERE id IN (%s, %s)",
                    (E5_INDEXING_PROFILE_ID, BM25_RETRIEVAL_PROFILE_ID),
                ).fetchone() == (2,)

            command.upgrade(config, REVISION_0009)
            _assert_seed(isolated_url, existing_email=existing_email)
            command.current(config, check_heads=True)
            command.check(config)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)


def test_0009_rejects_a_conflicting_technical_profile_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t10_conflict_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            command.upgrade(config, REVISION_0008)
            with psycopg.connect(_sync_url(isolated_url)) as connection:
                connection.execute(
                    """
                    INSERT INTO rag_profiles (
                        kind, name, version, config, evaluation_state, is_default, id
                    ) VALUES ('retrieval', 'bm25-baseline', 1, %s::json, 'draft', false, %s)
                    """,
                    (
                        json.dumps(
                            {
                                "bm25": {"analyzer": "standard", "top_k": 30},
                                "indexing_profile_id": str(E5_INDEXING_PROFILE_ID),
                            }
                        ),
                        uuid4(),
                    ),
                )

            with pytest.raises(RuntimeError, match="deterministic ID"):
                command.upgrade(config, REVISION_0009)

            with psycopg.connect(_sync_url(isolated_url)) as connection:
                assert connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone() == (REVISION_0008,)
                assert connection.execute(
                    "SELECT to_regclass('rag_configurations')"
                ).fetchone() == (None,)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
