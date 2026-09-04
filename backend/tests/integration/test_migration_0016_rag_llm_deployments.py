from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
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
REVISION_0015 = "0015_rag_generation_v2"
REVISION_0016 = "0016_rag_llm_deployments"


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def _isolated_database(
    monkeypatch: pytest.MonkeyPatch, suffix: str
) -> Iterator[tuple[Config, str]]:
    base_settings = get_settings()
    database = f"ai_workshop_t2_{suffix}_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    administrative = _database_url(base_settings.database_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            yield Config(str(BACKEND_ROOT / "alembic.ini")), isolated_url
    finally:
        get_settings.cache_clear()
        with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )


def _insert_legacy_generation_fixture(
    connection: psycopg.Connection[object],
    *,
    model_name: str = "Legacy local model",
    runtime_model: object = "synthetic/exact-local-model",
) -> dict[str, UUID]:
    ids = {
        name: uuid4()
        for name in (
            "owner",
            "workspace",
            "llm",
            "indexing_profile",
            "retrieval_profile",
            "generation_profile",
            "llm_binding",
            "configuration",
            "answer_policy",
            "configuration_version",
        )
    }
    email = f"{ids['owner']}@example.test"
    connection.execute(
        """
        INSERT INTO users (
            display_name, email, normalized_email, password_hash, role, is_active, id
        ) VALUES ('Migration Owner', %s, %s, 'fixture-hash', 'owner', true, %s)
        """,
        (email, email, ids["owner"]),
    )
    connection.execute(
        """
        INSERT INTO workspaces (name, kind, created_by, expires_at, id)
        VALUES ('Migration Workspace', 'personal', %s, NULL, %s)
        """,
        (ids["owner"], ids["workspace"]),
    )
    connection.execute(
        """
        INSERT INTO rag_model_definitions (kind, name, version, config, id)
        VALUES ('llm', %s, 1, %s::json, %s)
        """,
        (
            model_name,
            json.dumps(
                {
                    "provider": "openai_compatible",
                    "data_policy": "local_only",
                    "runtime_model": runtime_model,
                }
            ),
            ids["llm"],
        ),
    )
    for profile_id, kind, name, config in (
        (ids["indexing_profile"], "indexing", "Migration indexing", {}),
        (
            ids["retrieval_profile"],
            "retrieval",
            "Migration retrieval",
            {"reranker": {"enabled": False}},
        ),
        (
            ids["generation_profile"],
            "generation",
            "Migration generation",
            {
                "prompt_ref": "answer-v1",
                "context_prompt_ref": "contextualize-v1",
                "citation_mode": "required",
                "context_policy": {"max_prior_turns": 2},
                "generation": {"max_output_tokens": 256},
            },
        ),
    ):
        connection.execute(
            """
            INSERT INTO rag_profiles (
                kind, name, version, config, evaluation_state, is_default, id
            ) VALUES (%s, %s, 1, %s::json, 'passed', false, %s)
            """,
            (kind, name, json.dumps(config), profile_id),
        )
    connection.execute(
        """
        INSERT INTO rag_profile_model_bindings (profile_id, role, model_id, id)
        VALUES (%s, 'llm', %s, %s)
        """,
        (ids["generation_profile"], ids["llm"], ids["llm_binding"]),
    )
    connection.execute(
        """
        INSERT INTO rag_configurations (owner_id, name, is_system, id)
        VALUES (%s, 'Migration configuration', false, %s)
        """,
        (ids["owner"], ids["configuration"]),
    )
    connection.execute(
        """
        INSERT INTO rag_answer_policy_versions (
            configuration_id, version, mode, min_semantic_score,
            min_keyword_coverage, require_complete_provenance, conflict_mode, id
        ) VALUES (%s, 1, 'generative', 0, 0, true, 'separate_sources', %s)
        """,
        (ids["configuration"], ids["answer_policy"]),
    )
    connection.execute(
        """
        INSERT INTO rag_configuration_versions (
            configuration_id, version, indexing_profile_id, retrieval_profile_id,
            generation_profile_id, answer_policy_version_id, evaluation_state,
            is_default, id
        ) VALUES (%s, 1, %s, %s, %s, %s, 'draft', false, %s)
        """,
        (
            ids["configuration"],
            ids["indexing_profile"],
            ids["retrieval_profile"],
            ids["generation_profile"],
            ids["answer_policy"],
            ids["configuration_version"],
        ),
    )
    connection.commit()
    return ids


