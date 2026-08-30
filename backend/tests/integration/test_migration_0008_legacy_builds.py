import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import make_url, text

from ai_workshop.config import Settings, get_settings
from ai_workshop.shared.db import create_engine
from alembic import command

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REVISION_0007 = "0007_rag_ingestion_jobs"
REVISION_0008 = "0008_rag_embedding_artifacts"


@dataclass(frozen=True, slots=True)
class LegacyFixtureIds:
    user_id: UUID
    workspace_id: UUID
    document_id: UUID
    asset_id: UUID
    profile_id: UUID
    projection_id: UUID
    job_id: UUID
    build_ids: tuple[UUID, UUID, UUID]
    survivor_id: UUID


def _fixture_ids() -> LegacyFixtureIds:
    builds = (uuid4(), uuid4(), uuid4())
    return LegacyFixtureIds(
        user_id=uuid4(),
        workspace_id=uuid4(),
        document_id=uuid4(),
        asset_id=uuid4(),
        profile_id=uuid4(),
        projection_id=uuid4(),
        job_id=uuid4(),
        build_ids=builds,
        survivor_id=builds[1],
    )


def _alembic_config() -> Config:
    return Config(str(BACKEND_ROOT / "alembic.ini"))


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def _administrative_dsn(base_url: str) -> str:
    return _database_url(base_url, "postgres").replace(
        "postgresql+psycopg://", "postgresql://", 1
    )


def _create_database(base_url: str, database: str) -> None:
    with psycopg.connect(_administrative_dsn(base_url), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))


def _drop_database(base_url: str, database: str) -> None:
    with psycopg.connect(_administrative_dsn(base_url), autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
        )


async def _seed_populated_0007(settings: Settings, ids: LegacyFixtureIds) -> None:
    engine = create_engine(settings)
    oldest = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO users (
                        display_name, email, normalized_email, password_hash,
                        role, is_active, id
                    ) VALUES (
                        'Migration Owner', :email, :email, 'synthetic-hash',
                        'owner', true, :user_id
                    )
                    """
                ),
                {"email": f"migration-{ids.user_id}@example.test", "user_id": ids.user_id},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO workspaces (name, kind, created_by, expires_at, id)
                    VALUES (:name, 'personal', :user_id, NULL, :workspace_id)
                    """
                ),
                {
                    "name": f"Migration Workspace {ids.workspace_id}",
                    "user_id": ids.user_id,
                    "workspace_id": ids.workspace_id,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO documents (
                        workspace_id, folder_id, name, active_version_id, id
                    ) VALUES (:workspace_id, NULL, :name, NULL, :document_id)
                    """
                ),
                {
                    "workspace_id": ids.workspace_id,
                    "name": f"migration-{ids.document_id}.txt",
                    "document_id": ids.document_id,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO asset_versions (
                        document_id, number, object_key, sha256, media_type,
                        size, status, id
                    ) VALUES (
                        :document_id, 1, :object_key, :sha256, 'text/plain',
                        1, 'stored', :asset_id
                    )
                    """
                ),
                {
                    "document_id": ids.document_id,
                    "object_key": f"synthetic/migration-{ids.asset_id}.txt",
                    "sha256": "0" * 64,
                    "asset_id": ids.asset_id,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO rag_profiles (
                        kind, name, version, config, evaluation_state,
                        is_default, id
                    ) VALUES (
                        'indexing', :name, 1, CAST('{}' AS json), 'draft',
                        false, :profile_id
                    )
                    """
                ),
                {
                    "name": f"migration-profile-{ids.profile_id}",
                    "profile_id": ids.profile_id,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO rag_document_projections (
                        asset_version_id, indexing_profile_id, status, id
                    ) VALUES (:asset_id, :profile_id, 'pending', :projection_id)
                    """
                ),
                {
                    "asset_id": ids.asset_id,
                    "profile_id": ids.profile_id,
                    "projection_id": ids.projection_id,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO jobs (
                        user_id, workspace_id, asset_version_id, type,
                        idempotency_key, status, stage, attempt, id
                    ) VALUES (
                        :user_id, :workspace_id, :asset_id, 'rag_ingestion',
                        :idempotency_key, 'pending', 'pending', 0, :job_id
                    )
                    """
                ),
                {
                    "user_id": ids.user_id,
                    "workspace_id": ids.workspace_id,
                    "asset_id": ids.asset_id,
                    "idempotency_key": f"migration-{ids.job_id}",
                    "job_id": ids.job_id,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO rag_ingestion_jobs (
                        job_id, projection_id, asset_version_id,
                        indexing_profile_id, requested_by
                    ) VALUES (
                        :job_id, :projection_id, :asset_id, :profile_id, :user_id
                    )
                    """
                ),
                {
                    "job_id": ids.job_id,
                    "projection_id": ids.projection_id,
                    "asset_id": ids.asset_id,
                    "profile_id": ids.profile_id,
                    "user_id": ids.user_id,
                },
            )
            for build_id, created_at in (
                (ids.build_ids[0], oldest + timedelta(days=1)),
                (ids.survivor_id, oldest),
                (ids.build_ids[2], oldest + timedelta(days=2)),
            ):
                await connection.execute(
                    text(
                        """
                        INSERT INTO rag_index_builds (
                            projection_id, id, created_at, updated_at
                        ) VALUES (
                            :projection_id, :build_id, :created_at, :created_at
                        )
                        """
                    ),
                    {
                        "projection_id": ids.projection_id,
                        "build_id": build_id,
                        "created_at": created_at,
                    },
                )
    finally:
        await engine.dispose()


