from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from sqlalchemy import func, make_url, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.configurations.domain import (
    BM25_BASELINE_CONFIGURATION_ID,
    BM25_RETRIEVAL_PROFILE_ID,
    E5_INDEXING_PROFILE_ID,
)
from ai_workshop.labs.rag.configurations.models import (
    AnswerPolicyVersionRecord,
    RagConfigurationVersionRecord,
    RagConfigurationWorkspaceSubscriptionRecord,
)
from ai_workshop.labs.rag.configurations.repository import (
    SqlAlchemyRagConfigurationRepository,
    SqlAlchemySearchConfigurationResolver,
)
from ai_workshop.labs.rag.configurations.service import RagConfigurationService
from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord, RagProjectionRecord
from ai_workshop.labs.rag.ingestion.repository import (
    SqlAlchemyRagIngestionCommandRepository,
)
from ai_workshop.labs.rag.ingestion.service import RagIngestionService
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.workspaces.models import (
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ai_workshop.shared.errors import AppError
from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[5]


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def _sync_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def isolated_configuration_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    base_url = get_settings().database_url
    database = f"ai_workshop_t10_resolver_{uuid4().hex}"
    administrative = _database_url(base_url, "postgres")
    with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    isolated_url = _database_url(base_url, database)
    try:
        monkeypatch.setenv("AI_WORKSHOP_DATABASE_URL", isolated_url)
        get_settings.cache_clear()
        command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
        yield isolated_url
    finally:
        get_settings.cache_clear()
        with psycopg.connect(_sync_url(administrative), autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )


async def _seed_actor_workspace(
    session: AsyncSession,
    *,
    label: str,
    with_active_asset: bool,
) -> tuple[UUID, UUID, UUID | None]:
    actor_id = uuid4()
    workspace_id = uuid4()
    session.add(
        UserRecord(
            id=actor_id,
            display_name=f"Actor {label}",
            email=f"{actor_id}@example.test",
            normalized_email=f"{actor_id}@example.test",
            password_hash="fixture-hash",
            role="owner",
            is_active=True,
        )
    )
    await session.flush()
    session.add(
        WorkspaceRecord(
            id=workspace_id,
            name=f"Workspace {label}",
            kind="personal",
            created_by=actor_id,
            expires_at=None,
        )
    )
    await session.flush()
    session.add(
        WorkspaceMembershipRecord(
            workspace_id=workspace_id,
            user_id=actor_id,
            role="owner",
        )
    )
    if not with_active_asset:
        await session.flush()
        return actor_id, workspace_id, None

    document_id = uuid4()
    asset_version_id = uuid4()
    session.add(
        DocumentRecord(
            id=document_id,
            workspace_id=workspace_id,
            folder_id=None,
            name=f"{label}.txt",
            active_version_id=asset_version_id,
        )
    )
    await session.flush()
    session.add(
        AssetVersionRecord(
            id=asset_version_id,
            document_id=document_id,
            number=1,
            object_key=f"fixtures/{asset_version_id}.txt",
            sha256="a" * 64,
            media_type="text/plain",
            size=12,
            status="ready",
        )
    )
    await session.flush()
    return actor_id, workspace_id, asset_version_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_postgres_versions_visibility_jobs_subscriptions_and_exact_resolver(
    isolated_configuration_database_url: str,
) -> None:
    database_url = isolated_configuration_database_url
    engine = create_async_engine(database_url)
    settings = Settings(
        secret_key="task10-integration-secret-key-at-least-32-chars",
        database_url=database_url,
    )
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            owner_id, workspace_id, asset_version_id = await _seed_actor_workspace(
                session,
                label="owner",
                with_active_asset=True,
            )
            other_id, other_workspace_id, _ = await _seed_actor_workspace(
                session,
                label="other",
                with_active_asset=False,
            )
            assert asset_version_id is not None
            repository = SqlAlchemyRagConfigurationRepository(session)
            service = RagConfigurationService(
                repository,
                RagIngestionService(SqlAlchemyRagIngestionCommandRepository(session)),
                commit=session.commit,
            )

            first = await service.create(
                owner_id=owner_id,
                name="비교 구성",
                indexing_profile_id=E5_INDEXING_PROFILE_ID,
                retrieval_profile_id=BM25_RETRIEVAL_PROFILE_ID,
                generation_profile_id=None,
                min_semantic_score=0.81,
                min_keyword_coverage=0.71,
                require_complete_provenance=True,
                conflict_mode="separate_sources",
                workspace_ids=(workspace_id,),
            )
            second = await service.create(
                owner_id=owner_id,
                name="비교 구성",
                indexing_profile_id=E5_INDEXING_PROFILE_ID,
                retrieval_profile_id=BM25_RETRIEVAL_PROFILE_ID,
                generation_profile_id=None,
                min_semantic_score=0.86,
                min_keyword_coverage=0.76,
                require_complete_provenance=True,
                conflict_mode="separate_sources",
                workspace_ids=(workspace_id,),
            )
            other = await service.create(
                owner_id=other_id,
                name="타인 구성",
                indexing_profile_id=E5_INDEXING_PROFILE_ID,
                retrieval_profile_id=BM25_RETRIEVAL_PROFILE_ID,
                generation_profile_id=None,
                min_semantic_score=0.8,
                min_keyword_coverage=0.7,
                require_complete_provenance=True,
                conflict_mode="separate_sources",
                workspace_ids=(other_workspace_id,),
            )

            assert first.configuration.id == second.configuration.id
            assert first.configuration.version_id != second.configuration.version_id
            assert first.indexing_job_ids == second.indexing_job_ids
            assert len(first.indexing_job_ids) == 1
            assert other.indexing_job_ids == ()
            assert await session.scalar(select(func.count()).select_from(JobRecord)) == 1
            assert (
                await session.scalar(
                    select(func.count()).select_from(RagConfigurationVersionRecord).where(
                        RagConfigurationVersionRecord.configuration_id
                        == first.configuration.id
                    )
                )
                == 2
            )
            policies = list(
                await session.scalars(
                    select(AnswerPolicyVersionRecord)
                    .where(
                        AnswerPolicyVersionRecord.configuration_id
                        == first.configuration.id
                    )
                    .order_by(AnswerPolicyVersionRecord.version)
                )
            )
            assert [item.min_semantic_score for item in policies] == [0.81, 0.86]
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(RagConfigurationWorkspaceSubscriptionRecord)
                    .join(
                        RagConfigurationVersionRecord,
                        RagConfigurationVersionRecord.id
                        == RagConfigurationWorkspaceSubscriptionRecord.configuration_version_id,
                    )
                    .where(
                        RagConfigurationVersionRecord.configuration_id
                        == first.configuration.id
                    )
                )
                == 2
            )

            visible = await repository.list_visible(owner_id)
            visible_ids = {item.id for item in visible}
            assert BM25_BASELINE_CONFIGURATION_ID in visible_ids
            assert first.configuration.id in visible_ids
            assert other.configuration.id not in visible_ids
            own_visible = next(item for item in visible if item.id == first.configuration.id)
            assert own_visible.version == 2
            assert own_visible.is_default is False

            subscriptions = await repository.subscriptions_for_asset(asset_version_id)
            assert subscriptions == (
                (E5_INDEXING_PROFILE_ID, owner_id),
            )

            projection = await session.scalar(
                select(RagProjectionRecord).where(
                    RagProjectionRecord.asset_version_id == asset_version_id,
                    RagProjectionRecord.indexing_profile_id == E5_INDEXING_PROFILE_ID,
                )
            )
            assert projection is not None
            projection.status = "ready"
            session.add(
                RagIndexBuildRecord(
                    projection_id=projection.id,
                    indexing_profile_id=E5_INDEXING_PROFILE_ID,
                    index_name=f"ai-workshop-rag-{E5_INDEXING_PROFILE_ID}-{uuid4()}",
                    expected_document_count=1,
                    indexed_document_count=1,
                    vector_dimension=768,
                    status="ready",
                    is_active=True,
                )
            )
            await session.flush()

            resolver = SqlAlchemySearchConfigurationResolver(session, settings)
            resolved = await resolver.resolve(first.configuration.id, owner_id)
            exact_first = await resolver.resolve_version(
                first.configuration.version_id, owner_id
            )

            assert resolved.configuration_version_id == second.configuration.version_id
            assert resolved.configuration_version == 2
            assert resolved.indexing_profile_id == E5_INDEXING_PROFILE_ID
            assert resolved.retrieval_profile.id == BM25_RETRIEVAL_PROFILE_ID
            assert resolved.answer_policy_version_id == (
                second.configuration.answer_policy_version_id
            )
            assert resolved.answer_policy is not None
            assert resolved.answer_policy.min_semantic_score == 0.86
            assert resolved.workspace_ids == (workspace_id,)
            assert resolved.experimental is True
            assert resolved.active_index_alias.indexing_profile_id == E5_INDEXING_PROFILE_ID
            assert resolved.embedding.dimension == 768
            assert exact_first.configuration_version_id == first.configuration.version_id
            assert exact_first.configuration_version == 1
            assert exact_first.answer_policy is not None
            assert exact_first.answer_policy.min_semantic_score == 0.81

            with pytest.raises(AppError) as hidden:
                await resolver.resolve(first.configuration.id, other_id)
            assert hidden.value.status_code == 404
            assert hidden.value.code == "not_found"
            with pytest.raises(AppError) as hidden_version:
                await resolver.resolve_version(first.configuration.version_id, other_id)
            assert hidden_version.value.status_code == 404

        await transaction.rollback()
    await engine.dispose()
