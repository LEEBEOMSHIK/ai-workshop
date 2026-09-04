from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import insert, select

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.deployments.models import DeploymentHealthCheckRecord
from ai_workshop.labs.rag.deployments.repository import (
    DeploymentHealthCheck,
    SecretReference,
    SqlAlchemyDeploymentRepository,
)
from ai_workshop.labs.rag.models.models import ModelDefinitionRecord
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.shared.db import create_engine, create_session_factory
from alembic import command

pytestmark = pytest.mark.integration
BACKEND_ROOT = Path(__file__).resolve().parents[5]


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> None:
    command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "0016_rag_llm_deployments")


@pytest.mark.asyncio
async def test_deployment_version_and_health_check_round_trip() -> None:
    engine = create_engine(get_settings())
    sessions = create_session_factory(engine)
    owner_id = uuid4()
    model_id = uuid4()
    now = datetime.now(UTC)
    deployment = ModelDeploymentVersion(
        id=uuid4(),
        deployment_id=uuid4(),
        version=1,
        display_name="OpenAI synthetic deployment",
        description="Public synthetic integration fixture",
        model_definition_id=model_id,
        provider=ProviderKind.OPENAI_RESPONSES,
        location=ExecutionLocation.EXTERNAL,
        allowed_environments=(
            DeploymentEnvironment.DEVELOPMENT,
            DeploymentEnvironment.PRODUCTION,
        ),
        provider_model_id="synthetic/exact-model",
        endpoint_ref="openai-responses",
        secret_ref="openai-primary",
        capabilities=frozenset(
            {
                DeploymentCapability.STRUCTURED_OUTPUT,
                DeploymentCapability.TOKEN_ACCOUNTING,
            }
        ),
        external_transfer=True,
        transmitted_data_categories=("question", "evidence"),
        data_processing_notice_ref="openai-data-notice-v1",
        timeout_seconds=20.0,
        max_retries=1,
        retry_backoff_seconds=0.25,
        healthcheck_enabled=True,
        development_only=False,
        created_by=owner_id,
        created_at=now,
    )
    health = DeploymentHealthCheck(
        id=uuid4(),
        deployment_version_id=deployment.id,
        status="ready",
        safe_error_code=None,
        observed_provider_model_id="synthetic/exact-model",
        latency_ms=14,
        checked_by=owner_id,
        created_at=now,
    )
    try:
        async with sessions() as session:
            transaction = await session.begin()
            try:
                await session.execute(
                    insert(UserRecord).values(
                        id=owner_id,
                        display_name="Deployment owner",
                        email=f"{owner_id}@example.test",
                        normalized_email=f"{owner_id}@example.test",
                        password_hash="fixture-hash",
                        role="owner",
                        is_active=True,
                    )
                )
                await session.execute(
                    insert(ModelDefinitionRecord).values(
                        id=model_id,
                        kind="llm",
                        name=f"synthetic-{model_id}",
                        version=1,
                        config={},
                    )
                )
                repository = SqlAlchemyDeploymentRepository(session)
                await repository.register_secret_reference(
                    SecretReference(
                        reference_name="openai-primary",
                        created_by=owner_id,
                        created_at=now,
                    )
                )

                saved = await repository.add_version(deployment)
                await repository.add_health_check(health)

                assert saved == deployment
                assert await repository.get_version(deployment.id) == deployment
                assert await repository.latest_health_check(deployment.id) == health
                assert (
                    await session.scalar(
                        select(DeploymentHealthCheckRecord.status).where(
                            DeploymentHealthCheckRecord.id == health.id
                        )
                    )
                    == "ready"
                )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