def _insert_external_approval_fixture(
    connection: psycopg.Connection[object], ids: dict[str, UUID]
) -> dict[str, UUID]:
    fixture_ids = {
        name: uuid4()
        for name in (
            "deployment",
            "deployment_version",
            "generation_profile",
            "answer_policy",
            "configuration_version",
            "installation_policy_version",
            "workspace_policy",
            "workspace_policy_v1",
            "workspace_policy_v2",
            "extra_workspace",
            "extra_workspace_policy",
            "extra_workspace_policy_version",
        )
    }
    connection.execute(
        """
        INSERT INTO rag_secret_references (
            namespace, reference_name, created_by
        ) VALUES ('provider_secret', 'openai-primary', %s)
        """,
        (ids["owner"],),
    )
    connection.execute(
        "INSERT INTO rag_model_deployments (id, created_by) VALUES (%s, %s)",
        (fixture_ids["deployment"], ids["owner"]),
    )
    connection.execute(
        """
        INSERT INTO rag_model_deployment_versions (
            id, deployment_id, version, display_name, description,
            model_definition_id, provider, location, allowed_environments,
            provider_model_id, endpoint_ref, secret_ref_namespace, secret_ref,
            capabilities, external_transfer, transmitted_data_categories,
            data_processing_notice_ref, timeout_seconds, max_retries,
            retry_backoff_seconds, healthcheck_enabled, development_only,
            created_by
        ) VALUES (
            %s, %s, 1, 'External approval deployment', 'Synthetic metadata',
            %s, 'openai_responses', 'external', '["development"]'::json,
            'synthetic/exact-external-model', 'openai-responses',
            'provider_secret', 'openai-primary', '["structured_output"]'::json,
            true, '["question"]'::json, 'notice-v1', 10, 0, 0, true, false, %s
        )
        """,
        (
            fixture_ids["deployment_version"],
            fixture_ids["deployment"],
            ids["llm"],
            ids["owner"],
        ),
    )
    connection.execute(
        """
        INSERT INTO rag_profiles (
            id, kind, name, version, config, evaluation_state, is_default
        ) SELECT %s, 'generation', 'External approval generation', 1,
                 config, 'draft', false
          FROM rag_profiles WHERE id = %s
        """,
        (fixture_ids["generation_profile"], ids["generation_profile"]),
    )
    connection.execute(
        """
        INSERT INTO rag_generation_profile_deployments (
            profile_id, deployment_version_id
        ) VALUES (%s, %s)
        """,
        (fixture_ids["generation_profile"], fixture_ids["deployment_version"]),
    )
    connection.execute(
        """
        INSERT INTO rag_answer_policy_versions (
            id, configuration_id, version, mode, min_semantic_score,
            min_keyword_coverage, require_complete_provenance, conflict_mode
        ) VALUES (%s, %s, 2, 'generative', 0, 0, true, 'separate_sources')
        """,
        (fixture_ids["answer_policy"], ids["configuration"]),
    )
    connection.execute(
        """
        INSERT INTO rag_configuration_versions (
            id, configuration_id, version, indexing_profile_id,
            retrieval_profile_id, generation_profile_id,
            answer_policy_version_id, evaluation_state, is_default
        ) VALUES (%s, %s, 2, %s, %s, %s, %s, 'draft', false)
        """,
        (
            fixture_ids["configuration_version"],
            ids["configuration"],
            ids["indexing_profile"],
            ids["retrieval_profile"],
            fixture_ids["generation_profile"],
            fixture_ids["answer_policy"],
        ),
    )
    connection.execute(
        """
        INSERT INTO rag_configuration_workspace_subscriptions (
            id, configuration_version_id, workspace_id
        ) VALUES (%s, %s, %s)
        """,
        (uuid4(), fixture_ids["configuration_version"], ids["workspace"]),
    )
    installation_policy_id = connection.execute(
        "SELECT id FROM rag_installation_data_policies WHERE singleton_key"
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO rag_installation_data_policy_versions (
            id, policy_id, version, outbound_mode, approved_providers, changed_by
        ) VALUES (%s, %s, 2, 'approved_providers',
                  '["openai_responses"]'::json, %s)
        """,
        (
            fixture_ids["installation_policy_version"],
            installation_policy_id,
            ids["owner"],
        ),
    )
    connection.execute(
        """
        INSERT INTO rag_workspace_data_policies (id, workspace_id)
        VALUES (%s, %s)
        """,
        (fixture_ids["workspace_policy"], ids["workspace"]),
    )
    for version, version_id, mode, providers in (
        (1, fixture_ids["workspace_policy_v1"], "deny", "[]"),
        (
            2,
            fixture_ids["workspace_policy_v2"],
            "approved_providers",
            '["openai_responses"]',
        ),
    ):
        connection.execute(
            """
            INSERT INTO rag_workspace_data_policy_versions (
                id, policy_id, workspace_id, version, outbound_mode,
                approved_providers, changed_by
            ) VALUES (%s, %s, %s, %s, %s, %s::json, %s)
            """,
            (
                version_id,
                fixture_ids["workspace_policy"],
                ids["workspace"],
                version,
                mode,
                providers,
                ids["owner"],
            ),
        )
    connection.execute(
        """
        INSERT INTO workspaces (name, kind, created_by, expires_at, id)
        VALUES ('Extra approval workspace', 'personal', %s, NULL, %s)
        """,
        (ids["owner"], fixture_ids["extra_workspace"]),
    )
    connection.execute(
        """
        INSERT INTO rag_workspace_data_policies (id, workspace_id)
        VALUES (%s, %s)
        """,
        (fixture_ids["extra_workspace_policy"], fixture_ids["extra_workspace"]),
    )
    connection.execute(
        """
        INSERT INTO rag_workspace_data_policy_versions (
            id, policy_id, workspace_id, version, outbound_mode,
            approved_providers, changed_by
        ) VALUES (%s, %s, %s, 1, 'deny', '[]'::json, %s)
        """,
        (
            fixture_ids["extra_workspace_policy_version"],
            fixture_ids["extra_workspace_policy"],
            fixture_ids["extra_workspace"],
            ids["owner"],
        ),
    )
    fixture_ids["legacy_local_deployment_version"] = connection.execute(
        """
        SELECT deployment_version_id
        FROM rag_llm_deployment_migration_profile_copies
        LIMIT 1
        """
    ).fetchone()[0]
    fixture_ids["seed_installation_policy_version"] = connection.execute(
        """
        SELECT id FROM rag_installation_data_policy_versions WHERE version = 1
        """
    ).fetchone()[0]
    connection.commit()
    return fixture_ids


def test_fresh_upgrade_seeds_deny_policy_and_enforces_append_only_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_database(monkeypatch, "fresh") as (config, isolated_url):
        command.upgrade(config, REVISION_0016)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                """
                SELECT version, outbound_mode, approved_providers
                FROM rag_installation_data_policy_versions
                """
            ).fetchone() == (1, "deny", [])
            forbidden_columns = connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'rag_generation_execution_audits'
                  AND column_name = ANY(%s)
                ORDER BY column_name
                """,
                (
                    [
                        "question",
                        "history",
                        "prompt",
                        "prompt_text",
                        "evidence_text",
                        "document_text",
                        "secret",
                        "secret_ref",
                    ],
                ),
            ).fetchall()
            assert forbidden_columns == []

        command.downgrade(config, REVISION_0015)
        command.upgrade(config, REVISION_0016)


