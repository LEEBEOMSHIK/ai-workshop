from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings
from ai_workshop.labs.rag.configurations.repository import (
    SqlAlchemyRagConfigurationRepository,
)
from ai_workshop.labs.rag.deployments.domain import DeploymentEnvironment
from ai_workshop.labs.rag.deployments.repository import (
    SqlAlchemyDeploymentRepository,
)


class SqlAlchemyGenerationReadiness:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.settings = settings
        self.profiles = SqlAlchemyRagConfigurationRepository(session)
        self.deployments = SqlAlchemyDeploymentRepository(session)

    async def is_ready(self, profile_id: UUID) -> bool:
        profile = await self.profiles.find_profile(profile_id)
        if (
            profile is None
            or profile.bindings
            or profile.deployment_version_id is None
        ):
            return False
        deployment = await self.deployments.get_version(profile.deployment_version_id)
        if deployment is None:
            return False
        environment = _normalized_environment(self.settings.environment)
        if (
            environment not in deployment.allowed_environments
            or deployment.development_only
            and environment is not DeploymentEnvironment.DEVELOPMENT
        ):
            return False
        health = await self.deployments.latest_health_check(deployment.id)
        return bool(
            health is not None
            and health.status == "ready"
            and health.safe_error_code is None
            and health.observed_provider_model_id == deployment.provider_model_id
        )


def _normalized_environment(environment: str) -> DeploymentEnvironment:
    if environment in {"local", "test"}:
        return DeploymentEnvironment.DEVELOPMENT
    return DeploymentEnvironment.PRODUCTION
