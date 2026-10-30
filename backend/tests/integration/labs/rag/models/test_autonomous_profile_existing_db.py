"""Opt-in v2 profile JSON round-trip; existing DB only, no inference or durable writes."""

import os
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker

import ai_workshop.main  # noqa: F401 -- register existing SQLAlchemy mappings
from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
from ai_workshop.labs.rag.models.domain import EvaluationState, ProfileKind, thaw_json
from ai_workshop.labs.rag.models.orchestration_policy import resolve_orchestration_policy
from ai_workshop.labs.rag.models.repository import SqlAlchemyModelRegistryRepository
from ai_workshop.labs.rag.models.service import RagModelRegistryService
from ai_workshop.shared.db import create_engine
from ai_workshop.shared.errors import AppError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_AUTONOMOUS_PROFILE_EXISTING_DB") != "1",
        reason="Explicit original database rollback verification is required.",
    ),
]

_TABLES = {
    "rag_profiles": "id",
    "rag_profile_model_bindings": "profile_id",
    "rag_generation_profile_deployments": "profile_id",
    "rag_configuration_versions": None,
    "rag_domains": None,
    "rag_domain_connection_versions": None,
    "rag_generative_runs": None,
    "rag_generation_execution_audits": None,
}


async def _fingerprints(
    connection: AsyncConnection, synthetic_profile: UUID | None = None,
) -> tuple[object, ...]:
    values = []
    for table, profile_column in _TABLES.items():
        where = (
            f" WHERE {profile_column} <> :profile"
            if synthetic_profile is not None and profile_column is not None else ""
        )
        values.append(await connection.scalar(text(
            "SELECT count(*)::text || ':' || "
            "md5(coalesce(string_agg(md5(row_to_json(t)::text), '' "
            "ORDER BY md5(row_to_json(t)::text)), '')) FROM " + table + " t" + where
        ), {"profile": synthetic_profile}))
    return tuple(values)


async def test_autonomous_v2_profile_survives_json_round_trip_without_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in list(os.environ):
        if key.upper().startswith("AI_WORKSHOP_"):
            monkeypatch.delenv(key)
    engine = create_engine(load_original_settings(Path(__file__).resolve().parents[6]))
    engine.sync_engine.hide_parameters = True

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(_connection: Connection) -> None:
        raise AssertionError("Autonomous profile verification must never COMMIT.")

    profile_id: UUID | None = None
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            before = await _fingerprints(connection)
            try:
                baseline_id = await connection.scalar(text("""SELECT p.id FROM rag_domains d
                    JOIN rag_domain_connection_versions c ON c.id=d.active_connection_version_id
                    JOIN rag_configuration_versions v ON v.id=c.configuration_version_id
                    JOIN rag_profiles p ON p.id=v.generation_profile_id
                    WHERE p.kind='generation' ORDER BY d.created_at LIMIT 1"""))
                if baseline_id is None:
                    pytest.skip("An existing active generation profile is required; create none.")
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
                )
                expected = {
                    "engine": "openai_agents", "version": 2,
                    "local_http_api": "ollama_chat", "dispatch_mode": "autonomous_handoffs",
                    "max_model_calls": 6, "max_tool_calls": 5, "max_total_output_tokens": 1800,
                }
                async with sessions.begin() as session:
                    repository = SqlAlchemyModelRegistryRepository(session)
                    baseline = await repository.find_profile(baseline_id)
                    assert baseline is not None and baseline.deployment_version_id is not None
                    config = thaw_json(baseline.config)
                    assert isinstance(config, dict)
                    original_config = deepcopy(config)
                    config["orchestration"] = expected
                    candidate = await RagModelRegistryService(repository).register_profile(
                        kind=ProfileKind.GENERATION,
                        name=f"synthetic-autonomous-rollback-{uuid4().hex}", version=1,
                        config=config, bindings=(),
                        deployment_version_id=baseline.deployment_version_id,
                    )
                    profile_id = candidate.id
                    assert candidate.evaluation_state is EvaluationState.DRAFT
                    assert candidate.is_default is False
                raw = (await connection.execute(text("""SELECT config,evaluation_state,is_default
                    FROM rag_profiles WHERE id=:id"""), {"id": profile_id})).mappings().one()
                assert raw["config"]["orchestration"] == expected
                assert raw["evaluation_state"] == "draft" and raw["is_default"] is False
                assert {k: v for k, v in raw["config"].items() if k != "orchestration"} == {
                    k: v for k, v in original_config.items() if k != "orchestration"
                }
                async with sessions.begin() as session:
                    repository = SqlAlchemyModelRegistryRepository(session)
                    restored = await repository.find_profile(profile_id)
                    assert restored is not None
                    assert restored.evaluation_state is EvaluationState.DRAFT
                    assert restored.is_default is False
                    assert restored.deployment_version_id == baseline.deployment_version_id
                    policy = resolve_orchestration_policy(restored.config)
                    assert policy is not None
                    assert policy.version == 2 and policy.dispatch_mode == "autonomous_handoffs"
                    assert (policy.max_model_calls, policy.max_tool_calls,
                            policy.max_total_output_tokens) == (6, 5, 1800)
                    with pytest.raises(AppError) as denied:
                        await RagModelRegistryService(repository).promote_default(profile_id)
                    assert denied.value.status_code == 409
                    assert denied.value.code == "profile_not_evaluated"
                    unchanged = await repository.find_profile(baseline_id)
                    assert unchanged == baseline
                assert await _fingerprints(connection, profile_id) == before
            finally:
                await transaction.rollback()
                assert await _fingerprints(connection) == before
                if profile_id is not None:
                    for table, column in _TABLES.items():
                        if column is not None:
                            assert await connection.scalar(text(
                                f"SELECT count(*) FROM {table} WHERE {column}=:id"
                            ), {"id": profile_id}) == 0
                await connection.rollback()
    finally:
        await engine.dispose()