def test_legacy_upgrade_copies_convertible_local_profiles_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_database(monkeypatch, "legacy") as (config, isolated_url):
        command.upgrade(config, REVISION_0015)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            ids = _insert_legacy_generation_fixture(connection)
            before_binding = connection.execute(
                "SELECT profile_id, model_id FROM rag_profile_model_bindings WHERE id = %s",
                (ids["llm_binding"],),
            ).fetchone()
            before_configuration = connection.execute(
                "SELECT generation_profile_id FROM rag_configuration_versions WHERE id = %s",
                (ids["configuration_version"],),
            ).fetchone()

        command.upgrade(config, REVISION_0016)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                "SELECT profile_id, model_id FROM rag_profile_model_bindings WHERE id = %s",
                (ids["llm_binding"],),
            ).fetchone() == before_binding
            assert connection.execute(
                "SELECT generation_profile_id FROM rag_configuration_versions WHERE id = %s",
                (ids["configuration_version"],),
            ).fetchone() == before_configuration
            assert connection.execute(
                "SELECT count(*) FROM rag_model_deployment_versions"
            ).fetchone() == (1,)
            copied = connection.execute(
                """
                SELECT profile.name, profile.version, binding.deployment_version_id
                FROM rag_profiles AS profile
                JOIN rag_generation_profile_deployments AS binding
                  ON binding.profile_id = profile.id
                """
            ).fetchone()
            assert copied is not None
            assert copied[0:2] == ("Migration generation", 2)

            with pytest.raises(psycopg.errors.UniqueViolation):
                connection.execute(
                    """
                    INSERT INTO rag_model_deployment_versions (
                        deployment_id, version, display_name, description,
                        model_definition_id, provider, location, allowed_environments,
                        provider_model_id, endpoint_ref, capabilities, external_transfer,
                        transmitted_data_categories, timeout_seconds, max_retries,
                        retry_backoff_seconds, healthcheck_enabled, development_only,
                        created_by, id
                    ) SELECT deployment_id, version, display_name, description,
                        model_definition_id, provider, location, allowed_environments,
                        provider_model_id, endpoint_ref, capabilities, external_transfer,
                        transmitted_data_categories, timeout_seconds, max_retries,
                        retry_backoff_seconds, healthcheck_enabled, development_only,
                        created_by, %s
                    FROM rag_model_deployment_versions
                    LIMIT 1
                    """,
                    (uuid4(),),
                )
            connection.rollback()

            deployment_version_id = copied[2]
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                connection.execute(
                    "UPDATE rag_model_deployment_versions "
                    "SET display_name = 'changed' WHERE id = %s",
                    (deployment_version_id,),
                )
            connection.rollback()

            with pytest.raises(psycopg.errors.CheckViolation):
                connection.execute(
                    """
                    INSERT INTO rag_model_deployment_versions (
                        deployment_id, version, display_name, description,
                        model_definition_id, provider, location, allowed_environments,
                        provider_model_id, endpoint_ref, secret_ref, capabilities,
                        external_transfer, transmitted_data_categories, timeout_seconds,
                        max_retries, retry_backoff_seconds, healthcheck_enabled,
                        development_only, created_by, id
                    ) SELECT deployment_id, version + 1, display_name, description,
                        model_definition_id, provider, location, allowed_environments,
                        provider_model_id, endpoint_ref, 'sk-not-a-reference', capabilities,
                        external_transfer, transmitted_data_categories, timeout_seconds,
                        max_retries, retry_backoff_seconds, healthcheck_enabled,
                        development_only, created_by, %s
                    FROM rag_model_deployment_versions
                    LIMIT 1
                    """,
                    (uuid4(),),
                )
            connection.rollback()

            workspace_policy_id = uuid4()
            connection.execute(
                """
                INSERT INTO rag_workspace_data_policies (id, workspace_id)
                VALUES (%s, %s)
                """,
                (workspace_policy_id, ids["workspace"]),
            )
            connection.execute(
                """
                INSERT INTO rag_workspace_data_policy_versions (
                    id, policy_id, workspace_id, version, outbound_mode,
                    approved_providers, changed_by
                ) VALUES (%s, %s, %s, 1, 'deny', '[]'::json, %s)
                """,
                (uuid4(), workspace_policy_id, ids["workspace"], ids["owner"]),
            )
            connection.commit()
            with pytest.raises(psycopg.errors.UniqueViolation):
                connection.execute(
                    """
                    INSERT INTO rag_workspace_data_policy_versions (
                        id, policy_id, workspace_id, version, outbound_mode,
                        approved_providers, changed_by
                    ) VALUES (%s, %s, %s, 1, 'deny', '[]'::json, %s)
                    """,
                    (uuid4(), workspace_policy_id, ids["workspace"], ids["owner"]),
                )
            connection.rollback()

        command.downgrade(config, REVISION_0015)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                "SELECT generation_profile_id FROM rag_configuration_versions WHERE id = %s",
                (ids["configuration_version"],),
            ).fetchone() == before_configuration