async def _assert_upgraded_shape(settings: Settings, ids: LegacyFixtureIds) -> None:
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            builds = list(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT id, indexing_profile_id, status
                            FROM rag_index_builds
                            WHERE projection_id = :projection_id
                            """
                        ),
                        {"projection_id": ids.projection_id},
                    )
                ).tuples()
            )
            linked_build_id = await connection.scalar(
                text(
                    """
                    SELECT index_build_id
                    FROM rag_ingestion_jobs
                    WHERE job_id = :job_id
                    """
                ),
                {"job_id": ids.job_id},
            )
            constraint_names = set(
                await connection.scalars(
                    text(
                        """
                        SELECT conname
                        FROM pg_constraint
                        WHERE conrelid IN (
                            'rag_index_builds'::regclass,
                            'rag_ingestion_jobs'::regclass
                        )
                        """
                    )
                )
            )
            current_revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        assert builds == [(ids.survivor_id, ids.profile_id, "legacy")]
        assert linked_build_id == ids.survivor_id
        assert "uq_rag_index_builds_projection_id" in constraint_names
        assert "fk_rag_ingestion_jobs_index_build_id" in constraint_names
        assert current_revision == REVISION_0008
    finally:
        await engine.dispose()


async def _cleanup_fixture(settings: Settings, ids: LegacyFixtureIds) -> None:
    engine = create_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM rag_ingestion_jobs WHERE job_id = :job_id"),
                {"job_id": ids.job_id},
            )
            await connection.execute(
                text("DELETE FROM rag_index_builds WHERE projection_id = :projection_id"),
                {"projection_id": ids.projection_id},
            )
            await connection.execute(
                text("DELETE FROM jobs WHERE id = :job_id"), {"job_id": ids.job_id}
            )
            await connection.execute(
                text("DELETE FROM rag_document_projections WHERE id = :projection_id"),
                {"projection_id": ids.projection_id},
            )
            await connection.execute(
                text("DELETE FROM asset_versions WHERE id = :asset_id"),
                {"asset_id": ids.asset_id},
            )
            await connection.execute(
                text("DELETE FROM documents WHERE id = :document_id"),
                {"document_id": ids.document_id},
            )
            await connection.execute(
                text("DELETE FROM workspaces WHERE id = :workspace_id"),
                {"workspace_id": ids.workspace_id},
            )
            await connection.execute(
                text("DELETE FROM rag_profiles WHERE id = :profile_id"),
                {"profile_id": ids.profile_id},
            )
            await connection.execute(
                text("DELETE FROM users WHERE id = :user_id"),
                {"user_id": ids.user_id},
            )
    finally:
        await engine.dispose()


def test_0008_reconciles_duplicate_legacy_builds_before_unique_constraint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = get_settings()
    database = f"ai_workshop_t7_migration_{uuid4().hex}"
    isolated_url = _database_url(base_settings.database_url, database)
    settings = base_settings.model_copy(update={"database_url": isolated_url})
    ids = _fixture_ids()

    _create_database(base_settings.database_url, database)
    try:
        with monkeypatch.context() as environment:
            environment.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
            get_settings.cache_clear()
            config = _alembic_config()
            command.upgrade(config, "head")
            command.downgrade(config, REVISION_0007)
            asyncio.run(_seed_populated_0007(settings, ids))

            command.upgrade(config, REVISION_0008)

            asyncio.run(_assert_upgraded_shape(settings, ids))
            command.upgrade(config, "head")
            command.check(config)
    finally:
        try:
            asyncio.run(_cleanup_fixture(settings, ids))
        finally:
            get_settings.cache_clear()
            _drop_database(base_settings.database_url, database)
