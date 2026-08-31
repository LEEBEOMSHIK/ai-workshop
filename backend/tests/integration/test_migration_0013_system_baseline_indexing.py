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
REVISION_0012 = "0012_terminal_rag_handoffs"
REVISION_0013 = "0013_system_baseline_indexing"
BASELINE_VERSION_ID = UUID("00000000-0000-0000-0000-000000000503")
BASELINE_SUBSCRIPTION_ID = UUID("00000000-0000-0000-0000-000000000504")
E5_MODEL_ID = UUID("00000000-0000-0000-0000-000000000101")


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


def test_fresh_upgrade_seeds_exact_compatible_nondefault_baseline_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t14_baseline_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            command.upgrade(config, "head")
            command.current(config, check_heads=True)
            command.check(config)

            with psycopg.connect(_sync_url(isolated_url)) as connection:
                row = connection.execute(
                    """
                    SELECT subscription.id, version.id, configuration.is_system,
                           version.evaluation_state, version.is_default,
                           retrieval.config::jsonb ->> 'indexing_profile_id',
                           version.indexing_profile_id::text
                    FROM rag_system_indexing_subscriptions AS subscription
                    JOIN rag_configuration_versions AS version
                      ON version.id = subscription.configuration_version_id
                    JOIN rag_configurations AS configuration
                      ON configuration.id = version.configuration_id
                    JOIN rag_profiles AS retrieval
                      ON retrieval.id = version.retrieval_profile_id
                    """
                ).fetchone()
                assert row == (
                    BASELINE_SUBSCRIPTION_ID,
                    BASELINE_VERSION_ID,
                    True,
                    "pending",
                    False,
                    row[6],
                    row[6],
                )

            command.downgrade(config, REVISION_0012)
            with psycopg.connect(_sync_url(isolated_url)) as connection:
                assert connection.execute(
                    "SELECT to_regclass('rag_system_indexing_subscriptions')"
                ).fetchone() == (None,)
            command.upgrade(config, REVISION_0013)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)


def test_upgrade_restores_a_fully_missing_committed_baseline_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t14_missing_baseline_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            command.upgrade(config, REVISION_0012)
            with psycopg.connect(_sync_url(isolated_url)) as connection:
                connection.execute(
                    """
                    TRUNCATE TABLE rag_profile_model_bindings, rag_profiles,
                                   rag_model_definitions, rag_configurations
                    RESTART IDENTITY CASCADE
                    """
                )
                connection.commit()

            command.upgrade(config, REVISION_0013)

            with psycopg.connect(_sync_url(isolated_url)) as connection:
                row = connection.execute(
                    """
                    SELECT subscription.id, version.id, configuration.is_system,
                           configuration.owner_id, version.evaluation_state,
                           version.is_default,
                           retrieval.config::jsonb ->> 'indexing_profile_id',
                           version.indexing_profile_id::text
                    FROM rag_system_indexing_subscriptions AS subscription
                    JOIN rag_configuration_versions AS version
                      ON version.id = subscription.configuration_version_id
                    JOIN rag_configurations AS configuration
                      ON configuration.id = version.configuration_id
                    JOIN rag_profiles AS retrieval
                      ON retrieval.id = version.retrieval_profile_id
                    """
                ).fetchone()
                assert row == (
                    BASELINE_SUBSCRIPTION_ID,
                    BASELINE_VERSION_ID,
                    True,
                    None,
                    "pending",
                    False,
                    row[7],
                    row[7],
                )
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)


def test_upgrade_rejects_partial_seed_and_rolls_back_every_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t14_partial_baseline_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            command.upgrade(config, REVISION_0012)
            with psycopg.connect(_sync_url(isolated_url)) as connection:
                connection.execute(
                    """
                    TRUNCATE TABLE rag_profile_model_bindings, rag_profiles,
                                   rag_model_definitions, rag_configurations
                    RESTART IDENTITY CASCADE
                    """
                )
                connection.execute(
                    """
                    INSERT INTO rag_model_definitions (kind, name, version, config, id)
                    VALUES ('embedding', 'multilingual-e5-base', 1, '{}'::json, %s)
                    """,
                    (E5_MODEL_ID,),
                )
                connection.commit()

            with pytest.raises(
                RuntimeError,
                match="approved BM25 baseline seed is partially present or conflicting",
            ):
                command.upgrade(config, REVISION_0013)

            with psycopg.connect(_sync_url(isolated_url)) as connection:
                assert connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone() == (REVISION_0012,)
                assert connection.execute(
                    "SELECT to_regclass('rag_system_indexing_subscriptions')"
                ).fetchone() == (None,)
                assert connection.execute(
                    "SELECT count(*) FROM rag_model_definitions"
                ).fetchone() == (1,)
                assert connection.execute(
                    "SELECT count(*) FROM rag_profiles"
                ).fetchone() == (0,)
                assert connection.execute(
                    "SELECT count(*) FROM rag_configurations"
                ).fetchone() == (0,)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