def test_downgrade_rejects_configuration_referencing_deployment_bound_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_database(monkeypatch, "downgrade_guard") as (config, isolated_url):
        command.upgrade(config, REVISION_0015)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            ids = _insert_legacy_generation_fixture(connection)
        command.upgrade(config, REVISION_0016)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            deployment_profile_id = connection.execute(
                "SELECT profile_id FROM rag_generation_profile_deployments"
            ).fetchone()[0]
            second_answer_policy_id = uuid4()
            second_configuration_version_id = uuid4()
            connection.execute(
                """
                INSERT INTO rag_answer_policy_versions (
                    configuration_id, version, mode, min_semantic_score,
                    min_keyword_coverage, require_complete_provenance, conflict_mode, id
                ) VALUES (%s, 2, 'generative', 0, 0, true, 'separate_sources', %s)
                """,
                (ids["configuration"], second_answer_policy_id),
            )
            connection.execute(
                """
                INSERT INTO rag_configuration_versions (
                    configuration_id, version, indexing_profile_id, retrieval_profile_id,
                    generation_profile_id, answer_policy_version_id, evaluation_state,
                    is_default, id
                ) VALUES (%s, 2, %s, %s, %s, %s, 'draft', false, %s)
                """,
                (
                    ids["configuration"],
                    ids["indexing_profile"],
                    ids["retrieval_profile"],
                    deployment_profile_id,
                    second_answer_policy_id,
                    second_configuration_version_id,
                ),
            )
            connection.commit()

        with pytest.raises(RuntimeError, match="deployment-bound"):
            command.downgrade(config, REVISION_0015)


