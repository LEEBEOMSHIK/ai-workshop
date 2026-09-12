from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings
from ai_workshop.labs.rag.configurations.repository import (
    SqlAlchemyRagConfigurationRepository,
)
from ai_workshop.labs.rag.deployments.domain import DeploymentEnvironment, ProviderKind
from ai_workshop.labs.rag.deployments.repository import (
    SqlAlchemyDeploymentRepository,
)
from ai_workshop.labs.rag.generation.codex_composition import codex_services
from ai_workshop.labs.rag.generation.codex_verification import CodexVerificationService


class SqlAlchemyGenerationReadiness:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        actor_id: UUID | None = None,
        verification: CodexVerificationService | None = None,
    ) -> None:
        self.settings = settings
        self.actor_id, self.verification = actor_id, verification
        self.profiles = SqlAlchemyRagConfigurationRepository(session)
        self.deployments = SqlAlchemyDeploymentRepository(session)

    async def is_ready(
        self, profile_id: UUID, *, configuration_version_id: UUID | None = None
    ) -> bool:
        profile = await self.profiles.find_profile(profile_id)
        if profile is None or profile.bindings or profile.deployment_version_id is None:
            return False
        deployment = await self.deployments.get_version(profile.deployment_version_id)
        if deployment is None:
            return False
        if deployment.provider is ProviderKind.DEVELOPMENT_CODEX_EXEC:
            actor_id = getattr(self, "actor_id", None)
            if actor_id is None or configuration_version_id is None:
                return False
            try:
                configuration = await self.profiles.find_version_visible(
                    configuration_version_id, actor_id
                )
                if configuration is None or configuration.generation_profile_id != profile_id:
                    return False
                if self.verification is not None:
                    result = await self.verification.status(
                        actor_id=actor_id, configuration_version_id=configuration_version_id
                    )
                else:
                    async with codex_services(self.settings) as services:
                        result = await services.verification.status(
                            actor_id=actor_id, configuration_version_id=configuration_version_id
                        )
                return result.ready is True
            except Exception:
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
