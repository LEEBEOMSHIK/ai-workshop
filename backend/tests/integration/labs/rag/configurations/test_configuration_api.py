import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import make_url

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.configurations.api import get_rag_configuration_service
from ai_workshop.labs.rag.configurations.domain import (
    AnswerPolicyVersion,
    SavedRagConfiguration,
)
from ai_workshop.labs.rag.configurations.service import (
    ConfigurationReadiness,
    ConfigurationSaveResult,
)
from ai_workshop.labs.rag.models.domain import EvaluationState
from ai_workshop.labs.rag.policies.repository import SqlAlchemyDataPolicyRepository
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.shared.errors import AppError
from alembic import command

ACTOR_ID = UUID("10000000-0000-0000-0000-000000000001")
MEMBER_ID = UUID("10000000-0000-0000-0000-000000000002")
BACKEND_ROOT = Path(__file__).resolve().parents[5]


def owner() -> User:
    return User(
        id=ACTOR_ID,
        display_name="Owner",
        email="owner@example.test",
        normalized_email="owner@example.test",
        password_hash="hash",
        role=UserRole.OWNER,
    )


def member() -> User:
    return User(
        id=MEMBER_ID,
        display_name="Member",
        email="member@example.test",
        normalized_email="member@example.test",
        password_hash="hash",
        role=UserRole.MEMBER,
    )


def _configuration(
    *,
    owner_id: UUID | None = ACTOR_ID,
    name: str = "내 구성",
    is_system: bool = False,
) -> SavedRagConfiguration:
    configuration_id = uuid4()
    version = 1
    policy = AnswerPolicyVersion.create(
        configuration_id=configuration_id,
        version=version,
        min_semantic_score=0.8,
        min_keyword_coverage=0.7,
        require_complete_provenance=True,
        conflict_mode="separate_sources",
    )
    indexing_profile_id = uuid4()
    return SavedRagConfiguration.create(
        configuration_id=configuration_id,
        configuration_version_id=uuid4(),
        owner_id=owner_id,
        name=name,
        version=version,
        indexing_profile_id=indexing_profile_id,
        retrieval_profile_id=uuid4(),
        retrieval_indexing_profile_id=indexing_profile_id,
        generation_profile_id=None,
        answer_policy_version=policy,
        workspace_ids=() if is_system else (uuid4(),),
        evaluation_state=EvaluationState.PENDING,
        is_system=is_system,
        is_default=False,
    )


class FakeConfigurationService:
    def __init__(
        self,
        configurations: list[SavedRagConfiguration],
        *,
        actor_id: UUID = ACTOR_ID,
    ) -> None:
        self.configurations = configurations
        self.actor_id = actor_id
        self.created: dict[str, object] | None = None

    async def list(self, actor_id: UUID) -> list[SavedRagConfiguration]:
        assert actor_id == self.actor_id
        return self.configurations

    async def search_readiness(
        self, configurations: tuple[SavedRagConfiguration, ...]
    ) -> dict[UUID, bool]:
        return {configuration.version_id: True for configuration in configurations}

    async def readiness(
        self, configurations: tuple[SavedRagConfiguration, ...]
    ) -> dict[UUID, ConfigurationReadiness]:
        return {
            configuration.version_id: ConfigurationReadiness(
                search_ready=True,
                answer_ready=False,
                service_ready=False,
                answer_reasons=("generation_not_configured",),
            )
            for configuration in configurations
        }

    async def create(self, **values: object) -> ConfigurationSaveResult:
        assert values["owner_id"] == self.actor_id
        self.created = values
        configuration = self.configurations[-1]
        return ConfigurationSaveResult(configuration, (uuid4(), uuid4()))

    async def detail(
        self, configuration_id: UUID, actor_id: UUID
    ) -> SavedRagConfiguration:
        assert actor_id == self.actor_id
        for configuration in self.configurations:
            if configuration.id == configuration_id:
                return configuration
        raise AppError("not_found", "The requested resource was not found.", 404)

    async def promote_default(
        self, configuration_id: UUID, actor_id: UUID
    ) -> SavedRagConfiguration:
        await self.detail(configuration_id, actor_id)
        raise AppError(
            "evaluation_policy_required",
            "An applicable versioned Evaluation Policy and passing result are required.",
            409,
        )