@pytest.mark.parametrize(
    "invalid_binding",
    [
        "non_generation_profile",
        "legacy_bound_profile",
        "referenced_profile",
        "opposite_model_binding",
    ],
)
def test_deployment_profile_binding_rejects_invalid_or_ambiguous_profiles(
    monkeypatch: pytest.MonkeyPatch,
    invalid_binding: str,
) -> None:
    with _isolated_database(monkeypatch, f"binding_{invalid_binding}") as (
        config,
        isolated_url,
    ):
        command.upgrade(config, REVISION_0015)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            ids = _insert_legacy_generation_fixture(connection)
        command.upgrade(config, REVISION_0016)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            copied_profile_id, deployment_version_id = connection.execute(
                "SELECT profile_id, deployment_version_id "
                "FROM rag_generation_profile_deployments"
            ).fetchone()
            referenced_profile_id = uuid4()
            if invalid_binding == "referenced_profile":
                referenced_configuration_id = uuid4()
                referenced_policy_id = uuid4()
                connection.execute(
                    """
                    INSERT INTO rag_profiles (
                        id, kind, name, version, config, evaluation_state, is_default
                    ) SELECT %s, 'generation', 'Referenced unbound profile', 1,
                             config, 'draft', false
                      FROM rag_profiles WHERE id = %s
                    """,
                    (referenced_profile_id, ids["generation_profile"]),
                )
                connection.execute(
                    """
                    INSERT INTO rag_configurations (id, owner_id, name, is_system)
                    VALUES (%s, %s, 'Referenced profile configuration', false)
                    """,
                    (referenced_configuration_id, ids["owner"]),
                )
                connection.execute(
                    """
                    INSERT INTO rag_answer_policy_versions (
                        id, configuration_id, version, mode, min_semantic_score,
                        min_keyword_coverage, require_complete_provenance, conflict_mode
                    ) VALUES (%s, %s, 1, 'extractive', 0, 0, true,
                              'separate_sources')
                    """,
                    (referenced_policy_id, referenced_configuration_id),
                )
                connection.execute(
                    """
                    INSERT INTO rag_configuration_versions (
                        id, configuration_id, version, indexing_profile_id,
                        retrieval_profile_id, generation_profile_id,
                        answer_policy_version_id, evaluation_state, is_default
                    ) VALUES (%s, %s, 1, %s, %s, NULL, %s, 'draft', false)
                    """,
                    (
                        uuid4(),
                        referenced_configuration_id,
                        referenced_profile_id,
                        ids["retrieval_profile"],
                        referenced_policy_id,
                    ),
                )
            with pytest.raises(psycopg.errors.RaiseException, match="binding"):
                if invalid_binding == "opposite_model_binding":
                    connection.execute(
                        """
                        INSERT INTO rag_profile_model_bindings (
                            id, profile_id, role, model_id
                        ) VALUES (%s, %s, 'llm', %s)
                        """,
                        (uuid4(), copied_profile_id, ids["llm"]),
                    )
                else:
                    profile_id = (
                        ids["indexing_profile"]
                        if invalid_binding == "non_generation_profile"
                        else (
                            referenced_profile_id
                            if invalid_binding == "referenced_profile"
                            else ids["generation_profile"]
                        )
                    )
                    connection.execute(
                        """
                        INSERT INTO rag_generation_profile_deployments (
                            profile_id, deployment_version_id
                        ) VALUES (%s, %s)
                        """,
                        (profile_id, deployment_version_id),
                    )


