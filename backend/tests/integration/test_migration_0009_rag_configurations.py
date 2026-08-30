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


def _assert_database_rejects_enabled_reranker(database_url: str) -> None:
    configuration_id = uuid4()
    policy_id = uuid4()
    retrieval_profile_id = uuid4()
    with psycopg.connect(_sync_url(database_url)) as connection:  # noqa: SIM117
        with connection.transaction(force_rollback=True):
            connection.execute(
                """
                INSERT INTO rag_profiles (
                    kind, name, version, config, evaluation_state, is_default, id
                ) VALUES ('retrieval', %s, 1, %s::json, 'draft', false, %s)
                """,
                (
                    f"enabled-reranker-{retrieval_profile_id}",
                    json.dumps(
                        {
                            "bm25": {"analyzer": "standard", "top_k": 30},
                            "indexing_profile_id": str(E5_INDEXING_PROFILE_ID),
                            "reranker": {"enabled": True},
                        }
                    ),
                    retrieval_profile_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO rag_configurations (owner_id, name, is_system, id)
                VALUES (NULL, %s, true, %s)
                """,
                (f"reranker-system-{configuration_id}", configuration_id),
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
                (configuration_id, policy_id),
            )
            with pytest.raises(psycopg.errors.RaiseException, match="reranker"):
                connection.execute(
                    """
                    INSERT INTO rag_configuration_versions (
                        configuration_id, version, indexing_profile_id,
                        retrieval_profile_id, generation_profile_id,
                        answer_policy_version_id, evaluation_state, is_default, id
                    ) VALUES (%s, 1, %s, %s, NULL, %s, 'pending', false, %s)
                    """,
                    (
                        configuration_id,
                        E5_INDEXING_PROFILE_ID,
                        retrieval_profile_id,
                        policy_id,
                        uuid4(),
                    ),
                )


def _assert_database_rejects_bound_reranker(database_url: str) -> None:
    configuration_id = uuid4()
    policy_id = uuid4()
    retrieval_profile_id = uuid4()
    reranker_model_id = uuid4()
    with psycopg.connect(_sync_url(database_url)) as connection:  # noqa: SIM117
        with connection.transaction(force_rollback=True):
            connection.execute(
                """
                INSERT INTO rag_model_definitions (kind, name, version, config, id)
                VALUES ('reranker', %s, 1, '{}'::json, %s)
                """,
                (f"reranker-{reranker_model_id}", reranker_model_id),
            )
            connection.execute(
                """
                INSERT INTO rag_profiles (
                    kind, name, version, config, evaluation_state, is_default, id
                ) VALUES ('retrieval', %s, 1, %s::json, 'draft', false, %s)
                """,
                (
                    f"bound-reranker-{retrieval_profile_id}",
                    json.dumps(
                        {
                            "bm25": {"analyzer": "standard", "top_k": 30},
                            "indexing_profile_id": str(E5_INDEXING_PROFILE_ID),
                            "reranker": {"enabled": False},
                        }
                    ),
                    retrieval_profile_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO rag_profile_model_bindings (profile_id, role, model_id, id)
                VALUES (%s, 'reranker', %s, %s)
                """,
                (retrieval_profile_id, reranker_model_id, uuid4()),
            )
            connection.execute(
                """
                INSERT INTO rag_configurations (owner_id, name, is_system, id)
                VALUES (NULL, %s, true, %s)
                """,
                (f"bound-reranker-system-{configuration_id}", configuration_id),
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
                (configuration_id, policy_id),
            )
            with pytest.raises(psycopg.errors.RaiseException, match="binding"):
                connection.execute(
                    """
                    INSERT INTO rag_configuration_versions (
                        configuration_id, version, indexing_profile_id,
                        retrieval_profile_id, generation_profile_id,
                        answer_policy_version_id, evaluation_state, is_default, id
                    ) VALUES (%s, 1, %s, %s, NULL, %s, 'pending', false, %s)
                    """,
                    (
                        configuration_id,
                        E5_INDEXING_PROFILE_ID,
                        retrieval_profile_id,
                        policy_id,
                        uuid4(),
                    ),
                )


def _assert_database_rejects_reranker_selection(database_url: str) -> None:
    configuration_id = uuid4()
    policy_id = uuid4()
    retrieval_profile_id = uuid4()
    with psycopg.connect(_sync_url(database_url)) as connection:  # noqa: SIM117
        with connection.transaction(force_rollback=True):
            connection.execute(
                """
                INSERT INTO rag_profiles (
                    kind, name, version, config, evaluation_state, is_default, id
                ) VALUES ('retrieval', %s, 1, %s::json, 'draft', false, %s)
                """,
                (
                    f"selected-reranker-{retrieval_profile_id}",
                    json.dumps(
                        {
                            "bm25": {"analyzer": "standard", "top_k": 30},
                            "indexing_profile_id": str(E5_INDEXING_PROFILE_ID),
                            "reranker_profile_id": str(uuid4()),
                        }
                    ),
                    retrieval_profile_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO rag_configurations (owner_id, name, is_system, id)
                VALUES (NULL, %s, true, %s)
                """,
                (f"selected-reranker-system-{configuration_id}", configuration_id),
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
                (configuration_id, policy_id),
            )
            with pytest.raises(psycopg.errors.RaiseException, match="selection"):
                connection.execute(
                    """
                    INSERT INTO rag_configuration_versions (
                        configuration_id, version, indexing_profile_id,
                        retrieval_profile_id, generation_profile_id,
                        answer_policy_version_id, evaluation_state, is_default, id
                    ) VALUES (%s, 1, %s, %s, NULL, %s, 'pending', false, %s)
                    """,
                    (
                        configuration_id,
                        E5_INDEXING_PROFILE_ID,
                        retrieval_profile_id,
                        policy_id,
                        uuid4(),
                    ),
                )


def _assert_database_blocks_task11_states(database_url: str) -> None:
    with psycopg.connect(
        _sync_url(database_url), autocommit=True
    ) as connection:  # noqa: SIM117
        with pytest.raises(psycopg.errors.CheckViolation, match="no_passed"):
            connection.execute(
                """
                UPDATE rag_configuration_versions
                SET evaluation_state = 'passed'
                WHERE configuration_id = %s
                """,
                (BM25_BASELINE_CONFIGURATION_ID,),
            )
        with pytest.raises(psycopg.errors.CheckViolation, match="no_default"):
            connection.execute(
                """
                UPDATE rag_configuration_versions
                SET evaluation_state = 'passed', is_default = true
                WHERE configuration_id = %s
                """,
                (BM25_BASELINE_CONFIGURATION_ID,),
            )


def _assert_database_requires_matching_policy_version(database_url: str) -> None:
    with psycopg.connect(  # noqa: SIM117
        _sync_url(database_url), autocommit=True
    ) as connection:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                """
                INSERT INTO rag_configuration_versions (
                    configuration_id, version, indexing_profile_id,
                    retrieval_profile_id, generation_profile_id,
                    answer_policy_version_id, evaluation_state, is_default, id
                ) VALUES (
                    %s, 2, %s, %s, NULL,
                    (
                        SELECT id FROM rag_answer_policy_versions
                        WHERE configuration_id = %s AND version = 1
                    ),
                    'pending', false, %s
                )
                """,
                (
                    BM25_BASELINE_CONFIGURATION_ID,
                    E5_INDEXING_PROFILE_ID,
                    BM25_RETRIEVAL_PROFILE_ID,
                    BM25_BASELINE_CONFIGURATION_ID,
                    uuid4(),
                ),
            )


def _assert_referenced_technical_components_are_immutable(database_url: str) -> None:
    with psycopg.connect(_sync_url(database_url), autocommit=True) as connection:
        model_id = connection.execute(
            """
            SELECT model_id FROM rag_profile_model_bindings
            WHERE profile_id = %s
            """,
            (E5_INDEXING_PROFILE_ID,),
        ).fetchone()[0]
        binding_id = connection.execute(
            """
            SELECT id FROM rag_profile_model_bindings
            WHERE profile_id = %s
            """,
            (E5_INDEXING_PROFILE_ID,),
        ).fetchone()[0]

        with pytest.raises(psycopg.errors.RaiseException, match="referenced profile"):
            connection.execute(
                "UPDATE rag_profiles SET name = name || '-changed' WHERE id = %s",
                (E5_INDEXING_PROFILE_ID,),
            )
        with pytest.raises(psycopg.errors.RaiseException, match="referenced profile"):
            connection.execute(
                "DELETE FROM rag_profiles WHERE id = %s",
                (BM25_RETRIEVAL_PROFILE_ID,),
            )
        with pytest.raises(psycopg.errors.RaiseException, match="referenced binding"):
            connection.execute(
                "UPDATE rag_profile_model_bindings SET role = 'reranker' WHERE id = %s",
                (binding_id,),
            )
        with pytest.raises(psycopg.errors.RaiseException, match="referenced binding"):
            connection.execute(
                "DELETE FROM rag_profile_model_bindings WHERE id = %s",
                (binding_id,),
            )
        with pytest.raises(psycopg.errors.RaiseException, match="referenced model"):
            connection.execute(
                "UPDATE rag_model_definitions SET config = '{}'::json WHERE id = %s",
                (model_id,),
            )
        with pytest.raises(psycopg.errors.RaiseException, match="referenced model"):
            connection.execute(
                "DELETE FROM rag_model_definitions WHERE id = %s",
                (model_id,),
            )


def _assert_unreferenced_technical_drafts_remain_mutable(database_url: str) -> None:
    profile_id = uuid4()
    model_id = uuid4()
    binding_id = uuid4()
    with psycopg.connect(_sync_url(database_url), autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO rag_model_definitions (kind, name, version, config, id)
            VALUES ('embedding', %s, 1, '{}'::json, %s)
            """,
            (f"unreferenced-model-{model_id}", model_id),
        )
        connection.execute(
            """
            INSERT INTO rag_profiles (
                kind, name, version, config, evaluation_state, is_default, id
            ) VALUES ('indexing', %s, 1, '{}'::json, 'draft', false, %s)
            """,
            (f"unreferenced-profile-{profile_id}", profile_id),
        )
        connection.execute(
            """
            INSERT INTO rag_profile_model_bindings (profile_id, role, model_id, id)
            VALUES (%s, 'embedding', %s, %s)
            """,
            (profile_id, model_id, binding_id),
        )

        connection.execute(
            "UPDATE rag_profiles SET config = '{\"draft\": true}'::json WHERE id = %s",
            (profile_id,),
        )
        connection.execute(
            "UPDATE rag_profile_model_bindings SET role = 'reranker' WHERE id = %s",
            (binding_id,),
        )
        connection.execute(
            "UPDATE rag_model_definitions SET config = '{\"draft\": true}'::json WHERE id = %s",
            (model_id,),
        )
        assert connection.execute(
            "SELECT config FROM rag_profiles WHERE id = %s", (profile_id,)
        ).fetchone() == ({"draft": True},)
        assert connection.execute(
            "SELECT role FROM rag_profile_model_bindings WHERE id = %s", (binding_id,)
        ).fetchone() == ("reranker",)
        assert connection.execute(
            "SELECT config FROM rag_model_definitions WHERE id = %s", (model_id,)
        ).fetchone() == ({"draft": True},)
        connection.execute(
            "DELETE FROM rag_profile_model_bindings WHERE id = %s",
            (binding_id,),
        )
        connection.execute("DELETE FROM rag_profiles WHERE id = %s", (profile_id,))
        connection.execute(
            "DELETE FROM rag_model_definitions WHERE id = %s", (model_id,)
        )


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
            _assert_database_rejects_enabled_reranker(isolated_url)
            _assert_database_rejects_bound_reranker(isolated_url)
            _assert_database_rejects_reranker_selection(isolated_url)
            _assert_database_blocks_task11_states(isolated_url)
            _assert_database_requires_matching_policy_version(isolated_url)
            _assert_referenced_technical_components_are_immutable(isolated_url)
            _assert_unreferenced_technical_drafts_remain_mutable(isolated_url)
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


@pytest.mark.parametrize(
    ("profile_config", "evaluation_state", "with_binding"),
    [
        (
            {
                "bm25": {"analyzer": "standard", "top_k": 30},
                "dense": {"top_k": 30},
                "rrf": {"k": 60},
                "indexing_profile_id": str(E5_INDEXING_PROFILE_ID),
            },
            "draft",
            False,
        ),
        (
            {
                "bm25": {"analyzer": "keyword", "top_k": 99},
                "indexing_profile_id": str(E5_INDEXING_PROFILE_ID),
            },
            "draft",
            False,
        ),
        (
            {
                "bm25": {"analyzer": "standard", "top_k": 30},
                "indexing_profile_id": str(E5_INDEXING_PROFILE_ID),
            },
            "draft",
            True,
        ),
        (
            {
                "bm25": {"analyzer": "standard", "top_k": 30},
                "indexing_profile_id": str(E5_INDEXING_PROFILE_ID),
            },
            "pending",
            False,
        ),
    ],
    ids=("dense-shape", "analyzer-top-k", "binding", "evaluation-state"),
)
def test_0009_rejects_conflicting_full_bm25_profile_shape(
    monkeypatch: pytest.MonkeyPatch,
    profile_config: dict[str, object],
    evaluation_state: str,
    with_binding: bool,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t10_shape_{uuid4().hex}"
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
                    ) VALUES ('retrieval', 'bm25-baseline', 1, %s::json, %s, false, %s)
                    """,
                    (
                        json.dumps(profile_config),
                        evaluation_state,
                        BM25_RETRIEVAL_PROFILE_ID,
                    ),
                )
                if with_binding:
                    model_id = uuid4()
                    connection.execute(
                        """
                        INSERT INTO rag_model_definitions (
                            kind, name, version, config, id
                        ) VALUES ('reranker', %s, 1, '{}'::json, %s)
                        """,
                        (f"shape-reranker-{model_id}", model_id),
                    )
                    connection.execute(
                        """
                        INSERT INTO rag_profile_model_bindings (
                            profile_id, role, model_id, id
                        ) VALUES (%s, 'reranker', %s, %s)
                        """,
                        (BM25_RETRIEVAL_PROFILE_ID, model_id, uuid4()),
                    )

            with pytest.raises(RuntimeError, match="BM25 Retrieval Profile"):
                command.upgrade(config, REVISION_0009)

            with psycopg.connect(_sync_url(isolated_url)) as connection:
                assert connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone() == (REVISION_0008,)
    finally:
        get_settings.cache_clear()
        _drop_database(base_settings.database_url, database)