def _client(service: FakeConfigurationService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = owner
    app.dependency_overrides[get_rag_configuration_service] = lambda: service
    return TestClient(app)


def _member_client(service: FakeConfigurationService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = member
    app.dependency_overrides[get_rag_configuration_service] = lambda: service
    return TestClient(app)


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(
        hide_password=False
    )


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def isolated_configuration_database(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    base_settings = get_settings()
    database = f"ai_workshop_t5_configuration_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    administrative = _database_url(base_settings.database_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        monkeypatch.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
        get_settings.cache_clear()
        command.upgrade(
            Config(str(BACKEND_ROOT / "alembic.ini")),
            "0016_rag_llm_deployments",
        )
        yield isolated_url
    finally:
        get_settings.cache_clear()
        with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )


def seed_external_configuration_contract(isolated_url: str) -> dict[str, UUID]:
    ids = {
        name: uuid4()
        for name in (
            "workspace",
            "embedding_model",
            "llm_model",
            "indexing_profile",
            "retrieval_profile",
            "generation_profile",
            "legacy_generation_profile",
            "deployment",
            "deployment_version",
            "workspace_policy",
            "workspace_policy_version",
            "legacy_configuration",
            "legacy_answer_policy",
            "legacy_configuration_version",
        )
    }
    generation_config = {
        "prompt_ref": "rag-answer-v1",
        "context_prompt_ref": "rag-contextualize-v1",
        "citation_mode": "required",
        "context_policy": {"max_history_turns": 6, "max_history_tokens": 1024},
        "generation": {
            "timeout_seconds": 30,
            "max_output_tokens": 512,
            "temperature": 0.1,
            "response_schema_version": 1,
        },
    }
    with psycopg.connect(_sync_url(isolated_url)) as connection:
        connection.execute(
            """
            INSERT INTO users (
                id, display_name, email, normalized_email, password_hash,
                role, is_active
            ) VALUES (%s, 'Owner', 'owner@example.test', 'owner@example.test',
                      'synthetic-hash', 'owner', true)
            """,
            (ACTOR_ID,),
        )
        connection.execute(
            "INSERT INTO workspaces (id, name, kind, created_by) "
            "VALUES (%s, 'Synthetic workspace', 'personal', %s)",
            (ids["workspace"], ACTOR_ID),
        )
        connection.execute(
            "INSERT INTO workspace_memberships (id, workspace_id, user_id, role) "
            "VALUES (%s, %s, %s, 'owner')",
            (uuid4(), ids["workspace"], ACTOR_ID),
        )
        for model_id, kind, name, config in (
            (ids["embedding_model"], "embedding", "Synthetic embedding", {}),
            (ids["llm_model"], "llm", "Synthetic LLM", {}),
        ):
            connection.execute(
                "INSERT INTO rag_model_definitions "
                "(id, kind, name, version, config) VALUES (%s, %s, %s, 1, %s::json)",
                (model_id, kind, name, json.dumps(config)),
            )
        for profile_id, kind, name, config in (
            (
                ids["indexing_profile"],
                "indexing",
                "Synthetic indexing",
                {"chunker": {"name": "structure"}},
            ),
            (
                ids["retrieval_profile"],
                "retrieval",
                "Synthetic retrieval",
                {
                    "bm25": {"top_k": 30},
                    "indexing_profile_id": str(ids["indexing_profile"]),
                },
            ),
            (
                ids["generation_profile"],
                "generation",
                "External generation",
                generation_config,
            ),
            (
                ids["legacy_generation_profile"],
                "generation",
                "Legacy generation",
                generation_config,
            ),
        ):
            connection.execute(
                "INSERT INTO rag_profiles "
                "(id, kind, name, version, config, evaluation_state, is_default) "
                "VALUES (%s, %s, %s, 1, %s::json, 'draft', false)",
                (profile_id, kind, name, json.dumps(config)),
            )
        connection.execute(
            "INSERT INTO rag_profile_model_bindings "
            "(id, profile_id, role, model_id) VALUES (%s, %s, 'embedding', %s)",
            (uuid4(), ids["indexing_profile"], ids["embedding_model"]),
        )
        connection.execute(
            "INSERT INTO rag_profile_model_bindings "
            "(id, profile_id, role, model_id) VALUES (%s, %s, 'llm', %s)",
            (uuid4(), ids["legacy_generation_profile"], ids["llm_model"]),
        )
        connection.execute(
            "UPDATE rag_profiles SET evaluation_state = 'passed', is_default = true "
            "WHERE id = %s",
            (ids["generation_profile"],),
        )
        connection.execute(
            "UPDATE rag_profiles SET evaluation_state = 'passed' WHERE id = %s",
            (ids["legacy_generation_profile"],),
        )
        connection.execute(
            "INSERT INTO rag_secret_references "
            "(namespace, reference_name, created_by) "
            "VALUES ('provider_secret', 'openai-primary', %s)",
            (ACTOR_ID,),
        )
        connection.execute(
            "INSERT INTO rag_model_deployments (id, created_by) VALUES (%s, %s)",
            (ids["deployment"], ACTOR_ID),
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
                %s, %s, 1, 'External generation', 'Synthetic', %s,
                'openai_responses', 'external', '["development"]'::json,
                'exact-provider-model', 'openai-responses', 'provider_secret',
                'openai-primary', '["structured_output"]'::json, true,
                '["question", "evidence"]'::json, 'public-notice-v1',
                30, 1, 0.5, true, false, %s
            )
            """,
            (
                ids["deployment_version"],
                ids["deployment"],
                ids["llm_model"],
                ACTOR_ID,
            ),
        )
        connection.execute(
            "INSERT INTO rag_generation_profile_deployments "
            "(profile_id, deployment_version_id) VALUES (%s, %s)",
            (ids["generation_profile"], ids["deployment_version"]),
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
            (uuid4(), installation_policy_id, ACTOR_ID),
        )
        connection.execute(
            "INSERT INTO rag_workspace_data_policies (id, workspace_id) VALUES (%s, %s)",
            (ids["workspace_policy"], ids["workspace"]),
        )
        connection.execute(
            """
            INSERT INTO rag_workspace_data_policy_versions (
                id, policy_id, workspace_id, version, outbound_mode,
                approved_providers, changed_by
            ) VALUES (%s, %s, %s, 1, 'approved_providers',
                      '["openai_responses"]'::json, %s)
            """,
            (
                ids["workspace_policy_version"],
                ids["workspace_policy"],
                ids["workspace"],
                ACTOR_ID,
            ),
        )
        connection.execute(
            "INSERT INTO rag_configurations (id, owner_id, name, is_system) "
            "VALUES (%s, %s, 'Legacy saved configuration', false)",
            (ids["legacy_configuration"], ACTOR_ID),
        )
        connection.execute(
            """
            INSERT INTO rag_answer_policy_versions (
                id, configuration_id, version, mode, min_semantic_score,
                min_keyword_coverage, require_complete_provenance, conflict_mode
            ) VALUES (%s, %s, 1, 'generative', 0.8, 0.7, true,
                      'separate_sources')
            """,
            (ids["legacy_answer_policy"], ids["legacy_configuration"]),
        )
        connection.execute(
            """
            INSERT INTO rag_configuration_versions (
                id, configuration_id, version, indexing_profile_id,
                retrieval_profile_id, generation_profile_id,
                answer_policy_version_id, evaluation_state, is_default
            ) VALUES (%s, %s, 1, %s, %s, %s, %s, 'draft', false)
            """,
            (
                ids["legacy_configuration_version"],
                ids["legacy_configuration"],
                ids["indexing_profile"],
                ids["retrieval_profile"],
                ids["legacy_generation_profile"],
                ids["legacy_answer_policy"],
            ),
        )
        connection.execute(
            "INSERT INTO rag_configuration_workspace_subscriptions "
            "(id, configuration_version_id, workspace_id) VALUES (%s, %s, %s)",
            (uuid4(), ids["legacy_configuration_version"], ids["workspace"]),
        )
        connection.commit()
    return ids


def test_list_exposes_only_the_supplied_system_baseline_and_actor_configurations() -> None:
    baseline = _configuration(owner_id=None, name="BM25 기준선", is_system=True)
    own = _configuration()
    service = FakeConfigurationService([baseline, own])

    with _client(service) as client:
        response = client.get("/api/v1/rag/configurations")

    assert response.status_code == 200
    payload = response.json()
    assert [item["name"] for item in payload] == ["BM25 기준선", "내 구성"]
    assert payload[0]["evaluation_state"] == "pending"
    assert payload[0]["is_default"] is False
    assert payload[0]["experimental"] is True
    assert payload[0]["generation_profile_id"] is None
    assert payload[0]["search_ready"] is True
    assert payload[0]["answer_ready"] is False
    assert payload[0]["service_ready"] is False
    assert payload[0]["answer_reasons"] == ["generation_not_configured"]


def test_create_accepts_extractive_policy_and_leaves_dispatch_to_the_outbox() -> None:
    workspace_id = uuid4()
    indexing_profile_id = uuid4()
    retrieval_profile_id = uuid4()
    saved = _configuration()
    service = FakeConfigurationService([saved])

    with _client(service) as client:
        response = client.post(
            "/api/v1/rag/configurations",
            json={
                "name": "내 구성",
                "indexing_profile_id": str(indexing_profile_id),
                "retrieval_profile_id": str(retrieval_profile_id),
                "generation_profile_id": None,
                "answer_policy": {
                    "min_semantic_score": 0.8,
                    "min_keyword_coverage": 0.7,
                    "require_complete_provenance": True,
                    "conflict_mode": "separate_sources",
                },
                "workspace_ids": [str(workspace_id)],
            },
        )

    assert response.status_code == 201
    assert response.json()["id"] == str(saved.id)
    assert service.created == {
        "owner_id": ACTOR_ID,
        "name": "내 구성",
        "indexing_profile_id": indexing_profile_id,
        "retrieval_profile_id": retrieval_profile_id,
        "generation_profile_id": None,
        "answer_mode": "extractive",
        "min_semantic_score": 0.8,
        "min_keyword_coverage": 0.7,
        "require_complete_provenance": True,
        "conflict_mode": "separate_sources",
        "workspace_ids": (workspace_id,),
        "external_transfer_approval": None,
    }


def test_external_approval_schema_is_exact_and_forwarded_server_side() -> None:
    saved = _configuration()
    service = FakeConfigurationService([saved])
    request = {
        "name": "외부 구성",
        "indexing_profile_id": str(uuid4()),
        "retrieval_profile_id": str(uuid4()),
        "generation_profile_id": str(uuid4()),
        "answer_policy": {
            "mode": "generative",
            "min_semantic_score": 0.8,
            "min_keyword_coverage": 0.7,
            "require_complete_provenance": True,
            "conflict_mode": "separate_sources",
        },
        "workspace_ids": [str(uuid4())],
        "external_transfer_approval": {
            "confirmed": True,
            "disclosure_version": "external-generation-v1",
        },
    }

    with _client(service) as client:
        accepted = client.post("/api/v1/rag/configurations", json=request)
        rejected_confirmation = client.post(
            "/api/v1/rag/configurations",
            json={
                **request,
                "external_transfer_approval": {
                    "confirmed": False,
                    "disclosure_version": "external-generation-v1",
                },
            },
        )
        rejected_disclosure = client.post(
            "/api/v1/rag/configurations",
            json={
                **request,
                "external_transfer_approval": {
                    "confirmed": True,
                    "disclosure_version": "stale-disclosure",
                },
            },
        )
        rejected_client_snapshots = [
            client.post(
                "/api/v1/rag/configurations",
                json={
                    **request,
                    "external_transfer_approval": {
                        **request["external_transfer_approval"],
                        **extra,
                    },
                },
            )
            for extra in (
                {"deployment_version_id": str(uuid4())},
                {"installation_policy_version_id": str(uuid4())},
                {"workspace_policy_snapshots": []},
                {
                    "workspace_policy_snapshots": [
                        {
                            "workspace_id": str(uuid4()),
                            "workspace_policy_version_id": str(uuid4()),
                        }
                    ]
                },
            )
        ]

    assert accepted.status_code == 201
    assert service.created is not None
    approval = service.created["external_transfer_approval"]
    assert approval is not None
    assert approval.confirmed is True
    assert approval.disclosure_version == "external-generation-v1"
    assert rejected_confirmation.status_code == 422
    assert rejected_disclosure.status_code == 422
    assert [response.status_code for response in rejected_client_snapshots] == [
        422,
        422,
        422,
        422,
    ]


def test_detail_and_default_are_nondisclosing_or_fail_closed() -> None:
    saved = _configuration()
    service = FakeConfigurationService([saved])

    with _client(service) as client:
        detail = client.get(f"/api/v1/rag/configurations/{saved.id}")
        missing = client.get(f"/api/v1/rag/configurations/{uuid4()}")
        promotion = client.post(f"/api/v1/rag/configurations/{saved.id}/default")

    assert detail.status_code == 200
    assert detail.json()["version_id"] == str(saved.version_id)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert promotion.status_code == 409
    assert promotion.json()["error"]["code"] == "evaluation_policy_required"


def test_member_cannot_create_or_promote_configuration() -> None:
    saved = _configuration(owner_id=MEMBER_ID)
    service = FakeConfigurationService([saved], actor_id=MEMBER_ID)

    with _member_client(service) as client:
        created = client.post(
            "/api/v1/rag/configurations",
            json={
                "name": "member configuration",
                "indexing_profile_id": str(uuid4()),
                "retrieval_profile_id": str(uuid4()),
                "generation_profile_id": None,
                "answer_policy": {
                    "min_semantic_score": 0.8,
                    "min_keyword_coverage": 0.7,
                    "require_complete_provenance": True,
                    "conflict_mode": "separate_sources",
                },
                "workspace_ids": [str(uuid4())],
            },
        )
        promoted = client.post(
            f"/api/v1/rag/configurations/{saved.id}/default"
        )
        external = client.post(
            "/api/v1/rag/configurations",
            json={
                "name": "member external configuration",
                "indexing_profile_id": str(uuid4()),
                "retrieval_profile_id": str(uuid4()),
                "generation_profile_id": str(uuid4()),
                "answer_policy": {
                    "mode": "generative",
                    "min_semantic_score": 0.8,
                    "min_keyword_coverage": 0.7,
                    "require_complete_provenance": True,
                    "conflict_mode": "separate_sources",
                },
                "workspace_ids": [str(uuid4())],
                "external_transfer_approval": {
                    "confirmed": True,
                    "disclosure_version": "external-generation-v1",
                },
            },
        )

    assert created.status_code == 403
    assert created.json()["error"]["code"] == "owner_required"
    assert promoted.status_code == 403
    assert promoted.json()["error"]["code"] == "owner_required"
    assert external.status_code == 403
    assert external.json()["error"]["code"] == "owner_required"


def test_postgresql_external_save_is_atomic_and_preserves_legacy_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_configuration_database(monkeypatch) as isolated_url:
        ids = seed_external_configuration_contract(isolated_url)
        app = create_app()
        app.dependency_overrides[get_current_user] = owner
        generation_config = {
            "prompt_ref": "rag-answer-v1",
            "context_prompt_ref": "rag-contextualize-v1",
            "citation_mode": "required",
            "context_policy": {
                "max_history_turns": 6,
                "max_history_tokens": 1024,
            },
            "generation": {
                "timeout_seconds": 30,
                "max_output_tokens": 512,
                "temperature": 0.1,
                "response_schema_version": 1,
            },
        }
        with TestClient(app) as client:
            created_profile = client.post(
                "/api/v1/admin/rag/profiles/generation",
                json={
                    "name": "API exact Deployment generation",
                    "version": 1,
                    "config": generation_config,
                    "bindings": [],
                    "deployment_version_id": str(ids["deployment_version"]),
                    "evaluation_state": "draft",
                },
            )
            profiles = client.get("/api/v1/rag/profiles/generation")
            legacy_admin_promotion = client.post(
                "/api/v1/admin/rag/profiles/"
                f"{ids['legacy_generation_profile']}/default"
            )
            legacy_compat_promotion = client.post(
                f"/api/v1/rag/profiles/{ids['legacy_generation_profile']}/default"
            )

        assert created_profile.status_code == 201, created_profile.text
        assert created_profile.json()["deployment_version_id"] == str(
            ids["deployment_version"]
        )
        assert created_profile.json()["legacy"] is False
        assert created_profile.json()["readiness"] == {
            "ready": False,
            "reason_codes": ["deployment_not_ready"],
        }
        legacy_profile = next(
            item
            for item in profiles.json()
            if item["id"] == str(ids["legacy_generation_profile"])
        )
        assert legacy_profile["legacy"] is True
        assert legacy_profile["deployment_version_id"] is None
        assert legacy_profile["readiness"]["reason_codes"] == [
            "deployment_not_ready"
        ]
        for rejected in (legacy_admin_promotion, legacy_compat_promotion):
            assert rejected.status_code == 409
            assert rejected.json()["error"]["code"] == "legacy_profile_read_only"
        payload = {
            "name": "External approved configuration",
            "indexing_profile_id": str(ids["indexing_profile"]),
            "retrieval_profile_id": str(ids["retrieval_profile"]),
            "generation_profile_id": created_profile.json()["id"],
            "answer_policy": {
                "mode": "generative",
                "min_semantic_score": 0.8,
                "min_keyword_coverage": 0.7,
                "require_complete_provenance": True,
                "conflict_mode": "separate_sources",
            },
            "workspace_ids": [str(ids["workspace"])],
            "external_transfer_approval": {
                "confirmed": True,
                "disclosure_version": "external-generation-v1",
            },
        }

        with TestClient(app) as client:
            saved = client.post("/api/v1/rag/configurations", json=payload)
            listed = client.get("/api/v1/rag/configurations")

        assert saved.status_code == 201, saved.text
        assert saved.json()["answer_ready"] is False
        assert saved.json()["answer_reasons"] == ["deployment_not_ready"]
        assert saved.json()["generation_execution_preview"] == {
            "provider": "openai_responses",
            "model_name": "Synthetic LLM",
            "model_version": 1,
            "deployment_name": "External generation",
            "location": "external",
            "external_transfer": True,
            "disclosure": (
                "OpenAI 외부 API로 현재 질문, 제한된 이전 대화와 선별된 문서 근거가 "
                "전송됩니다."
            ),
        }
        serialized_saved = json.dumps(
            saved.json()["generation_execution_preview"], ensure_ascii=False
        )
        for internal_value in (
            str(ids["deployment_version"]),
            str(ids["llm_model"]),
            created_profile.json()["id"],
            "exact-provider-model",
            "openai-responses",
            "openai-primary",
            "public-notice-v1",
        ):
            assert internal_value not in serialized_saved
        legacy = next(
            item
            for item in listed.json()
            if item["name"] == "Legacy saved configuration"
        )
        assert legacy["generation_profile_id"] == str(
            ids["legacy_generation_profile"]
        )
        assert legacy["answer_ready"] is False
        assert legacy["answer_reasons"] == ["deployment_not_ready"]

        configuration_version_id = UUID(saved.json()["version_id"])
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            approval = connection.execute(
                """
                SELECT deployment_version_id, installation_policy_version_id,
                       approved_by, disclosure_version
                  FROM rag_external_configuration_approvals
                 WHERE configuration_version_id = %s
                """,
                (configuration_version_id,),
            ).fetchone()
            current_installation_id = connection.execute(
                "SELECT id FROM rag_installation_data_policy_versions "
                "ORDER BY version DESC LIMIT 1"
            ).fetchone()[0]
            snapshot = connection.execute(
                """
                SELECT workspace_id, workspace_policy_version_id
                  FROM rag_external_configuration_approval_workspaces
                """
            ).fetchall()
            assert approval == (
                ids["deployment_version"],
                current_installation_id,
                ACTOR_ID,
                "external-generation-v1",
            )
            assert snapshot == [
                (ids["workspace"], ids["workspace_policy_version"])
            ]
            assert connection.execute(
                "SELECT generation_profile_id FROM rag_configuration_versions "
                "WHERE id = %s",
                (ids["legacy_configuration_version"],),
            ).fetchone() == (ids["legacy_generation_profile"],)
            assert connection.execute(
                "SELECT model_id FROM rag_profile_model_bindings "
                "WHERE profile_id = %s",
                (ids["legacy_generation_profile"],),
            ).fetchone() == (ids["llm_model"],)
            assert connection.execute(
                "SELECT id, is_default FROM rag_profiles "
                "WHERE kind = 'generation' AND is_default ORDER BY id"
            ).fetchall() == [(ids["generation_profile"], True)]
            assert connection.execute(
                "SELECT evaluation_state, is_default FROM rag_profiles WHERE id = %s",
                (ids["legacy_generation_profile"],),
            ).fetchone() == ("passed", False)

        original_add_approval = SqlAlchemyDataPolicyRepository.add_external_approval

        async def reject_stale_approval(self, approval):
            del self, approval
            raise ValueError("synthetic concurrent policy change")

        monkeypatch.setattr(
            SqlAlchemyDataPolicyRepository,
            "add_external_approval",
            reject_stale_approval,
        )
        with TestClient(app) as client:
            rolled_back = client.post(
                "/api/v1/rag/configurations",
                json={**payload, "name": "Rolled back external configuration"},
            )
        monkeypatch.setattr(
            SqlAlchemyDataPolicyRepository,
            "add_external_approval",
            original_add_approval,
        )

        assert rolled_back.status_code == 409
        assert rolled_back.json()["error"]["code"] == "external_approval_stale"
        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM rag_configurations "
                "WHERE name = 'Rolled back external configuration'"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT count(*) FROM rag_answer_policy_versions ap "
                "JOIN rag_configurations c ON c.id = ap.configuration_id "
                "WHERE c.name = 'Rolled back external configuration'"
            ).fetchone() == (0,)

        with (
            pytest.raises(psycopg.errors.RaiseException),
            psycopg.connect(_sync_url(isolated_url)) as connection,
        ):
            connection.execute(
                "INSERT INTO rag_generation_profile_deployments "
                "(profile_id, deployment_version_id) VALUES (%s, %s)",
                (
                    ids["legacy_generation_profile"],
                    ids["deployment_version"],
                ),
            )

        with psycopg.connect(_sync_url(isolated_url)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM rag_generation_profile_deployments "
                "WHERE profile_id = %s",
                (ids["legacy_generation_profile"],),
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT count(*) FROM rag_profile_model_bindings "
                "WHERE profile_id = %s",
                (ids["legacy_generation_profile"],),
            ).fetchone() == (1,)