def test_legacy_conversion_accepts_180_character_targets_and_skips_181(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_database(monkeypatch, "legacy_lengths") as (config, isolated_url):
        command.upgrade(config, REVISION_0015)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            _insert_legacy_generation_fixture(
                connection,
                model_name="n" * 180,
                runtime_model="m" * 180,
            )
            connection.execute(
                """
                INSERT INTO rag_model_definitions (kind, name, version, config, id)
                VALUES ('llm', 'Unconvertible long runtime', 1, %s::json, %s)
                """,
                (
                    json.dumps(
                        {
                            "provider": "openai_compatible",
                            "data_policy": "local_only",
                            "runtime_model": "m" * 181,
                        }
                    ),
                    uuid4(),
                ),
            )
            connection.execute(
                """
                INSERT INTO rag_model_definitions (kind, name, version, config, id)
                VALUES ('llm', 'Unconvertible structured runtime', 1, %s::json, %s)
                """,
                (
                    json.dumps(
                        {
                            "provider": "openai_compatible",
                            "data_policy": "local_only",
                            "runtime_model": {"unexpected": "shape"},
                        }
                    ),
                    uuid4(),
                ),
            )
            connection.commit()

        command.upgrade(config, REVISION_0016)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM rag_model_deployment_versions"
            ).fetchone() == (1,)
            assert connection.execute(
                """
                SELECT char_length(display_name), char_length(provider_model_id)
                FROM rag_model_deployment_versions
                """
            ).fetchone() == (180, 180)


