from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from time import monotonic
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


@dataclass(frozen=True, slots=True)
class TechnicalFixture:
    configuration_id: UUID
    policy_id: UUID
    version_id: UUID
    indexing_profile_id: UUID
    retrieval_profile_id: UUID
    embedding_model_id: UUID
    reranker_model_id: UUID


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


def _seed_technical_fixture(
    database_url: str,
    *,
    bind_embedding: bool = False,
) -> TechnicalFixture:
    fixture = TechnicalFixture(
        configuration_id=uuid4(),
        policy_id=uuid4(),
        version_id=uuid4(),
        indexing_profile_id=uuid4(),
        retrieval_profile_id=uuid4(),
        embedding_model_id=uuid4(),
        reranker_model_id=uuid4(),
    )
    with psycopg.connect(_sync_url(database_url)) as connection:
        connection.execute(
            """
            INSERT INTO rag_model_definitions (kind, name, version, config, id)
            VALUES
              ('embedding', %s, 1, '{}'::json, %s),
              ('reranker', %s, 1, '{}'::json, %s)
            """,
            (
                f"race-embedding-{fixture.embedding_model_id}",
                fixture.embedding_model_id,
                f"race-reranker-{fixture.reranker_model_id}",
                fixture.reranker_model_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO rag_profiles (
                kind, name, version, config, evaluation_state, is_default, id
            ) VALUES
              ('indexing', %s, 1, %s::json, 'draft', false, %s),
              ('retrieval', %s, 1, %s::json, 'draft', false, %s)
            """,
            (
                f"race-indexing-{fixture.indexing_profile_id}",
                '{"chunker": {"name": "race"}}',
                fixture.indexing_profile_id,
                f"race-retrieval-{fixture.retrieval_profile_id}",
                (
                    '{"bm25": {"analyzer": "standard", "top_k": 10}, '
                    f'"indexing_profile_id": "{fixture.indexing_profile_id}"}}'
                ),
                fixture.retrieval_profile_id,
            ),
        )
        if bind_embedding:
            connection.execute(
                """
                INSERT INTO rag_profile_model_bindings (
                    profile_id, role, model_id, id
                ) VALUES (%s, 'embedding', %s, %s)
                """,
                (
                    fixture.indexing_profile_id,
                    fixture.embedding_model_id,
                    uuid4(),
                ),
            )
        connection.execute(
            """
            INSERT INTO rag_configurations (owner_id, name, is_system, id)
            VALUES (NULL, %s, true, %s)
            """,
            (f"race-configuration-{fixture.configuration_id}", fixture.configuration_id),
        )
        connection.execute(
            """
            INSERT INTO rag_answer_policy_versions (
                configuration_id, version, mode, min_semantic_score,
                min_keyword_coverage, require_complete_provenance,
                conflict_mode, id
            ) VALUES (%s, 1, 'extractive', 0.8, 0.7, true,
                      'separate_sources', %s)
            """,
            (fixture.configuration_id, fixture.policy_id),
        )
    return fixture


def _insert_configuration_version(
    connection: psycopg.Connection[tuple[object, ...]],
    fixture: TechnicalFixture,
) -> object:
    return connection.execute(
        """
        INSERT INTO rag_configuration_versions (
            configuration_id, version, indexing_profile_id,
            retrieval_profile_id, generation_profile_id,
            answer_policy_version_id, evaluation_state, is_default, id
        ) VALUES (%s, 1, %s, %s, NULL, %s, 'pending', false, %s)
        """,
        (
            fixture.configuration_id,
            fixture.indexing_profile_id,
            fixture.retrieval_profile_id,
            fixture.policy_id,
            fixture.version_id,
        ),
    )


def _insert_reranker_binding(
    connection: psycopg.Connection[tuple[object, ...]],
    fixture: TechnicalFixture,
) -> object:
    return connection.execute(
        """
        INSERT INTO rag_profile_model_bindings (profile_id, role, model_id, id)
        VALUES (%s, 'reranker', %s, %s)
        """,
        (fixture.retrieval_profile_id, fixture.reranker_model_id, uuid4()),
    )


def _waits_for_lock(
    database_url: str,
    *,
    backend_pid: int,
    operation: Future[object],
    advisory_only: bool = True,
    timeout_seconds: float = 5,
) -> bool:
    deadline = monotonic() + timeout_seconds
    with psycopg.connect(_sync_url(database_url), autocommit=True) as observer:
        while monotonic() < deadline:
            if operation.done():
                return False
            wait = observer.execute(
                """
                SELECT wait_event_type, wait_event
                FROM pg_stat_activity
                WHERE pid = %s
                """,
                (backend_pid,),
            ).fetchone()
            if wait is not None and wait[0] == "Lock" and (
                not advisory_only or wait[1] == "advisory"
            ):
                return True
            Event().wait(0.01)
    return False


def _observed_lock_event(
    database_url: str,
    *,
    backend_pid: int,
    operation: Future[object],
    timeout_seconds: float = 5,
) -> tuple[str, str] | None:
    deadline = monotonic() + timeout_seconds
    with psycopg.connect(_sync_url(database_url), autocommit=True) as observer:
        while monotonic() < deadline:
            if operation.done():
                return None
            wait = observer.execute(
                """
                SELECT wait_event_type, wait_event
                FROM pg_stat_activity
                WHERE pid = %s
                """,
                (backend_pid,),
            ).fetchone()
            if wait is not None and wait[0] == "Lock":
                return str(wait[0]), str(wait[1])
            Event().wait(0.01)
    return None


def _finish_operation(
    operation: Future[object],
    connection: psycopg.Connection[tuple[object, ...]],
) -> Exception | None:
    try:
        operation.result(timeout=5)
    except Exception as exc:
        connection.rollback()
        return exc
    connection.commit()
    return None


def _row_exists(database_url: str, table: str, row_id: UUID) -> bool:
    with psycopg.connect(_sync_url(database_url)) as connection:
        return (
            connection.execute(
                sql.SQL("SELECT EXISTS (SELECT 1 FROM {} WHERE id = %s)").format(
                    sql.Identifier(table)
                ),
                (row_id,),
            ).fetchone()
            == (True,)
        )


def _assert_config_wins_reranker_binding_race(database_url: str) -> None:
    fixture = _seed_technical_fixture(database_url)
    config_connection = psycopg.connect(_sync_url(database_url))
    binding_connection = psycopg.connect(_sync_url(database_url))
    try:
        _insert_configuration_version(config_connection, fixture)
        with ThreadPoolExecutor(max_workers=1) as executor:
            operation = executor.submit(
                _insert_reranker_binding, binding_connection, fixture
            )
            waited = _waits_for_lock(
                database_url,
                backend_pid=binding_connection.info.backend_pid,
                operation=operation,
            )
            config_connection.commit()
            error = _finish_operation(operation, binding_connection)

        assert waited is True, repr(error)
        assert isinstance(error, psycopg.errors.RaiseException)
        assert "referenced binding set is immutable" in str(error)
        assert _row_exists(
            database_url, "rag_configuration_versions", fixture.version_id
        )
        with psycopg.connect(_sync_url(database_url)) as connection:
            assert connection.execute(
                """
                SELECT count(*) FROM rag_profile_model_bindings
                WHERE profile_id = %s AND role = 'reranker'
                """,
                (fixture.retrieval_profile_id,),
            ).fetchone() == (0,)
    finally:
        config_connection.rollback()
        binding_connection.rollback()
        config_connection.close()
        binding_connection.close()


def _assert_binding_wins_reranker_configuration_race(database_url: str) -> None:
    fixture = _seed_technical_fixture(database_url)
    binding_connection = psycopg.connect(_sync_url(database_url))
    config_connection = psycopg.connect(_sync_url(database_url))
    try:
        _insert_reranker_binding(binding_connection, fixture)
        with ThreadPoolExecutor(max_workers=1) as executor:
            operation = executor.submit(
                _insert_configuration_version, config_connection, fixture
            )
            waited = _waits_for_lock(
                database_url,
                backend_pid=config_connection.info.backend_pid,
                operation=operation,
            )
            binding_connection.commit()
            error = _finish_operation(operation, config_connection)

        assert waited is True
        assert isinstance(error, psycopg.errors.RaiseException)
        assert "reranker binding is not supported" in str(error)
        assert not _row_exists(
            database_url, "rag_configuration_versions", fixture.version_id
        )
        with psycopg.connect(_sync_url(database_url)) as connection:
            assert connection.execute(
                """
                SELECT count(*) FROM rag_profile_model_bindings
                WHERE profile_id = %s AND role = 'reranker'
                """,
                (fixture.retrieval_profile_id,),
            ).fetchone() == (1,)
    finally:
        binding_connection.rollback()
        config_connection.rollback()
        binding_connection.close()
        config_connection.close()


def _assert_config_wins_component_update_race(
    database_url: str,
    mutation: str,
) -> None:
    fixture = _seed_technical_fixture(database_url, bind_embedding=True)
    config_connection = psycopg.connect(_sync_url(database_url))
    mutation_connection = psycopg.connect(_sync_url(database_url))
    try:
        _insert_configuration_version(config_connection, fixture)
        if mutation == "profile":
            statement = "UPDATE rag_profiles SET name = name || '-changed' WHERE id = %s"
            parameters = (fixture.retrieval_profile_id,)
            expected_error = "referenced profile version is immutable"
        else:
            statement = (
                "UPDATE rag_model_definitions SET name = name || '-changed' WHERE id = %s"
            )
            parameters = (fixture.embedding_model_id,)
            expected_error = "referenced model definition version is immutable"

        with ThreadPoolExecutor(max_workers=1) as executor:
            operation = executor.submit(
                mutation_connection.execute, statement, parameters
            )
            waited = _waits_for_lock(
                database_url,
                backend_pid=mutation_connection.info.backend_pid,
                operation=operation,
                advisory_only=False,
            )
            config_connection.commit()
            error = _finish_operation(operation, mutation_connection)

        assert waited is True, repr(error)
        assert isinstance(error, psycopg.errors.RaiseException)
        assert expected_error in str(error)
    finally:
        config_connection.rollback()
        mutation_connection.rollback()
        config_connection.close()
        mutation_connection.close()


def _assert_component_row_lock_precedes_advisory_lock(
    database_url: str,
    component: str,
) -> None:
    fixture = _seed_technical_fixture(database_url)
    locker = psycopg.connect(_sync_url(database_url))
    mutation_connection = psycopg.connect(_sync_url(database_url))
    try:
        if component == "profile":
            profile_ids = [fixture.retrieval_profile_id]
            model_ids: list[UUID] = []
            statement = "SELECT id FROM rag_profiles WHERE id = %s FOR UPDATE"
            parameters = (fixture.retrieval_profile_id,)
        else:
            profile_ids = []
            model_ids = [fixture.embedding_model_id]
            statement = (
                "SELECT id FROM rag_model_definitions WHERE id = %s FOR UPDATE"
            )
            parameters = (fixture.embedding_model_id,)

        locker.execute(
            "SELECT rag_lock_technical_components(%s::uuid[], %s::uuid[])",
            (profile_ids, model_ids),
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            operation = executor.submit(
                mutation_connection.execute, statement, parameters
            )
            wait_event = _observed_lock_event(
                database_url,
                backend_pid=mutation_connection.info.backend_pid,
                operation=operation,
            )
            locker.rollback()
            error = _finish_operation(operation, mutation_connection)

        assert wait_event is not None
        assert wait_event[1] != "advisory"
        assert error is None
    finally:
        locker.rollback()
        mutation_connection.rollback()
        locker.close()
        mutation_connection.close()


def _install_second_binding_row_gate(
    database_url: str,
    *,
    profile_id: UUID,
    gate_name: str,
) -> None:
    function_name = f"test_pause_binding_{uuid4().hex}"
    trigger_name = f"aaa_pause_binding_{uuid4().hex}"
    with psycopg.connect(_sync_url(database_url)) as connection:
        connection.execute(
            sql.SQL(
                """
                CREATE FUNCTION {}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.profile_id = {}::uuid THEN
                        PERFORM pg_advisory_xact_lock(
                            hashtextextended({}, 0)
                        );
                    END IF;
                    RETURN NEW;
                END;
                $$
                """
            ).format(
                sql.Identifier(function_name),
                sql.Literal(str(profile_id)),
                sql.Literal(gate_name),
            )
        )
        connection.execute(
            sql.SQL(
                """
                CREATE TRIGGER {} BEFORE INSERT ON rag_profile_model_bindings
                FOR EACH ROW EXECUTE FUNCTION {}()
                """
            ).format(
                sql.Identifier(trigger_name),
                sql.Identifier(function_name),
            )
        )


def _insert_reverse_profile_bindings(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    first_profile_id: UUID,
    second_profile_id: UUID,
    model_id: UUID,
) -> object:
    return connection.execute(
        """
        INSERT INTO rag_profile_model_bindings (profile_id, role, model_id, id)
        VALUES
          (%s, 'embedding', %s, %s),
          (%s, 'embedding', %s, %s)
        """,
        (
            first_profile_id,
            model_id,
            uuid4(),
            second_profile_id,
            model_id,
            uuid4(),
        ),
    )


def _assert_statement_lock_prevents_inverse_multirow_deadlock(
    database_url: str,
) -> None:
    fixture = _seed_technical_fixture(database_url)
    low_profile_id, high_profile_id = sorted(
        (fixture.indexing_profile_id, fixture.retrieval_profile_id)
    )
    gate_name = f"ai-workshop:test:binding-gate:{fixture.configuration_id}"
    _install_second_binding_row_gate(
        database_url,
        profile_id=low_profile_id,
        gate_name=gate_name,
    )
    blocker = psycopg.connect(_sync_url(database_url))
    binding_connection = psycopg.connect(_sync_url(database_url))
    config_connection = psycopg.connect(_sync_url(database_url))
    try:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (gate_name,),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            binding_operation = executor.submit(
                _insert_reverse_profile_bindings,
                binding_connection,
                first_profile_id=high_profile_id,
                second_profile_id=low_profile_id,
                model_id=fixture.embedding_model_id,
            )
            assert _waits_for_lock(
                database_url,
                backend_pid=binding_connection.info.backend_pid,
                operation=binding_operation,
            )
            config_operation = executor.submit(
                _insert_configuration_version,
                config_connection,
                fixture,
            )
            assert _waits_for_lock(
                database_url,
                backend_pid=config_connection.info.backend_pid,
                operation=config_operation,
            )

            blocker.rollback()
            binding_error = _finish_operation(
                binding_operation, binding_connection
            )
            config_error = _finish_operation(config_operation, config_connection)

        assert binding_error is None
        assert config_error is None
        assert _row_exists(
            database_url, "rag_configuration_versions", fixture.version_id
        )
    finally:
        blocker.rollback()
        binding_connection.rollback()
        config_connection.rollback()
        blocker.close()
        binding_connection.close()
        config_connection.close()


def test_0009_serializes_configuration_and_technical_component_races(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t10_serialization_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")

            _assert_component_row_lock_precedes_advisory_lock(
                isolated_url, "profile"
            )
            _assert_component_row_lock_precedes_advisory_lock(isolated_url, "model")
            _assert_statement_lock_prevents_inverse_multirow_deadlock(isolated_url)
            _assert_config_wins_reranker_binding_race(isolated_url)
            _assert_binding_wins_reranker_configuration_race(isolated_url)
            _assert_config_wins_component_update_race(isolated_url, "profile")
            _assert_config_wins_component_update_race(isolated_url, "model")
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
