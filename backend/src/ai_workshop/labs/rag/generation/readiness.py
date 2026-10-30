from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings
from ai_workshop.labs.rag.configurations.repository import (
    SqlAlchemyRagConfigurationRepository,
)
from ai_workshop.labs.rag.deployments.domain import (
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.deployments.endpoint_policy import validate_endpoint_dialect
from ai_workshop.labs.rag.deployments.repository import (
    SqlAlchemyDeploymentRepository,
)
from ai_workshop.labs.rag.generation.codex_composition import codex_services
from ai_workshop.labs.rag.generation.codex_verification import CodexVerificationService
from ai_workshop.labs.rag.generation.numeric_validation_repository import numeric_storage_ready
from ai_workshop.labs.rag.models.context_evidence import resolve_evidence_budget
from ai_workshop.labs.rag.models.domain import Profile
from ai_workshop.labs.rag.models.orchestration_policy import (
    resolve_orchestration_policy,
    supports_orchestration_binding,
)
from ai_workshop.labs.rag.models.provider_policy import validate_provider_profile_config


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
        self.session = session
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
        return await self.is_ready_for(
            profile, deployment, configuration_version_id=configuration_version_id
        )

    async def is_ready_for(
        self,
        profile: Profile,
        deployment: ModelDeploymentVersion,
        *,
        configuration_version_id: UUID | None = None,
    ) -> bool:
        """Check current readiness using inputs resolved in this request only."""
        if profile.bindings or profile.deployment_version_id != deployment.id:
            return False
        try:
            validate_provider_profile_config(profile.config, deployment)
            validate_endpoint_dialect(deployment.provider, deployment.endpoint_ref or "",
                                      getattr(self.settings, "provider_endpoint_dialects", {}))
        except ValueError:
            return False
        if profile.config.get("prompt_ref") in {"rag-answer-v5", "rag-answer-v6"} and (
            deployment.provider is not ProviderKind.LOCAL_OPENAI_COMPATIBLE
            or deployment.location is not ExecutionLocation.LOCAL
        ):
            return False
        generation = profile.config.get("generation")
        if profile.config.get("prompt_ref") == "rag-answer-v6":
            try:
                budget = resolve_evidence_budget(profile.config)
            except ValueError:
                return False
            if (budget is None or budget.max_units > 200 or not isinstance(generation, Mapping)
                    or type(generation.get("response_schema_version")) is not int
                    or generation["response_schema_version"] != 2):
                return False
        try:
            orchestration = resolve_orchestration_policy(profile.config)
        except ValueError:
            return False
        if orchestration is not None and not supports_orchestration_binding(
            deployment,
            generation.get("response_schema_version") if isinstance(generation, Mapping) else None,
        ):
            return False
        if (orchestration is not None and orchestration.local_http_api == "ollama_chat"
                and self.settings.provider_endpoint_dialects.get(deployment.endpoint_ref or "")
                != "ollama"):
            return False
        if (
            isinstance(generation, Mapping)
            and generation.get("response_schema_version") == 3
            and deployment.provider is not ProviderKind.DEVELOPMENT_CODEX_EXEC
        ):
            return False
        if deployment.provider is ProviderKind.DEVELOPMENT_CODEX_EXEC:
            if (
                isinstance(generation, Mapping)
                and generation.get("response_schema_version") == 3
                and not await numeric_storage_ready(self.session)
            ):
                return False
            actor_id = getattr(self, "actor_id", None)
            if actor_id is None or configuration_version_id is None:
                return False
            try:
                configuration = await self.profiles.find_version_visible(
                    configuration_version_id, actor_id
                )
                if configuration is None or configuration.generation_profile_id != profile.id:
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