def test_secret_references_require_registered_provider_secret_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_database(monkeypatch, "secret_registry") as (config, isolated_url):
        command.upgrade(config, REVISION_0016)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            owner_id = uuid4()
            connection.execute(
                """
                INSERT INTO users (
                    display_name, email, normalized_email, password_hash,
                    role, is_active, id
                ) VALUES ('Secret Registry Owner', %s, %s, 'fixture-hash',
                          'owner', true, %s)
                """,
                (f"{owner_id}@example.test", f"{owner_id}@example.test", owner_id),
            )
            for literal in (
                "deadbeefdeadbeefdeadbeefdeadbeef",
                "QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
                "sk-not-a-reference",
            ):
                with (
                    pytest.raises(psycopg.errors.CheckViolation),
                    connection.transaction(),
                ):
                    connection.execute(
                            """
                            INSERT INTO rag_secret_references (
                                namespace, reference_name, created_by
                            ) VALUES ('provider_secret', %s, %s)
                            """,
                            (literal, owner_id),
                        )

            connection.execute(
                """
                INSERT INTO rag_secret_references (
                    namespace, reference_name, created_by
                ) VALUES ('provider_secret', 'openai-primary', %s)
                """,
                (owner_id,),
            )
            assert connection.execute(
                """
                SELECT namespace, reference_name
                FROM rag_secret_references
                WHERE namespace = 'provider_secret'
                  AND reference_name = 'openai-primary'
                """
            ).fetchone() == ("provider_secret", "openai-primary")
            model_id = uuid4()
            deployment_id = uuid4()
            connection.execute(
                """
                INSERT INTO rag_model_definitions (id, kind, name, version, config)
                VALUES (%s, 'llm', 'Secret FK model', 1, '{}'::json)
                """,
                (model_id,),
            )
            connection.execute(
                "INSERT INTO rag_model_deployments (id, created_by) VALUES (%s, %s)",
                (deployment_id, owner_id),
            )
            with (
                pytest.raises(psycopg.errors.ForeignKeyViolation),
                connection.transaction(),
            ):
                connection.execute(
                        """
                        INSERT INTO rag_model_deployment_versions (
                            id, deployment_id, version, display_name, description,
                            model_definition_id, provider, location,
                            allowed_environments, provider_model_id, endpoint_ref,
                            secret_ref_namespace, secret_ref, capabilities,
                            external_transfer, transmitted_data_categories,
                            data_processing_notice_ref, timeout_seconds, max_retries,
                            retry_backoff_seconds, healthcheck_enabled,
                            development_only, created_by
                        ) VALUES (
                            %s, %s, 1, 'Unregistered secret deployment', '', %s,
                            'openai_responses', 'external', '["development"]'::json,
                            'synthetic/model', 'openai-responses',
                            'provider_secret', 'openai-unregistered',
                            '["structured_output"]'::json, true, '["question"]'::json,
                            'notice-v1', 10, 0, 0, true, false, %s
                        )
                        """,
                        (uuid4(), deployment_id, model_id, owner_id),
                    )


def test_downgrade_refuses_unreferenced_user_created_deployment_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_database(monkeypatch, "downgrade_user_profile") as (
        config,
        isolated_url,
    ):
        command.upgrade(config, REVISION_0015)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            _insert_legacy_generation_fixture(connection)
        command.upgrade(config, REVISION_0016)
        user_profile_id = uuid4()
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            deployment_version_id = connection.execute(
                "SELECT deployment_version_id FROM rag_generation_profile_deployments"
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO rag_profiles (
                    id, kind, name, version, config, evaluation_state, is_default
                ) VALUES (
                    %s, 'generation', 'User deployment profile', 1,
                    %s::json, 'draft', false
                )
                """,
                (
                    user_profile_id,
                    json.dumps(
                        {
                            "prompt_ref": "answer-v1",
                            "context_prompt_ref": "contextualize-v1",
                            "citation_mode": "required",
                            "context_policy": {"max_prior_turns": 2},
                            "generation": {"max_output_tokens": 256},
                        }
                    ),
                ),
            )
            connection.execute(
                """
                INSERT INTO rag_generation_profile_deployments (
                    profile_id, deployment_version_id
                ) VALUES (%s, %s)
                """,
                (user_profile_id, deployment_version_id),
            )
            connection.commit()

        with pytest.raises(RuntimeError, match="user-created"):
            command.downgrade(config, REVISION_0015)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM rag_profiles WHERE id = %s",
                (user_profile_id,),
            ).fetchone() == (1,)


@pytest.mark.parametrize(
    "mismatch",
    [
        "deployment",
        "installation_policy",
        "missing_workspace",
        "extra_workspace",
        "workspace_policy",
    ],
)
def test_external_approval_rejects_non_exact_execution_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    with _isolated_database(monkeypatch, f"approval_{mismatch[:8]}") as (
        config,
        isolated_url,
    ):
        command.upgrade(config, REVISION_0015)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            ids = _insert_legacy_generation_fixture(connection)
        command.upgrade(config, REVISION_0016)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            approval_ids = _insert_external_approval_fixture(connection, ids)
            approval_id = uuid4()
            deployment_version_id = (
                approval_ids["legacy_local_deployment_version"]
                if mismatch == "deployment"
                else approval_ids["deployment_version"]
            )
            installation_policy_version_id = (
                approval_ids["seed_installation_policy_version"]
                if mismatch == "installation_policy"
                else approval_ids["installation_policy_version"]
            )
            connection.execute(
                """
                INSERT INTO rag_external_configuration_approvals (
                    id, configuration_version_id, deployment_version_id,
                    installation_policy_version_id, approved_by,
                    disclosure_version, created_at
                ) VALUES (%s, %s, %s, %s, %s, 'disclosure-v1', now())
                """,
                (
                    approval_id,
                    approval_ids["configuration_version"],
                    deployment_version_id,
                    installation_policy_version_id,
                    ids["owner"],
                ),
            )
            if mismatch != "missing_workspace":
                workspace_policy_version_id = (
                    approval_ids["workspace_policy_v1"]
                    if mismatch == "workspace_policy"
                    else approval_ids["workspace_policy_v2"]
                )
                connection.execute(
                    """
                    INSERT INTO rag_external_configuration_approval_workspaces (
                        approval_id, workspace_id, workspace_policy_version_id
                    ) VALUES (%s, %s, %s)
                    """,
                    (approval_id, ids["workspace"], workspace_policy_version_id),
                )
            if mismatch == "extra_workspace":
                connection.execute(
                    """
                    INSERT INTO rag_external_configuration_approval_workspaces (
                        approval_id, workspace_id, workspace_policy_version_id
                    ) VALUES (%s, %s, %s)
                    """,
                    (
                        approval_id,
                        approval_ids["extra_workspace"],
                        approval_ids["extra_workspace_policy_version"],
                    ),
                )

            with pytest.raises(psycopg.errors.RaiseException, match="approval"):
                connection.commit()


def test_external_approval_accepts_exact_external_execution_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_database(monkeypatch, "approval_exact") as (config, isolated_url):
        command.upgrade(config, REVISION_0015)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            ids = _insert_legacy_generation_fixture(connection)
        command.upgrade(config, REVISION_0016)
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            approval_ids = _insert_external_approval_fixture(connection, ids)
            approval_id = uuid4()
            connection.execute(
                """
                INSERT INTO rag_external_configuration_approvals (
                    id, configuration_version_id, deployment_version_id,
                    installation_policy_version_id, approved_by,
                    disclosure_version, created_at
                ) VALUES (%s, %s, %s, %s, %s, 'disclosure-v1', now())
                """,
                (
                    approval_id,
                    approval_ids["configuration_version"],
                    approval_ids["deployment_version"],
                    approval_ids["installation_policy_version"],
                    ids["owner"],
                ),
            )
            connection.execute(
                """
                INSERT INTO rag_external_configuration_approval_workspaces (
                    approval_id, workspace_id, workspace_policy_version_id
                ) VALUES (%s, %s, %s)
                """,
                (
                    approval_id,
                    ids["workspace"],
                    approval_ids["workspace_policy_v2"],
                ),
            )
            connection.commit()
            assert connection.execute(
                """
                SELECT count(*) FROM rag_external_configuration_approvals
                WHERE id = %s
                """,
                (approval_id,),
            ).fetchone() == (1,)
            connection.execute(
                """
                INSERT INTO rag_configuration_workspace_subscriptions (
                    id, configuration_version_id, workspace_id
                ) VALUES (%s, %s, %s)
                """,
                (
                    uuid4(),
                    approval_ids["configuration_version"],
                    approval_ids["extra_workspace"],
                ),
            )
            with pytest.raises(psycopg.errors.RaiseException, match="approval"):
                connection.commit()
